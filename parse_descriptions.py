#parse descriptions from saunamart.ru
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time
import os
import pandas as pd
import requests
from bs4 import BeautifulSoup
from typing import List


def parse_good_and_add_to_exel(url):
    html = requests.get(url).text
    soup = BeautifulSoup(html, "html.parser")
    good_data = {}
    # Номенклатура
    title = soup.select_one('[class="catalog-detail__title"]')
    title_text = title.text

    # код товара
    code = soup.select_one('[class="catalog-detail__code"]')
    code_text = code.text

    # Стоимость за единицу
    price = soup.select_one('[class="catalog-detail__price"]')
    price_text = price.get_text(strip=True)

    # Описание
    desc_block = soup.select_one('[data-tab="description"]')
    description = "\n".join(p.get_text(strip=True) for p in desc_block.select("p") if p.get_text(strip=True))

    # Характеристики
    characteristics = {}
    for row in desc_block.select("table tr"):
        cells = row.find_all("td")
        if len(cells) == 2:
            key = cells[0].get_text(strip=True).rstrip(":")
            value = cells[1].get_text(strip=True)
            characteristics[key] = value
    good_data['title']= title_text
    good_data['code'] = code_text
    good_data['price'] = price_text
    good_data['description'] = description
    good_data['characteristics'] = characteristics
    return good_data
    # print(title_text)
    # print(code_text)
    # print(price_text)
    # print(description)
    # print(characteristics)

def get_category_links(driver, url):

    driver.get(url)
    #time.sleep(4)
    try:
        #time.sleep(0.2)
        category_links = driver.find_elements(By.CLASS_NAME, "sidebar-menu__link")
        category_urls = []

        for link in category_links:
            href = link.get_attribute('href')
            text = driver.execute_script("return arguments[0].textContent;", link)
            if href and (href,text) not in category_urls:
                category_urls.append((href, text))
        return category_urls

    except Exception as e:
        print(f"Ошибка при поиске категорий: {e}")
        return []

def get_subcategory_links(driver, category_url):

    try:
        driver.get(category_url)
        #time.sleep(0.2)

        #//a[@class='sidebar-menu__link ' and @href='/catalog/drovyanye-pechi/']/following-sibling::ul[@class='sidebar-submenu']//a[@class='sidebar-submenu__link '
        #начала родительской ссылки на сайте нет, поэтому нужно обрезать начало category/url
        category_url_cutted = category_url[20:]
        # print(category_url_cutted)
        # Проверяем, есть ли подкатегории
        xpath = f"//a[@class='sidebar-menu__link ' and @href='{category_url_cutted}']/following-sibling::ul[@class='sidebar-submenu']//a[@class='sidebar-submenu__link ']"

        submenu_links = driver.find_elements(By.XPATH, xpath)
        subcategory_urls = []

        if submenu_links:
            #print(f"Найдено подкатегорий: {len(submenu_links)/2}")
            for link in submenu_links:
                href = link.get_attribute('href')
                text = driver.execute_script("return arguments[0].textContent;", link)
                if href and (href,text) not in subcategory_urls:
                    subcategory_urls.append((href, text))
            return subcategory_urls
        else:
            return [(category_url,"")]  #Возвращаем саму категорию как страницу товаров

    except Exception as e:
        print(f"Ошибка при обработке субкатегории {category_url}: {e}")
        return []
def get_subsubcategory_links(driver, category_url):
    try:
        driver.get(category_url)
        #time.sleep(0.2)

        category_url_cutted = category_url[20:]
        #print(category_url_cutted)
        xpath = f"//a[@class='sidebar-submenu__link ' and @href='{category_url_cutted}']/following-sibling::ul[@class='sidebar-submenu']//a[@class='sidebar-submenu__link ']"

        submenu_links = driver.find_elements(By.XPATH, xpath)
        subcategory_urls = []


        if submenu_links:
            # print(f"Найдено субсубкатегорий: {len(submenu_links)/2}")
            for link in submenu_links:
                href = link.get_attribute('href')
                text = driver.execute_script("return arguments[0].textContent;", link)
                if href and (href,text) not in subcategory_urls:

                    subcategory_urls.append((href, text))
            return subcategory_urls
        else:
            return [(category_url,"")]  #Возвращаем саму категорию как страницу товаров

    except Exception as e:
        print(f"Ошибка при обработке субсубкатегории {category_url}: {e}")
        return []

def get_goods_links(driver, subcategory_url):

    try:
        driver.get(subcategory_url)
        #time.sleep(0.2)
        #//a[@class='offer__title']

        xpath = "//a[@class='offer__title']"

        goods_links = driver.find_elements(By.XPATH, xpath)
        goods_urls = []
        # print(f"Найдено товаров: {len(goods_links)}")
        for link in goods_links:
            href = link.get_attribute('href')
            if href and href not in goods_urls:
                goods_urls.append(href)
        return goods_urls

    except Exception as e:
        print(f"Ошибка при обработке товара {category_url}: {e}")
        return []

#!!! у субкатегории feringer категории дровяные печи есть субсубкатегория, у остальных субкатегорий такого нет
# поэтому сделал костыль на первую субкатегорию

# Попадаем изначально в каталог
# sidebar-menu__link
#выбираем все с классом sidebar-menu__link и сохраняем их hrefs
#переходим по каждой из hrefs и находим все sidebar-submenu__link и сохраняем
#Если sidebar-submenu__link, значит уже на старнице товаров и можно получать ссылки конретных товаров
#Переходим по cсылкам sidebar-submenu__link и теперь точно попадаем на страницу товаров
#выбираем все класса offer__title и сохраняем их hrefs
# Проходим по hrefs всех товаров

if __name__ == "__main__":
    url_start = "https://saunamart.ru"
    url = "https://saunamart.ru/catalog/"

    options = Options()
    options.headless = True
    options.add_argument("--disable-extensions")
    options.add_argument("--blink-settings=imagesEnabled=false")  #отключить картинки
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--memory-pressure-off")
    options.add_argument("--max_old_space_size=4096")
    options.add_argument("--disable-javascript")

    driver = webdriver.Chrome(options=options)

    columns = ['Номенклатура','Артикул', 'Цена', 'Описание', 'Характеристики']
    df = pd.DataFrame(columns=columns)

    all_goods_urls = []
    category_urls = get_category_links(driver, url_start)
    for category_url, category_text in category_urls:
        goods_amount_lvl1 = 0
        subcategory_urls = get_subcategory_links(driver, category_url)

        for subcategory_url, subcategory_text in subcategory_urls:
            if subcategory_text == "":
                subcategory_text = category_text
            goods_amount_lvl2 = 0
            if(subcategory_url == "https://saunamart.ru/catalog/pechi-feringer/"
                    or subcategory_url == "https://saunamart.ru/catalog/otopitelnye-kotly/"
                    or subcategory_url == "https://saunamart.ru/catalog/dymokhody-i-komplektuyushchie/"):
                continue
            if(subcategory_url == "https://saunamart.ru/catalog/feringer_1/"):
                subsubcategory_urls = get_subsubcategory_links(driver, subcategory_url)

                for subsubcategory_url, subsubcategory_text in subsubcategory_urls:
                    if subsubcategory_text == "":
                        subsubcategory_text = subcategory_text
                    goods_urls = get_goods_links(driver, subsubcategory_url)
                    for good_url in all_goods_urls:
                        good_data = parse_good_and_add_to_exel(good_url)
                        row_data = [
                            "Путь в каталоге: " + category_text + ", " + subcategory_text + ", " + subsubcategory_text + ". " + good_data['title'],
                            good_data['code'][12:], good_data['price'],
                            good_data['description'], good_data['characteristics']]
                        temp_df = pd.DataFrame([row_data], columns=columns)
                        df = pd.concat([df, temp_df], ignore_index=True)

                    goods_amount_lvl3 = len(goods_urls)
                    print("___ ___ subsubcat", subsubcategory_text, goods_amount_lvl3)
                    all_goods_urls.extend(goods_urls)

                    # for good_url in goods_urls:
                    #
                    # #     print("___ ___ good ____ ", good_url)

                    goods_amount_lvl2 += goods_amount_lvl3

            else:

                goods_urls = get_goods_links(driver, subcategory_url)
                goods_amount_lvl2 = len(goods_urls)
                all_goods_urls.extend(goods_urls)
                for good_url in all_goods_urls:
                    good_data = parse_good_and_add_to_exel(good_url)
                    row_data = [
                        "Путь в каталоге: " + category_text + ", "+subcategory_text+ ". " + good_data['title'],
                        good_data['code'][12:], good_data['price'],
                        good_data['description'], good_data['characteristics']]
                    temp_df = pd.DataFrame([row_data], columns=columns)
                    df = pd.concat([df, temp_df], ignore_index=True)

                # for good_url in goods_urls:
                #
                #     # print("___ good ____ ", good_url)

            goods_amount_lvl1 += goods_amount_lvl2
            print("___ subcat", subcategory_text, goods_amount_lvl2)
        print("cat", category_text, goods_amount_lvl1)

    # получим все нужные данные о каждом товаре и запишем их в parsed_data_about_goods_saunamart.xlsx
    df.to_excel('C:/Users/Asus/Desktop/work/DL/parsed_data_about_goods_saunamart2.xlsx', index=False)
    print("Файл успешно создан!")

    print(len(all_goods_urls))









