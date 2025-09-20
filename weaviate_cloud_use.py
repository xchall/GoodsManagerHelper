import weaviate
from weaviate.classes.init import Auth
from weaviate.classes.config import Configure, Property, DataType
import dotenv
from dotenv import load_dotenv
import os
import pandas as pd

df = pd.read_excel(
    'C:/Users/Asus/Desktop/work/DL/Goods.xlsx',
    sheet_name='Sheet1',
    usecols=[0, 1, 2, 3, 4, 5],
    header=2 #заголовок заканчивается на 3 строке, нумерация с 0
)

rows_for_vector_db = []
for index, row in df.iterrows():
    col1 = row.iloc[2]  # столбец номенклатуры
    col2 = row.iloc[4]  # столбец единицы хранения
    col3 = row.iloc[5] # столбец стоимости за единицу в рублях
    new_row = col1 + ". Единица (измерения) хранения остатков: " + col2 + ". Цена за единицу в рублях: " + str(col3)
    print(new_row)
    rows_for_vector_db.append(new_row)



load_dotenv() #загружаем переменные среды из .env файла


weaviate_url = os.getenv("WEAVIATE_URL") #REST endpoint
weaviate_api_key = os.getenv("WEAVIATE_API_KEY")

client = weaviate.connect_to_weaviate_cloud(
    cluster_url=weaviate_url,
    auth_credentials=Auth.api_key(weaviate_api_key),
)

print(client.is_ready())  # Should print: `True`

# try:
#     # Удаление коллекции
#     client.collections.delete("GoodsList")  # ← Ваше имя коллекции
#     print("✅ Коллекция успешно удалена!")
#
# finally:
#     client.close()

goods_list = client.collections.create(
    name="GoodsList",
    properties=[
        Property(name="content", data_type=DataType.TEXT) # только строка
    ],
    vector_config=Configure.Vectors.text2vec_weaviate(), # Configure the Weaviate Embeddings integration
    generative_config=Configure.Generative.cohere() # Configure the Cohere generative AI integration
)



goods_list = client.collections.use("GoodsList")
with goods_list.batch.fixed_size(batch_size=30) as batch:
    for i, text in enumerate(rows_for_vector_db):
        batch.add_object(
            properties={
                "content": text  # ТОЛЬКО content, больше ничего
            }
        )
        if batch.number_errors > 5:
            print("Batch import stopped due to excessive errors.")
            break

failed_objects = goods_list.batch.failed_objects
if failed_objects:
    print(f"Number of failed imports: {len(failed_objects)}")
    print(f"First failed object: {failed_objects[0]}")


client.close()  # Free up resources