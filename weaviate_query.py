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


def classify(prompt: str) -> dict:
    res = model_classificator.run([
        {"role": "system", "text": SYSTEM},
        {"role": "user", "text": prompt}
    ])

    text = res.text
    return json.loads(text)

load_dotenv() #загружаем переменные среды из .env файла


weaviate_url = os.getenv("WEAVIATE_URL") #REST endpoint
weaviate_api_key = os.getenv("WEAVIATE_API_KEY")

client = weaviate.connect_to_weaviate_cloud(
    cluster_url=weaviate_url,
    auth_credentials=Auth.api_key(weaviate_api_key),
)

print(client.is_ready())  # Should print: `True`



folder_id = os.getenv("FOLDER_ID_YANDEX")
api_key = os.getenv("API_KEY_YANDEX")
sdk = YCloudML(folder_id=folder_id, auth=api_key)
model_classificator = (
    sdk.models.completions("yandexgpt")
    .configure(
        temperature=0.0,
        max_tokens=20,
        response_format="json" # строго JSON
    )
)

def to_text(x):
    return "" if x is None else str(x)

def get_description_by_id(good_id:int):
    connection = mysql.connector.connect(
        host='localhost',
        database='sauna_goods',
        user='root',
        password='ghyRe3rTd'
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
    if not row:  # нет записи
        return ""
    # ВСЕГДА приводим к str ПЕРЕД join/конкатенацией
    return " ".join([
        to_text(row[1]), "Артикул: " + to_text(row[2]) +".",
        "Цена в рублях: " + to_text(row[3])+".", to_text(row[4]), to_text(row[5])
    ]).strip()


def get_descriptions_by_ids(ids: List):
    goods_with_descriptions = []
    for id in ids:
        goods_with_descriptions.append(get_description_by_id(int(id)))
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
        print(str(obj.properties['content']))
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
        if search_limit == 50:
            return sorted_by_price_chunks[0:15]
        else:
            return sorted_by_price_chunks[0:20]
    elif flag == 2: #средней ценовой категории
        if search_limit == 50:
            return sorted_by_price_chunks[15:35]
        else:
            return sorted_by_price_chunks[65:85]
    elif flag == 3: #самые дорогие
        if search_limit == 50:
            return sorted_by_price_chunks[35:50]
        else:
            return sorted_by_price_chunks[139:150]


# res = find_cheap_expensive_middle_goods("Электропечи", 1)
# print("____________\n\n\n\n\n\n")
# for chunk, price in res:
#     print(chunk, price)

class GetDescriptionsByIds(BaseModel):
    """Функция возвращает описания товаров по списку их идентификаторов."""

    ids: List[Union[int, float, str]] = Field(description="Список идентификаторов объектов")

    def process(self):
        return {"descriptions": get_descriptions_by_ids(self.ids)}


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




assistant = sdk.assistants.create(
    model="yandexgpt",
    instruction=(
        "Ты — менеджер магазина оборудования для бань/саун. Отвечай только по контексту."
        "Каждый инструмент можно использовать только 1 раз"
        
        "У ТЕБЯ ЕСТЬ ИНСТРУМЕНТ GoodsVectorSearch. Вызывай его, когда тебе необходимо найти товар/товары соответствующие зпросу"
        "Если просят найти товр/товары, вызывай GoodsVectorSearch"
        "Передавай в инструмент три аргумента: запрос пользователя, название базы данных и количество чанков для поиска."
        "Используй один из двух вариантов:"
        "- Либо запрос и база \"GoodsListWithID\" и 5 чанков"
        "- Либо запрос и база \"GoodsListWithIDWithoutCharacteristics\" и 15 чанков"
        "ВАЖНО: передавай в инструмент аргумент строго в формате JSON с ключами vec_query, database_name и search_limit - название базы как строка, количество чанков как целое число."
        "Пример корректного вызова инструмента: {\"vec_query\": \"электропечь Harvia до 60000 рублей и высотой меньше 1.5 метра\", \"database_name\": \"GoodsListWithID\", \"search_limit\": 10}"
        "НЕЛЬЗЯ передавать другие названия баз или произвольные числа чанков - используй только указанные выше комбинации."
        "\"GoodsListWithIDWithoutCharacteristics\" содержит номенклатуру товара, цену и артикул"
        "\"GoodsListWithID\" содержит еще характеристики товаров помимо (номенклатуры товара, цены и артикула)"
        "При использовании инструмента GoodsVectorSearch, самостоятельно определи нужны ли характеристики товаров,"
        "Если нужны выбери комбинацию с \"GoodsListWithID\", не нужны - \"GoodsListWithIDWithoutCharacteristics\"."
        
         "Формат контекста полученного инструментом GoodsVectorSearch: каждая строка — ОТДЕЛЬНЫЙ товар. В начале строки всегда есть идентификатор в виде "
        "\"ID <число>\". Примеры: \"ID 12 ...\".\n\n"
        "Если нужной информации в контексте нет — прямо так и скажи.\n\n"

        "У ТЕБЯ ЕСТЬ ИНСТРУМЕНТ GetDescriptionsByIds. Вызывай его, когда тебе необходимо получить подробные описания товаров "
        "или тебя напрямую об этом просят."
        "Если просят вызвать дать описание товара, или подробное описание, вызывай GetDescriptionsByIds"
        "по списку ID из контекста (можно брать из контекста предыдущих запросов, если необходимо).\n"
        "ВАЖНО: передавай в инструмент аргумент строго в формате JSON с ключом ids — массив ЦЕЛЫХ чисел. "
        "Пример корректного вызова инструмента: {\"ids\": [12, 45, 103]}.\n"
        "НЕЛЬЗЯ передавать строки вроде \"1,2,3\" или \"ID 12\" — только числа.\n\n"
        
        "У ТЕБЯ ЕСТЬ ИНСТРУМЕНТ FindCheapExpensiveMiddleGoods. Вызывай его, когда тебе необходимо найти "
        "самые дешевые или средней цены или самые дорогие товары определенного вида "
        "Используй в первую очередь этот инструмент для запрсов содержащих \"дорогие/самый дорогой\", \"средней цены\", \"дешевые/самый дорогой\""
        "ВАЖНО: передавай в инструмент аргумент строго в формате JSON с ключами vec_query, flag и search_limit"
        "flag - целое число: если 1 - ищем самые дешевые товары, если 2 - ищем товары средней ценовой категории, если 3 - ищем самые дорогие товары"
        "search_limit - целое число либо 50 либо 150; если в запросе пользователя есть название фирмы, то 50, иначе передаем значение 150"
        "Пример корректного вызова инструмента: {\"vec_query\": \"Какая самая дорогая стеклянная дверь\", \"flag\": \"3\", \"search_limit\": 150}"
        "НЕЛЬЗЯ передавать другие значения flag или произвольные числа чанков - используй только указанные выше комбинации."
        ""
        
        "Алгоритм:\n"
        "1) Внимательно прочитай запрос пользователя (Query).\n"
        "2) Для вопросов содржащих  \"дорогие/самый дорогой\", \"средней цены\", \"дешевые/самый дорогой\" используй FindCheapExpensiveMiddleGoods"
        "2) Если нужно, воспользуйся GoodsVectorSearch для получения контекста(чанков). НИКОГДА не придумывай данные. (есть котекст переписки, поэтому необязательно применять инструмент,"
        "но если для ответа не хватает данных из прошлого котекста, воспользуййся интсрументом)" 
        "3) Если для ответа достаточно информации прямо в чанках — отвечай сразу, без вызова инструмента GetDescriptionsByIds, но если "
        "в запросе требуют описание (подробное) обязательно вызов интсрумента GetDescriptionsByIds\n (в ответ также прописывай id из начала чанков)"
        "4) Если нужен текст описаний товаров — аккуратно извлеки все нужные ID из начала соответствующих строк товаров контекста и вызови "
        "инструмент GetDescriptionsByIds один раз, передав массив чисел (без повторов). Максимум 3 ID за один вызов.\n"
        "5) После получения ответов инструмента — дай итоговый ответ пользователю "
        "6) Если в контексте нет подходящих товаров/ID — скажи, что данных нет, и уточни, что можно уточнить запрос.\n\n"

        # "Стиль ответа: по-русски, кратко, списком, без лишней воды. Не используй гипотезы. "
        "Если показаны цены — указывай валюту (руб.)."
    ),
    tools=[get_desc_tool, goods_vector_search_tool, find_cheap_expensive_middle_goods_tool],
)

LOCAL_TOOLS = {
    "GetDescriptionsByIds": GetDescriptionsByIds,
    "GoodsVectorSearch": GoodsVectorSearch,
    "FindCheapExpensiveMiddleGoods": FindCheapExpensiveMiddleGoods
}
def run_with_tools(assistant, thread, prompt: str) -> str:
    thread.write(prompt)
    run = assistant.run(thread)
    res = run.wait()

    # В некоторых случаях может быть несколько раундов tool_calls,
    # поэтому делаем цикл, пока модель что-то запрашивает
    while getattr(res, "tool_calls", None):
        tool_results = []

        for call in res.tool_calls:
            name = call.function.name
            args = call.function.arguments

            print(f"[tool] {name}({args})")

            # 2) Берём локальный класс-инструмент
            ToolClass = LOCAL_TOOLS.get(name)

            try:
                # 3) Валидируем вход через Pydantic и запускаем ваш .process()
                obj = ToolClass(**args)
                content = obj.process()   # ВАЖНО: без thread; ваш process(self) ничего не принимает
            except Exception as e:
                # Чтобы видеть реальную причину падения, возвращаем ошибку как контент
                content = {"error": repr(e)}

            # 4) Контент должен быть JSON-сериализуемым (dict/str/список)
            tool_results.append({"name": name, "content": str(content)})

        # 5) Отдаём результаты инструментов модели и ждём следующий шаг
        run.submit_tool_results(tool_results = tool_results)
        res = run.wait()

    # Когда tool_calls больше нет — это финальный ответ
    return res.text

thread = sdk.threads.create(ttl_days=1, expiration_policy="static")
#нужно подробное описание Печь электрическая ЭКМ Олимпия 6 кВт Артикул 25398. Вызови инструмент GetDescriptionsByIds, если нет никакого ответа от функции дай логи

while(True):
    prompt = input()
    result = run_with_tools(assistant, thread, prompt)
    print(result)


client.close()