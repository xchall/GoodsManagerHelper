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
    search_limit += (search_limit//100*5) #для перекрытия нахождения небольшой погрешности (в результат векторного поиска втискивается лишнее)
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
        "- Либо запрос и база \"GoodsListWithID\" и 10 чанков"
        "- Либо запрос и база \"GoodsListWithIDWithoutCharacteristics\" и 15 чанков"
        "ВАЖНО: передавай в инструмент аргумент строго в формате JSON с ключами vec_query, database_name и search_limit - название базы как строка, количество чанков как целое число."
        "Пример корректного вызова инструмента: {\"vec_query\": \"электропечь Harvia до 60000 рублей и высотой меньше 1.5 метра\", \"database_name\": \"GoodsListWithID\", \"search_limit\": 10}"
        "НЕЛЬЗЯ передавать другие названия баз или произвольные числа чанков - используй только указанные выше комбинации."
        "\"GoodsListWithIDWithoutCharacteristics\" содержит номенклатуру товара, цену и артикул"
        "\"GoodsListWithID\" содержит еще характеристики товаров помимо (номенклатуры товара, цены и артикула)"
        "При использовании инструмента GoodsVectorSearch, самостоятельно определи нужны ли характеристики товаров,"
        "Если нужны выбери комбинацию с \"GoodsListWithID\", не нужны - \"GoodsListWithIDWithoutCharacteristics\"."
        "В свой ответ передавай ID выбранных товаров, это сервисная информация, НУЖНАЯ ОЧЕНЬ"
        
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
        "самые дешевые или средней цены или самые дорогие товары определенного вида"
        "Используй в первую очередь этот инструмент для запрсов содержащих \"дорогие/самый дорогой\", \"средней цены\", \"дешевые/самый дорогой\", даэе если есть предыдущий контекст переписки"
        "ВАЖНО: передавай в инструмент аргумент строго в формате JSON с ключами vec_query, flag и search_limit"
        "flag - целое число: если 1 - ищем самые дешевые товары, если 2 - ищем товары средней ценовой категории, если 3 - ищем самые дорогие товары"
        "search_limit - целое число которое нужно определить по структуре каталога магазина, в которой указаны число товаров в категориях,"
        "то есть сначала определяешь в какой категории(подкатегории) ищем и берешь соответсвующее чмсло. Если это число равно 0, "
        "не вызывай инструмент FindCheapExpensiveMiddleGoods,"
        "сразу говори, что таких товаров нет в наличии."
        "Пример корректного вызова инструмента: {\"vec_query\": \"Какая самая дорогая стеклянная дверь\", \"flag\": \"3\", \"search_limit\": 126}"
        "НЕЛЬЗЯ передавать другие значения flag или произвольные числа чанков - используй только указанные выше комбинации."
        
        
        
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
        
        "Структура каталога магазина с указанием количество товаров в каталоге, подкаталоге и возможно в подподкаатлоге"
        "где cat - категория, subcat - подкатегория, subsubcat - подподкатегория"
        "и число означающее сколько товаров внутри категории(или подкатегории или подподкатегории):"
        "cat Дровяные печи 288"
        "___ subcat Feringer 54"
        "___ ___ subsubcat Печи 24"
        "___ ___ subsubcat Отопительные котлы 6"
        "___ ___ subsubcat Дымоходы и комплектующие 24"
        "___ subcat Harvia 24"
        "___ subcat Атмосфера 24"
        "___ subcat Костёр 24"
        "___ subcat Grill`D 24"
        "___ subcat Гефест 24"
        "___ subcat Везувий 24"
        "___ subcat ASTON 21"
        "___ subcat Пегас 24"
        "___ subcat Термофор 0"
        "___ subcat Kastor 0"
        "___ subcat EOS 0s"
        "cat Камни для печи 24"
        "___ subcat Камни для печи 24"
        "cat Дымоходы и баки 60"
        "___ subcat Дымоходы Теплов и Сухов 24"
        "___ subcat УМК  24"
        "___ subcat Баки и теплообменники 3"
        "___ subcat Феникс 1"
        "___ subcat Дымоходы Вермилоджик 0"
        "___ subcat Гефест 8"
        "___ subcat Феррум 0"
        "cat Электрокаменки 234"
        "___ subcat KARINA  24"
        "___ subcat Tylo 0"
        "___ subcat Helo 4"
        "___ subcat Sangens  10"
        "___ subcat Henki 4"
        "___ subcat Костёр 0"
        "___ subcat Ресурс Электрокотел 24"
        "___ subcat Sawo 24"
        "___ subcat BORN 24"
        "___ subcat Harvia 24"
        "___ subcat Политех 0"
        "___ subcat EOS 0"
        "___ subcat Ограждения, фланцы 24"
        "___ subcat Комплектующие 24"
        "___ subcat Тэны 24"
        "___ subcat Прочее 24"
        "cat Пульты управления 49"
        "___ subcat Sawo 18"
        "___ subcat Harvia 10"
        "___ subcat Политех 0"
        "___ subcat KARINA 4"
        "___ subcat Костёр 3"
        "___ subcat Sangens 4"
        "___ subcat Ресурс Электрокотел 7"
        "___ subcat BORN 3"
        "cat Парогенераторы 39"
        "___ subcat Sawo 20"
        "___ subcat Harvia 4"
        "___ subcat Grandis 15"
        "cat Пиломатериалы 191"
        "___ subcat Вагонка 24"
        "___ subcat Полок 24"
        "___ subcat Липа 24"
        "___ subcat Ольха 24"
        "___ subcat Осина 0"
        "___ subcat Абаш 16"
        "___ subcat Кедр 6"
        "___ subcat Термодревесина 24"
        "___ subcat Плинтус и уголки 24"
        "___ subcat Пропитки для дерева 1"
        "___ subcat Прочее 24"
        "cat Гималайская соль 56"
        "___ subcat Соляная плитка 24"
        "___ subcat Соляные лампы 24"
        "___ subcat Клеевая смесь 2"
        "___ subcat Пищевая соль 6"
        "cat Двери 126"
        "___ subcat Sawo 13"
        "___ subcat Grandis 15"
        "___ subcat Ecodoors 24"
        "___ subcat Harvia 24"
        "___ subcat Россия 17"
        "___ subcat Doorwood 24"
        "___ subcat Арта 9"
        "cat Аксессуары и комплектующие 693"
        "___ subcat Термометры и гигрометры 24"
        "___ subcat Термогигрометры 24"
        "___ subcat Термометры 14"
        "___ subcat Гигрометры 24"
        "___ subcat Часы 24"
        "___ subcat Песочные часы 24"
        "___ subcat Часы вне сауны 8"
        "___ subcat Запарники и шайки 24"
        "___ subcat Sawo 24"
        "___ subcat Китай 24"
        "___ subcat Россия 24"
        "___ subcat Harvia 1"
        "___ subcat Tammer-Tukku 1"
        "___ subcat Woodson 5"
        "___ subcat Черпаки и ковши 24"
        "___ subcat Sawo 9"
        "___ subcat Китай 17"
        "___ subcat Россия 24"
        "___ subcat Harvia 0"
        "___ subcat Tylo 1"
        "___ subcat Tammer-Tukku 1"
        "___ subcat Woodson 4"
        "___ subcat Щетки для мытья 4"
        "___ subcat Подголовники 17"
        "___ subcat Sawo 3"
        "___ subcat Китай 6"
        "___ subcat Россия 8"
        "___ subcat Tammer-Tukku 0"
        "___ subcat Ароматизаторы 24"
        "___ subcat Sawo 4"
        "___ subcat Harvia 2"
        "___ subcat Другие 24"
        "___ subcat Веники для бани 17"
        "___ subcat Обливные устройства 19"
        "___ subcat Комплектующие 24"
        "___ subcat Sawo 24"
        "___ subcat Grandis 4"
        "___ subcat Harvia 24"
        "___ subcat Прочее 24"
        "___ subcat Sawo 18"
        "___ subcat Harvia 4"
        "___ subcat Другие 24"
        "___ subcat Шапки 24"
        "___ subcat Россия 24"
        "___ subcat Текстиль 23"
        "___ subcat Текстиль 23"
        "cat Освещение 39"
        "___ subcat Лампы и светодиоды 13"
        "___ subcat Cariitti 2"
        "___ subcat Абажуры 24"
        "cat Все для хамама 141"
        "___ subcat Парогенераторы 19"
        "___ subcat Sawo 16"
        "___ subcat Harvia 3"
        "___ subcat Grandis 0"
        "___ subcat Двери 24"
        "___ subcat Sawo 2"
        "___ subcat Grandis 7"
        "___ subcat Harvia 24"
        "___ subcat Освещение 11"
        "___ subcat Cariitti 11"
        "___ subcat Tylo 0"
        "___ subcat Курны 24"
        "cat Аттракционы для бани 0"
        "cat Инфракрасные сауны 16"
        "___ subcat Оборудование для сухих бань 16"
        "cat Готовые сауны 2"
        "cat Купели 35"
        "___ subcat Купель из массива дерева 24"
        "___ subcat Купель из пластика 11"
        "cat Облицовка 24"
        "cat Окна 7"
        "cat Чаны DUKO 2"
        "cat Мебель для бани 12"
        "___ subcat Sawo 6"
        "___ subcat Прочее 6"
    ),
    tools=[get_desc_tool, goods_vector_search_tool, find_cheap_expensive_middle_goods_tool],
)

#классы а не просто методы, для валидации аргументов с использование pydantic
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
            tool_results.append({"name": name, "content": str(content)})

        #Отдаём результаты инструментов модели и ждём следующий шаг
        run.submit_tool_results(tool_results = tool_results)
        res = run.wait()

    #Когда tool_calls больше нет — это финальный ответ
    return res.text

thread = sdk.threads.create(ttl_days=1, expiration_policy="static")
#нужно подробное описание Печь электрическая ЭКМ Олимпия 6 кВт Артикул 25398. Вызови инструмент GetDescriptionsByIds, если нет никакого ответа от функции дай логи

while(True):
    prompt = input()
    if prompt == "":
        continue
    if prompt == "stop":
        break
    result = run_with_tools(assistant, thread, prompt)
    print(result)


client.close()