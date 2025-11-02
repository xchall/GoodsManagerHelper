import pydantic
import weaviate
from charset_normalizer.cli import query_yes_no
from weaviate.classes.init import Auth
from weaviate.classes.config import Configure, Property, DataType
import dotenv
from dotenv import load_dotenv
import os
import json
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.search_indexes import (
    StaticIndexChunkingStrategy,
    HybridSearchIndexType,
    ReciprocalRankFusionIndexCombinationStrategy,
)
import mysql.connector
from mysql.connector import Error
from pydantic import BaseModel, Field
from typing import List, Union
import re


load_dotenv() #загружаем переменные среды из .env файла


weaviate_url = os.getenv("WEAVIATE_URL") #REST endpoint
weaviate_api_key = os.getenv("WEAVIATE_API_KEY")

client = weaviate.connect_to_weaviate_cloud(
    cluster_url=weaviate_url,
    auth_credentials=Auth.api_key(weaviate_api_key),
)

print(client.is_ready())



folder_id = os.getenv("FOLDER_ID_YANDEX")
api_key = os.getenv("API_KEY_YANDEX")
sdk = YCloudML(folder_id=folder_id, auth=api_key)


def clamp(PER_KEY_MAX, s: str) -> str:
    if not s:
        return ""
    return s if len(s) <= PER_KEY_MAX else s[:PER_KEY_MAX] + " … [truncated]"

def to_text(x):
    return "" if x is None else str(x)
mysql_log=os.getenv("MYSQL_LOG")
mysql_pass=os.getenv("MYSQL_PASS")
def get_description_by_id(good_id:int, length_list:int):
    connection = mysql.connector.connect(
        host='localhost',
        database='sauna_goods',
        user=mysql_log, #на линуксе пользователь chatbot, и соотвествующий пароль для него
        password=mysql_pass,
    )
    cursor = connection.cursor()
    select_query = """
        SELECT good_id, title, code, price, characteristics, description
        FROM about_goods
        WHERE good_id = %s
        """

    cursor.execute(select_query, (good_id,))
    row = cursor.fetchone()
    connection.close()
    if not row:
        return ""

    title = to_text(row[1])
    code = to_text(row[2])
    price = to_text(row[3])
    chars = to_text(row[4])
    if length_list == 1:
        desc = clamp(1400, to_text(row[5]))  # 1400 -> около 350 токенов оставим
    elif length_list > 1:
        desc = clamp(800, to_text(row[5])) # около 200 токенов на описание оставим

    return " ".join([
        title,
        "Артикул: " + code + ".",
        "Цена в рублях: " + price + ".",
        chars,
        desc
    ]).strip()


def get_descriptions_by_ids(ids: List):
    goods_with_descriptions = []
    for id in ids:
        goods_with_descriptions.append(get_description_by_id(int(id),len(ids)))
    return goods_with_descriptions

def goods_vector_search(vec_query:str, database_name:str = "GoodsListWithID", search_limit:int = 10):
    goods_list = client.collections.use(database_name)
    response = goods_list.query.near_text(
        query=vec_query,
        limit=search_limit
    )
    found_chunks = []
    for obj in response.objects:
        content = obj.properties['content']
        found_chunks.append(str(obj.properties['content']))
        # print(str(obj.properties['content']))
    return found_chunks


def hoare_sort_pairs(arr):
    """ Сортировка Хоара для пар (chunk, price) по значению price """

    if len(arr) <= 1:
        return arr

    # Выбираем опорный элемент (берем price из среднего элемента)
    pivot = arr[len(arr) // 2][1]

    # Разделяем на три части
    left = []
    middle = []
    right = []

    for pair in arr:
        if pair[1] < pivot:
            left.append(pair)
        elif pair[1] == pivot:
            middle.append(pair)
        else:
            right.append(pair)

    # Рекурсивно сортируем левую и правую части
    return hoare_sort_pairs(left) + middle + hoare_sort_pairs(right)

def find_cheap_expensive_middle_goods(vec_query:str, flag:int = 1, search_limit:int =  50):
    search_limit += 3 #для перекрытия нахождения небольшой погрешности (в результат векторного поиска втискивается лишнее)
    database_name = "GoodsListWithIDWithoutCharacteristics"
    chuncks = goods_vector_search(vec_query, database_name, search_limit)
    chunks_and_price = []
    for chunk in chuncks:
        match = re.search(r'Цена за единицу в рублях:\s*(\d[\d\s]*)', chunk)
        if match:
            price = match.group(1).replace(' ', '')  # убираем пробелы
            chunks_and_price.append((chunk, int(price)))
    #сортируем по возрастанию
    sorted_by_price_chunks = hoare_sort_pairs(chunks_and_price)
    if flag == 1: #самые дешевые
        return sorted_by_price_chunks[0:15]

    elif flag == 2: #средней ценовой категории
        return sorted_by_price_chunks[search_limit//2 - 7:search_limit//2 + 7]

    elif flag == 3: #самые дорогие
        return sorted_by_price_chunks[search_limit-15:search_limit-1]



# res = find_cheap_expensive_middle_goods("Электропечи", 1)
# print("____________\n\n\n\n\n\n")
# for chunk, price in res:
#     print(chunk, price)
def sanitize_ids(raw) -> list[int]:
    out = []
    for x in raw:
        try:
            out.append(int(float(x)))
        except Exception:
            pass
    # уникально, в исходном порядке
    return list(dict.fromkeys(out))

class GetDescriptionsByIds(BaseModel):
    """Функция возвращает описания товаров по списку их идентификаторов (целых чисел)."""

    ids: List[Union[int, float, str]] = Field(description="Список идентификаторов объектов")

    def process(self):
        clean = sanitize_ids(self.ids)
        if not clean:
            return {"status": "INVALID_ARGS", "message": "ids пусты/некорректны"}
        return {"status": "OK", "descriptions": get_descriptions_by_ids(clean)}


class GoodsVectorSearch(BaseModel):
    """Возвращает список товаров ниболее подходящих к запросу, используя векторный поиск."""

    vec_query: str = Field(description="Запрос пользователя, по которому будем искать товары в векторной базе")
    database_name: str = Field(description="Нзвание базы в кторой будем отбирать чанки товаров")
    search_limit: int = Field(description="Сколько чанков отобрать")
    def process(self):
        return {"goods": goods_vector_search(self.vec_query, self.database_name, self.search_limit)}

class FindCheapExpensiveMiddleGoods(BaseModel):
    """Возвращает список товаров какого-то вида либо самых дешевых, либо самых дорогих, либо средней ценовой категории."""

    vec_query: str = Field(description="Запрос пользователя, по которому будем искать товары в векторной базе")
    flag:int = Field(description="1 - самые дешевые ищем, 2- ищем средней ценовой категории, 3- ищем самые дорогие")
    search_limit:int = Field(description="Сколько чанков найдем перед выбором дешевого/средней цены/дорогого")

    def process(self):
        return {"goods": find_cheap_expensive_middle_goods(self.vec_query, self.flag, self.search_limit)}

get_desc_tool = sdk.tools.function(
    GetDescriptionsByIds,
    name="GetDescriptionsByIds",
    description="Возвращает список описнаий товаров по списку их идентификаторов."
)
goods_vector_search_tool = sdk.tools.function(
    GoodsVectorSearch,
    name="GoodsVectorSearch",
    description="Возвращает список товаров ниболее подходящих к запросу."
)
find_cheap_expensive_middle_goods_tool = sdk.tools.function(
    FindCheapExpensiveMiddleGoods,
    name="FindCheapExpensiveMiddleGoods",
    description="Возвращает список либо самых дешевых, либо средней цены, либо самых дорогих товаров"
)
main_search_tool = sdk.tools.search_index("fvth9d4ph4l4lui0ulss", max_num_results=5) #получаем по id и 5 чанков получаем при поиске


assistant = sdk.assistants.create(
    model = sdk.models.completions("gpt-oss-120b", model_version="latest"),
    temperature=0.1,
    instruction=(
        """
        Ты — менеджер магазина бань/саун. Отвечай ТОЛЬКО по контексту.
        «Если запрос относится к товарам (поиск/описания/дорогие/дешёвые), обязательно сначала вызови соответствующий инструмент (PRICE или GVS, а при необходимости DESC). Запрещено формировать ответ без результата инструментов.»
        ИНСТРУМЕНТЫ
        search_index — гибридный поиск по общим книжным материалам (НЕ про товары магазина).
        GoodsVectorSearch (GVS) — найти товары по запросу. ВЫЗЫВАТЬ НЕ БОЛЕЕ 1 РАЗ.
          Аргументы (JSON): {"vec_query":<str>,"database_name":<str>,"search_limit":<int>}
          Ровно один из пресетов:
            - {"database_name":"GoodsListWithID","search_limit":10}   (нужны характеристики)
            - {"database_name":"GoodsListWithIDWithoutCharacteristics","search_limit":15} (без характеристик)
          В ответе пользователю всегда указывай ID найденных товаров (служебно).
        GetDescriptionsByIds (DESC) — получить подробные описания по ID. ВЫЗЫВАТЬ НЕ БОЛЕЕ 1 РАЗ.
          Аргументы (JSON): {"ids":[<int>,<int>,...]}  (строго целые числа, максимум 2 ID).
          ПОСЛЕ УСПЕШНОГО DESC — СРАЗУ формируй финальный ответ, БЕЗ новых инструментов.
          После GetDescriptionsByIds нелья вызывать FindCheapExpensiveMiddleGoods
        FindCheapExpensiveMiddleGoods (PRICE) — выбрать дешёвые/средние/дорогие. ВЫЗЫВАТЬ НЕ БОЛЕЕ 1 РАЗ.
          Аргументы (JSON): {"vec_query":<str>,"flag":<int 1|2|3>,"search_limit":<int>}
          Выбирай категорию/подкатегорию из каталога ниже и ставь её объём товаров в search_limit.
          Если объём = 0 — не вызывай PRICE, сообщи что таких товаров нет.

        ОБЩИЕ ПРАВИЛА
        1) Не придумывай данные. Если нет в контексте — так и скажи.
        2) Один ход = максимум ОДИН вызов инструмента. Жди результата, потом решай следующий шаг.
        3) Не вызывай один и тот же инструмент повторно (даже если аргументы разные).
        4) Любая ошибка/пустой ответ инструмента → сформируй ответ из имеющихся данных (или попроси уточнение), НЕ вызывая другие инструменты в этом запросе.
        5) Цены всегда с валютой (руб.).
        6) Если инструмент указан в Must_not_to_call, его НЕЛЬЗЯ ВЫЗЫВАТЬ.

        АЛГОРИТМ (кратко)
        A) Если вопрос про общие знания (не про товары) → search_index. При желании затем порекомендуй товары (через GVS/PRICE), но только если это уместно.
        B) Если про товары:
           - Если запрошены «дорогие/средней цены/дешёвые» → сначала PRICE (flag: 3/2/1), затем при необходимости DESC.
           - Иначе → GVS (выбери нужный пресет). Если требуются подробные описания → затем DESC.
        C) После DESC — сразу финальный ответ.

        ФОРМАТ КОНТЕКСТА GVS
        Каждая строка — отдельный товар. В начале строки всегда есть «ID <число>». Пример: «ID 12 ...».

        ПРИМЕРЫ JSON-ВЫЗОВОВ
        • GVS: {"vec_query":"электропечь Harvia до 60000","database_name":"GoodsListWithID","search_limit":10}
        • DESC: {"ids":[12,45]}
        • PRICE: {"vec_query":"стеклянная дверь","flag":3,"search_limit":126}

        — — — КАТАЛОГ (НЕ МЕНЯТЬ) — — —
        cat Дровяные печи 288
        ___ subcat Feringer 54
        ___ ___ subsubcat Печи 24
        ___ ___ subsubcat Отопительные котлы 6
        ___ ___ subsubcat Дымоходы и комплектующие 24
        ___ subcat Harvia 24
        ___ subcat Атмосфера 24
        ___ subcat Костёр 24
        ___ subcat Grill`D 24
        ___ subcat Гефест 24
        ___ subcat Везувий 24
        ___ subcat ASTON 21
        ___ subcat Пегас 24
        ___ subcat Термофор 0
        ___ subcat Kastor 0
        ___ subcat EOS 0s
        cat Камни для печи 24
        ___ subcat Камни для печи 24
        cat Дымоходы и баки 60
        ___ subcat Дымоходы Теплов и Сухов 24
        ___ subcat УМК  24
        ___ subcat Баки и теплообменники 3
        ___ subcat Феникс 1
        ___ subcat Дымоходы Вермилоджик 0
        ___ subcat Гефест 8
        ___ subcat Феррум 0
        cat Электрокаменки(это электрические печи) 138 (только учитываем сами электрокаменки)
        ___ subcat KARINA  24
        ___ subcat Tylo 0
        ___ subcat Helo 4
        ___ subcat Sangens  10
        ___ subcat Henki 4
        ___ subcat Костёр 0
        ___ subcat Ресурс Электрокотел 24
        ___ subcat Sawo 24
        ___ subcat BORN 24
        ___ subcat Harvia 24
        ___ subcat Политех 0
        ___ subcat EOS 0
        ___ subcat Ограждения, фланцы 24 (не являются самими электрокаменками)
        ___ subcat Комплектующие 24 (не являются самими электрокаменками)
        ___ subcat Тэны 24 (не являются самими электрокаменками)
        ___ subcat Прочее 24 (не являются самими электрокаменками)
        cat Пульты управления 49
        ___ subcat Sawo 18
        ___ subcat Harvia 10
        ___ subcat Политех 0
        ___ subcat KARINA 4
        ___ subcat Костёр 3
        ___ subcat Sangens 4
        ___ subcat Ресурс Электрокотел 7
        ___ subcat BORN 3
        cat Парогенераторы 39
        ___ subcat Sawo 20
        ___ subcat Harvia 4
        ___ subcat Grandis 15
        cat Пиломатериалы 191
        ___ subcat Вагонка 24
        ___ subcat Полок 24
        ___ subcat Липа 24
        ___ subcat Ольха 24
        ___ subcat Осина 0
        ___ subcat Абаш 16
        ___ subcat Кедр 6
        ___ subcat Термодревесина 24
        ___ subcat Плинтус и уголки 24
        ___ subcat Пропитки для дерева 1
        ___ subcat Прочее 24
        cat Гималайская соль 56
        ___ subcat Соляная плитка 24
        ___ subcat Соляные лампы 24
        ___ subcat Клеевая смесь 2
        ___ subcat Пищевая соль 6
        cat Двери 126
        ___ subcat Sawo 13
        ___ subcat Grandis 15
        ___ subcat Ecodoors 24
        ___ subcat Harvia 24
        ___ subcat Россия 17
        ___ subcat Doorwood 24
        ___ subcat Арта 9
        cat Аксессуары и комплектующие 693
        ___ subcat Термометры и гигрометры 24
        ___ subcat Термогигрометры 24
        ___ subcat Термометры 14
        ___ subcat Гигрометры 24
        ___ subcat Часы 24
        ___ subcat Песочные часы 24
        ___ subcat Часы вне сауны 8
        ___ subcat Запарники и шайки 24
        ___ subcat Sawo 24
        ___ subcat Китай 24
        ___ subcat Россия 24
        ___ subcat Harvia 1
        ___ subcat Tammer-Tukku 1
        ___ subcat Woodson 5
        ___ subcat Черпаки и ковши 24
        ___ subcat Sawo 9
        ___ subcat Китай 17
        ___ subcat Россия 24
        ___ subcat Harvia 0
        ___ subcat Tylo 1
        ___ subcat Tammer-Tukku 1
        ___ subcat Woodson 4
        ___ subcat Щетки для мытья 4
        ___ subcat Подголовники 17
        ___ subcat Sawo 3
        ___ subcat Китай 6
        ___ subcat Россия 8
        ___ subcat Tammer-Tukku 0
        ___ subcat Ароматизаторы 24
        ___ subcat Sawo 4
        ___ subcat Harvia 2
        ___ subcat Другие 24
        ___ subcat Веники для бани 17
        ___ subcat Обливные устройства 19
        ___ subcat Комплектующие 24
        ___ subcat Sawo 24
        ___ subcat Grandis 4
        ___ subcat Harvia 24
        ___ subcat Прочее 24
        ___ subcat Sawo 18
        ___ subcat Harvia 4
        ___ subcat Другие 24
        ___ subcat Шапки 24
        ___ subcat Россия 24
        ___ subcat Текстиль 23
        ___ subcat Текстиль 23
        cat Освещение 39
        ___ subcat Лампы и светодиоды 13
        ___ subcat Cariitti 2
        ___ subcat Абажуры 24
        cat Все для хамама 141
        ___ subcat Парогенераторы 19
        ___ subcat Sawo 16
        ___ subcat Harvia 3
        ___ subcat Grandis 0
        ___ subcat Двери 24
        ___ subcat Sawo 2
        ___ subcat Grandis 7
        ___ subcat Harvia 24
        ___ subcat Освещение 11
        ___ subcat Cariitti 11
        ___ subcat Tylo 0
        ___ subcat Курны 24
        cat Аттракционы для бани 0
        cat Инфракрасные сауны 16
        ___ subcat Оборудование для сухих бань 16
        cat Готовые сауны 2
        cat Купели 35
        ___ subcat Купель из массива дерева 24
        ___ subcat Купель из пластика 11
        cat Облицовка 24
        cat Окна 7
        cat Чаны DUKO 2
        cat Мебель для бани 12
        ___ subcat Sawo 6
        ___ subcat Прочее 6
        """
    ),
    tools=[main_search_tool, get_desc_tool, goods_vector_search_tool, find_cheap_expensive_middle_goods_tool],
)

#классы а не просто методы, для валидации аргументов с использование pydantic
LOCAL_TOOLS = {
    "GetDescriptionsByIds": GetDescriptionsByIds,
    "GoodsVectorSearch": GoodsVectorSearch,
    "FindCheapExpensiveMiddleGoods": FindCheapExpensiveMiddleGoods
}


# def clamp_per_key_1200(obj: dict) -> dict: #без этого из-за огромных описаний выходим за предельный размер 7000 токенов контекста модели
#     out = {}
#     for k, v in obj.items():
#         s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
#         out[k] = s if len(s) <= PER_KEY_MAX else s[:PER_KEY_MAX] + TRUNC
#     return out
def run_with_tools(assistant, thread, prompt: str) -> str:

    thread.write(prompt)
    run = assistant.run(thread)
    res = run.wait()
    rounds = 0
    MAX_ROUNDS = 4  # чтобы исключить зацикливание
    # В некоторых случаях может быть несколько раундов tool_calls,
    # поэтому делаем цикл, пока модель что-то запрашивает
    tools_not_to_call = "" #теперь снова можно вызывать любой инструмент
    while getattr(res, "tool_calls", None):
        print(getattr(res, "tool_calls", None))
        rounds += 1
        if rounds > MAX_ROUNDS:
            return {"ok": False, "status": "TOO_MANY_TOOL_ROUNDS", "error": "tool-calls loop detected"}
        tool_results = []

        for call in res.tool_calls:
            name = call.function.name
            args = call.function.arguments
            # print(call)
            print(f"[tool] {name}({args})")

            if name == "GetDescriptionsByIds":
                tools_not_to_call += "name " + "(DESC), "
            elif name == "GoodsVectorSearch":
                tools_not_to_call += "name " + "(GVS), "
            elif  name == "FindCheapExpensiveMiddleGoods":
                tools_not_to_call += "name " + "(PRICE), "
            #Берём локальный класс-инструмент
            ToolClass = LOCAL_TOOLS.get(name) #ToolClass - ссылка например на GetDescriptionsByIds

            try:
                #Валидируем вход через Pydantic и запускаем  .process()
                obj = ToolClass(**args) #Например объект класса GetDescriptionsByIds
                content = obj.process()   # вызываем process от объекта класса
            except Exception as e:
                # Чтобы видеть реальную причину падения, возвращаем ошибку как контент
                content = {"error": repr(e)}

            #Контент должен быть JSON-сериализуемым (например словарь)
            # print(content)
            # safe_content = clamp_per_key_1200(content)
            payload = json.dumps(content, ensure_ascii=False)
            tool_results.append({
                "tool_call_id": rounds,
                "Must_not_to_call": tools_not_to_call,
                "name": name,
                "content": payload}
            )
            break #за один раунд один tool

        #Отдаём результаты инструментов модели и ждём следующий шаг
        try:
            run.submit_tool_results(tool_results=tool_results)
        except Exception as e:
            return {"ok": False, "status": "SUBMIT_TOOL_RESULTS_ERROR", "error": repr(e)}
        res = run.wait()

    #Когда tool_calls больше нет — это финальный ответ
    try:
        return res.text
    except Exception:
        # полезно вывести служебную инфу из run/res
        details = {}
        for attr in ("state", "status", "error", "error_message"):
            val = getattr(res, attr, None)
            if val:
                details[attr] = str(val)
        return json.dumps({"ok": False, "status": "RUN_FAILED", "details": details}, ensure_ascii=False)

__all__ = ["sdk", "assistant", "run_with_tools"]
