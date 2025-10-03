# parse descriptions from saunamart.ru
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time
import os
import pandas as pd
import requests
from bs4 import BeautifulSoup
from typing import List
from urllib.parse import urljoin, urlparse

# === PARALLEL ===
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# === PARALLEL: общий сессионный клиент с пулом соединений и ретраями ===
SESSION = requests.Session()
retries = Retry(
    total=3, backoff_factor=0.3,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"])
)
adapter = HTTPAdapter(pool_connections=64, pool_maxsize=64, max_retries=retries)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)
DEFAULT_TIMEOUT = 15  # секунд
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; saunamart-scraper/1.0; +https://example.com/bot)"
}

def parse_good_and_add_to_exel(url):
    # === PARALLEL: используем SESSION + таймаут + заголовки ===
    resp = SESSION.get(url, timeout=DEFAULT_TIMEOUT, headers=HEADERS)
    resp.raise_for_status()
    html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    good_data = {}

    title = soup.select_one('[class="catalog-detail__title"]')
    title_text = title.text if title else ""

    code = soup.select_one('[class="catalog-detail__code"]')
    code_text = code.text if code else ""

    price = soup.select_one('[class="catalog-detail__price"]')
    price_text = price.get_text(strip=True) if price else ""

    desc_block = soup.select_one('[data-tab="description"]')
    if desc_block:
        description = "\n".join(
            p.get_text(strip=True) for p in desc_block.select("p") if p.get_text(strip=True)
        )
    else:
        description = ""

    characteristics = {}
    if desc_block:
        for row in desc_block.select("table tr"):
            cells = row.find_all("td")
            if len(cells) == 2:
                key = cells[0].get_text(strip=True).rstrip(":")
                value = cells[1].get_text(strip=True)
                characteristics[key] = value

    good_data['title'] = title_text
    good_data['code'] = code_text
    good_data['price'] = price_text
    good_data['description'] = description
    good_data['characteristics'] = characteristics
    return good_data

# === PARALLEL: маленький воркер, который сразу готовит строку для датафрейма ===
def fetch_row(good_url: str, path_text: str):
    try:
        good_data = parse_good_and_add_to_exel(good_url)
        code_trimmed = good_data['code'][12:] if len(good_data['code']) >= 12 else good_data['code']
        row = [
            f"{path_text}. {good_data['title']}",
            code_trimmed,
            good_data['price'],
            good_data['description'],
            good_data['characteristics'],
        ]
        return row
    except Exception as e:
        # чтобы не падать из-за одной карточки
        return [f"{path_text}. ERROR: {good_url}", "", "", f"{type(e).__name__}: {e}", {}]

def get_category_links(driver, url):
    driver.get(url)
    try:
        category_links = driver.find_elements(By.CLASS_NAME, "sidebar-menu__link")
        category_urls = []
        for link in category_links:
            href = link.get_attribute('href')
            text = driver.execute_script("return arguments[0].textContent;", link)
            if href and (href, text) not in category_urls:
                category_urls.append((href, text))
        return category_urls
    except Exception as e:
        print(f"Ошибка при поиске категорий: {e}")
        return []

def get_subcategory_links(driver, category_url):
    try:
        driver.get(category_url)
        category_url_cutted = category_url[20:]
        xpath = f"//a[@class='sidebar-menu__link ' and @href='{category_url_cutted}']/following-sibling::ul[@class='sidebar-submenu']//a[@class='sidebar-submenu__link ']"
        submenu_links = driver.find_elements(By.XPATH, xpath)
        subcategory_urls = []
        if submenu_links:
            for link in submenu_links:
                href = link.get_attribute('href')
                text = driver.execute_script("return arguments[0].textContent;", link)
                if href and (href, text) not in subcategory_urls:
                    subcategory_urls.append((href, text))
            return subcategory_urls
        else:
            return [(category_url, "")]
    except Exception as e:
        print(f"Ошибка при обработке субкатегории {category_url}: {e}")
        return []

def get_subsubcategory_links(driver, category_url):
    try:
        driver.get(category_url)
        category_url_cutted = category_url[20:]
        xpath = f"//a[@class='sidebar-submenu__link ' and @href='{category_url_cutted}']/following-sibling::ul[@class='sidebar-submenu']//a[@class='sidebar-submenu__link ']"
        submenu_links = driver.find_elements(By.XPATH, xpath)
        subcategory_urls = []
        if submenu_links:
            for link in submenu_links:
                href = link.get_attribute('href')
                text = driver.execute_script("return arguments[0].textContent;", link)
                if href and (href, text) not in subcategory_urls:
                    subcategory_urls.append((href, text))
            return subcategory_urls
        else:
            return [(category_url, "")]
    except Exception as e:
        print(f"Ошибка при обработке субсубкатегории {category_url}: {e}")
        return []

def get_goods_links(subcategory_url):
    try:
        response = SESSION.get(subcategory_url, timeout=DEFAULT_TIMEOUT, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        goods_links = soup.find_all('a', class_='offer__title')
        goods_urls = []
        for link in goods_links:
            href = link.get('href')
            if href:
                href = urljoin(subcategory_url, href)
                if href not in goods_urls:
                    goods_urls.append(href)
        return goods_urls
    except requests.RequestException as e:
        print(f"Ошибка при загрузке страницы {subcategory_url}: {e}")
        return []
    except Exception as e:
        print(f"Ошибка при поиске товаров: {e}")
        return []

if __name__ == "__main__":
    url_start = "https://saunamart.ru"
    url = "https://saunamart.ru/catalog/"

    options = Options()
    driver = webdriver.Chrome(options=options)

    columns = ['Номенклатура','Артикул', 'Цена', 'Описание', 'Характеристики']
    df = pd.DataFrame(columns=columns)

    all_goods_urls = []
    category_urls = get_category_links(driver, url_start)

    # === PARALLEL: настройка пула ===
    MAX_WORKERS = 32  # подбери по CPU/сети
    # --------------------------------

    for category_url, category_text in category_urls:
        goods_amount_lvl1 = 0
        subcategory_urls = get_subcategory_links(driver, category_url)

        for subcategory_url, subcategory_text in subcategory_urls:
            if subcategory_text == "":
                subcategory_text = category_text
            goods_amount_lvl2 = 0

            if (subcategory_url == "https://saunamart.ru/catalog/pechi-feringer/"
                or subcategory_url == "https://saunamart.ru/catalog/otopitelnye-kotly/"
                or subcategory_url == "https://saunamart.ru/catalog/dymokhody-i-komplektuyushchie/"):
                continue

            if (subcategory_url == "https://saunamart.ru/catalog/feringer_1/"):
                subsubcategory_urls = get_subsubcategory_links(driver, subcategory_url)
                for subsubcategory_url, subsubcategory_text in subsubcategory_urls:
                    if subsubcategory_text == "":
                        subsubcategory_text = subcategory_text

                    goods_urls = get_goods_links(subsubcategory_url)
                    goods_amount_lvl3 = len(goods_urls)
                    print("___ ___ subsubcat", subsubcategory_text, goods_amount_lvl3)

                    # === PARALLEL: обрабатываем карточки этой (под)подкатегории ===
                    path_text = f"Путь в каталоге: {category_text}, {subcategory_text}, {subsubcategory_text}"
                    rows = []
                    if goods_urls:
                        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                            futures = [ex.submit(fetch_row, u, path_text) for u in goods_urls]
                            for f in as_completed(futures):
                                rows.append(f.result())
                    if rows:
                        df = pd.concat([df, pd.DataFrame(rows, columns=columns)], ignore_index=True)

                    all_goods_urls.extend(goods_urls)
                    goods_amount_lvl2 += goods_amount_lvl3
            else:
                goods_urls = get_goods_links(subcategory_url)
                goods_amount_lvl2 = len(goods_urls)

                # === PARALLEL: обрабатываем карточки этой подкатегории ===
                path_text = f"Путь в каталоге: {category_text}, {subcategory_text}"
                rows = []
                if goods_urls:
                    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                        futures = [ex.submit(fetch_row, u, path_text) for u in goods_urls]
                        for f in as_completed(futures):
                            rows.append(f.result())
                if rows:
                    df = pd.concat([df, pd.DataFrame(rows, columns=columns)], ignore_index=True)

                all_goods_urls.extend(goods_urls)

            goods_amount_lvl1 += goods_amount_lvl2
            print("___ subcat", subcategory_text, goods_amount_lvl2)
        print("cat", category_text, goods_amount_lvl1)

    # сохраняем результат
    df.to_excel('C:/Users/Asus/Desktop/work/DL/parsed_data_about_goods_saunamart2.xlsx', index=False)
    print("Файл успешно создан!")
    print(len(all_goods_urls))
