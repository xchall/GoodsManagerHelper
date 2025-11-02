from fastapi import FastAPI, HTTPException, Response, Depends, Request, status
from pydantic import BaseModel
from typing import Optional, Any, Dict
from itsdangerous import URLSafeSerializer, BadSignature
import mysql.connector
from mysql.connector import Error
from yandex_cloud_ml_sdk import YCloudML
from main_module7 import run_with_tools, assistant
import dotenv
from dotenv import load_dotenv
import os

load_dotenv()

folder_id = os.getenv("FOLDER_ID_YANDEX")
api_key = os.getenv("API_KEY_YANDEX")
sdk = YCloudML(folder_id=folder_id, auth=api_key)

mysql_log=os.getenv("MYSQL_LOG")
mysql_pass=os.getenv("MYSQL_PASS")

DB_CONFIG = {
    "host": "localhost",
    "user": mysql_log,
    "password": mysql_pass,
    "database": "sauna_goods"
}

SECRET_KEY = os.getenv("SECRET_KEY")
SIGNER = URLSafeSerializer(SECRET_KEY, salt="session")
COOKIE_NAME = "session"

app = FastAPI()

# -------------------- Модели --------------------
class LoginData(BaseModel):
    login: str
    password: str

class PromptRequest(BaseModel):
    prompt: str

#-------------------------------------------------
def get_user_from_db(login: str, password: str):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE login = %s AND password = %s", (login, password))
        user = cur.fetchone()
        cur.close()
        conn.close()
        return user
    except Error as e:
        print("DB error:", e)
        return None

def get_user_by_login(login: str) -> Optional[Dict[str, Any]]:
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT login FROM users WHERE login=%s", (login,))
        u = cur.fetchone()
        cur.close(); conn.close()
        return u
    except Error as e:
        print("DB error:", e)
        return None
# -------------------- Куки/сессия --------------------
def set_session_cookie(resp: Response, payload: dict, *, secure=False):
    token = SIGNER.dumps(payload)
    resp.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,     # в проде под HTTPS = True
        samesite="Lax",
        path="/",
        max_age=60*60*8,   # 8 часов
    )

def clear_session_cookie(resp: Response):
    resp.delete_cookie(COOKIE_NAME, path="/")

def require_user(request: Request) -> Dict[str, Any]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    try:
        data = SIGNER.loads(token)
    except BadSignature:
        raise HTTPException(status_code=401, detail="invalid session")

    login = data.get("login")
    if not login:
        raise HTTPException(status_code=401, detail="invalid session")

    u = get_user_by_login(login)
    if not u:
        raise HTTPException(status_code=401, detail="user not found")
    return {"login": u["login"]}

# -------------------- Роуты --------------------
@app.post("/login")
def login(data: LoginData, response: Response):
    u = get_user_from_db(data.login.strip(), data.password)
    if not u:
        raise HTTPException(status_code=401, detail="invalid credentials")
    # Модифицируем исходящий ответ: ставим HttpOnly-куку
    set_session_cookie(response, {"login": u["login"]}, secure=False)
    # Возвращаем тело ответа; кука уже прикреплена к этому же ответу
    return {"ok": True, "user": u["login"]}

#Если внутри require_user происходит raise HTTPException(...), FastAPI не вызовет me(...), а сразу отправит ответ с указанным статусом ( 401).
@app.get("/me")
def me(user=Depends(require_user)):
    # если нужен id на фронте — добавь "id": user["id"]
    return {"login": user["login"]}

@app.post("/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}

@app.post("/generate")
async def generate_text(request: PromptRequest):
    """Генерация текста по промпту."""
    thread = sdk.threads.create(ttl_days=1, expiration_policy="static")
    result = run_with_tools(assistant, thread, request.prompt)
    print(result)
    return {"response": result}

@app.get("/health")
async def health_check():
    """Проверка работоспособности сервера."""
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000
)
