import logging
import json
import os
import re
import requests
import aiofiles
import aiohttp
import asyncpg
from bs4 import BeautifulSoup
import asyncio
import random
from config import DB_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_URL = "https://coffeemania.ru"
REST_URL = f"{BASE_URL}/restaurants"

MAX_CONCURRENT_REQUESTS = 20
FETCH_DELAY_RANGE = (0.01, 0.02)


def normalize_phone_number(phone_text: str) -> str:
    phone_text = re.sub(r"\D", "", phone_text)
    return phone_text

async def fetch_with_delay(url, session, semaphore):
    async with semaphore:
        await asyncio.sleep(random.uniform(*FETCH_DELAY_RANGE))
        async with session.get(url, timeout=10) as response:
            response.raise_for_status()
            return await response.text()

async def fetch_restaurant_data(url, session, semaphore):
    try:
        page_text = await fetch_with_delay(url, session, semaphore)
        soup = BeautifulSoup(page_text, "html.parser")

        script_tag = soup.find('script', id='__NEXT_DATA__')
        json_data = script_tag.string
        dat = json.loads(json_data)
        restaurant_id = dat['props']['pageProps']['restaurant']['inner-id']
        title = dat['props']['pageProps']['restaurant']['title']
        descriptions = soup.find("div", class_="styles__AboutContent-sc-1q087s8-26 kcNVuQ")
        description_text = descriptions.get_text(strip=True) if descriptions else "Нет описания"

        extra_info = soup.find_all("div", class_="styles__ExtraInfoItemText-sc-1q087s8-23 KvPwL")
        veranda = extra_info[0].get_text(strip=True) if len(extra_info) > 0 else "Без летней веранды"
        changing_table = dat['props']['pageProps']['restaurant']['changing-tables']
        animation = extra_info[2].get_text(strip=True) if len(extra_info) > 2 else "Без детской анимации"

        address = dat['props']['pageProps']['restaurant']['address']

        vine = soup.find("a", class_='underline', attrs={"rel": "noopener noreferrer"})
        vine_text = vine.get_text(strip=True) if vine else ""
        vine_url = vine['href'] if vine else ""

        restaurant_img = soup.find('img', {'itemprop': 'contentUrl'})
        img_url = restaurant_img["src"]

        metro = dat['props']['pageProps']['restaurant']['metro']
        work_time = str(dat['props']['pageProps']['restaurant']['working-hours']).replace("[", "").replace("]", "")
        contacts = dat['props']['pageProps']['restaurant']['phone']
        contacts = normalize_phone_number(contacts)

        restaurant_menu = soup.find("a", string="Смотреть меню")
        menu_url = restaurant_menu['href'] if restaurant_menu else "Нет меню"

        data = {
            "id": restaurant_id,
            # Имя ресторана будет добавлено отдельно при сборе общего списка
            "address": address,
            "restaurant_img": img_url,
            "metro": metro,
            "description": description_text,
            "veranda": veranda,
            "changing_table": changing_table,
            "animation": animation,
            "work_time": work_time,
            "contacts": contacts,
            "vine": vine_text,
            "vine_url": vine_url,
            "restaurant_menu": menu_url,
        }
        return data

    except requests.RequestException as e:
        logging.error(f"Ошибка при запросе {url}: {e}")
        return None

async def fetch_all_restaurants(session, semaphore):
    page_text = await fetch_with_delay(REST_URL, session, semaphore)
    soup = BeautifulSoup(page_text, "html.parser")
    all_rests = soup.find_all("a", class_="image-side")
    restaurants = {}
    for rest in all_rests:
        rest_name = rest.find("img").get("title")
        rest_url = BASE_URL + rest.get("href")
        restaurants[rest_name] = rest_url
    restaurants.pop("Кофемания Chef's", None)
    return restaurants

async def save_restaurants_to_db(db_pool, restaurants: list):
    if not restaurants:
        return {}

    query = """
        INSERT INTO restaurants 
            (restaurant_id, name, address, image, metro, description, veranda, changing_table, animation, work_time, contacts, vine_card)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        ON CONFLICT (restaurant_id) DO UPDATE 
        SET name = EXCLUDED.name,
            address = EXCLUDED.address,
            image = EXCLUDED.image,
            metro = EXCLUDED.metro,
            description = EXCLUDED.description,
            veranda = EXCLUDED.veranda,
            changing_table = EXCLUDED.changing_table,
            animation = EXCLUDED.animation,
            work_time = EXCLUDED.work_time,
            contacts = EXCLUDED.contacts,
            vine_card = EXCLUDED.vine_card;
    """

    params_list = []
    links_dict = {}

    for restaurant in restaurants:
        restaurant_id = restaurant.get("id")
        if not restaurant_id:
            logging.warning(f"Пропускаем ресторан без ID: {restaurant.get('name', 'Без названия')}")
            continue

        name = restaurant.get("name", "Без названия")
        address = restaurant.get("address", "Нет адреса")
        restaurant_image = restaurant.get("restaurant_img", "Нет изображения")
        metro = restaurant.get("metro", "Нет данных о метро")
        description = restaurant.get("description", "Нет описания")
        veranda = restaurant.get("veranda", "Без летней веранды")
        changing_table = restaurant.get("changing_table", "Нет данных")
        animation = restaurant.get("animation", "Нет анимации")
        work_time = restaurant.get("work_time", "Нет данных о времени работы")
        contacts = restaurant.get("contacts", "Нет контактов")
        vine_card = restaurant.get("vine", "Нет данных о винной карте")

        params_list.append((
            restaurant_id,
            name,
            address,
            restaurant_image,
            metro,
            description,
            veranda,
            changing_table,
            animation,
            work_time,
            contacts,
            vine_card
        ))

        restaurant_menu_link = restaurant.get("restaurant_menu", "Нет меню")
        wine_card_link = restaurant.get("vine_url", "Нет винной карты")
        links_dict[restaurant_id] = {
            "restaurant_menu": restaurant_menu_link,
            "wine_card": wine_card_link
        }

    async with db_pool.acquire() as conn:
        await conn.executemany(query, params_list)

    return links_dict

async def main(db_pool):
    restaurant_data_list = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        restaurants_dict = await fetch_all_restaurants(session, semaphore)
        for name, url in restaurants_dict.items():
            data = await fetch_restaurant_data(url, session, semaphore)
            if data:
                data["name"] = name
                restaurant_data_list.append(data)
                logging.info(f"Получены данные ресторана: {name}")

    for restaurant in restaurant_data_list:
        logging.info("-" * 70)
        logging.info(f"ID: {restaurant.get('id')}")
        logging.info(f"Название: {restaurant.get('name')}")
        logging.info(f"Описание: {restaurant.get('description')}")
        logging.info(f"Веранда: {restaurant.get('veranda')}")
        logging.info(f"Пеленальный столик: {restaurant.get('changing_table')}")
        logging.info(f"Анимация: {restaurant.get('animation')}")
        logging.info(f"Адрес: {restaurant.get('address')}")
        logging.info(f"Метро: {restaurant.get('metro')}")
        logging.info(f"Время работы: {restaurant.get('work_time')}")
        logging.info(f"Контакты: {restaurant.get('contacts')}")
        logging.info(f"Винная карта: {restaurant.get('vine')}")
        logging.info(f"Меню: {restaurant.get('restaurant_menu')}")
        logging.info(f"Ссылка на винную карту: {restaurant.get('vine_url')}")

    links = await save_restaurants_to_db(db_pool, restaurant_data_list)
    logging.info("Сохраненные ссылки:")
    logging.info(links)
    return links

async def get_links(db_pool):
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    connector = aiohttp.TCPConnector(ssl=False)
    restaurant_data_list = []
    async with aiohttp.ClientSession(connector=connector) as session:
        restaurants_dict = await fetch_all_restaurants(session, semaphore)
        for name, url in restaurants_dict.items():
            data = await fetch_restaurant_data(url, session, semaphore)
            if data:
                data["name"] = name
                restaurant_data_list.append(data)
    links = await save_restaurants_to_db(db_pool, restaurant_data_list)
    return links

if __name__ == "__main__":
    async def run():
        db_pool = await asyncpg.create_pool(**DB_CONFIG, min_size=1, max_size=10)
        await main(db_pool)
        await db_pool.close()
    asyncio.run(run())