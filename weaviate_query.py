import weaviate
from weaviate.classes.init import Auth
from weaviate.classes.config import Configure, Property, DataType
import dotenv
from dotenv import load_dotenv
import os
import json


load_dotenv() #загружаем переменные среды из .env файла


weaviate_url = os.getenv("WEAVIATE_URL") #REST endpoint
weaviate_api_key = os.getenv("WEAVIATE_API_KEY")

client = weaviate.connect_to_weaviate_cloud(
    cluster_url=weaviate_url,
    auth_credentials=Auth.api_key(weaviate_api_key),
)

print(client.is_ready())  # Should print: `True`

goods_list = client.collections.use("GoodsList")

response = goods_list.query.near_text(
    query="Полок сорт А",
    limit=140
)

for obj in response.objects:
    content = obj.properties['content']
    print(obj.properties['content'])

client.close()