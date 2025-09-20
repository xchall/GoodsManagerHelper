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

#добавление в векторную базу далее
