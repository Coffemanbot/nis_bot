import asyncio
import aiohttp
import asyncpg
import logging
import random
import os
import re
import json
import aiofiles
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from config import DB_CONFIG, BASE_URL
from rest import get_links

MAX_CONCURRENT_REQUESTS = 20
FETCH_DELAY_RANGE = (0.01, 0.02)
SCROLL_PAUSE_TIME = 0
MAX_SCROLLS = 20
parsing_restaurants = set()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")



def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_price(raw_price: str) -> str:
    raw_price = clean_text(raw_price)
    raw_price = re.sub(r"\s*₽", " ₽", raw_price)
    return raw_price


def parse_calories(cal_str: str) -> int:
    cal_str = clean_text(cal_str)
    try:
        return int(cal_str)
    except ValueError:
        match = re.search(r"\d+", cal_str)
        return int(match.group(0)) if match else 0

async def scroll_to_bottom(page, pause_time: float = SCROLL_PAUSE_TIME, max_scrolls: int = MAX_SCROLLS):
    last_height = await page.evaluate("document.body.scrollHeight")
    scrolls = 0
    while True:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        await asyncio.sleep(pause_time)
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
        scrolls += 1
        if scrolls >= max_scrolls:
            logging.info(f"Достигли лимита скроллов ({max_scrolls}).")
            break


async def get_categories_and_items(page, url: str) -> dict:
    logging.info(f"Переходим на страницу: {url}")
    await page.goto(url, timeout=60000, wait_until="domcontentloaded")
    await asyncio.sleep(1)
    await scroll_to_bottom(page)

    content = await page.content()
    soup = BeautifulSoup(content, "html.parser")
    categories = {}

    # Проходим по всем блокам категории
    for cat_container in soup.select(".deliveryCategoryBlockWrapper.deliveryCategoryContainer"):
        cat_title = cat_container.get("data-title", "Неизвестная категория").strip()
        # Извлекаем data-id и преобразуем его в целое число
        try:
            cat_id = int(cat_container.get("data-id", 0))
        except ValueError:
            cat_id = 0

        dish_links = []
        for a in cat_container.find_all("a", href=True):
            href = a["href"]
            if "/menu/" in href:
                if not href.startswith("http"):
                    href = BASE_URL + href
                dish_links.append(href)
        dish_links = list(set(dish_links))
        if dish_links:
            # Сохраняем информацию по категории: ссылки и id
            categories[cat_title] = {
                "id": cat_id,
                "urls": dish_links
            }
    return categories


async def fetch(url, session, retries=3, delay_range=FETCH_DELAY_RANGE):

    for attempt in range(retries):
        try:
            delay = random.uniform(*delay_range)
            await asyncio.sleep(delay)
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    logging.error(f"Ошибка {response.status} при запросе {url}")
        except Exception as E:
            logging.exception(f"Exception при запросе {url}: {E}")
        logging.info(f"Повтор запроса {url} (попытка {attempt + 1}/{retries})")
    return None

def get_restaurant_id_for_item(item_url: str, restaurant_links: dict):
    for rest_id, links in restaurant_links.items():
        menu_url = links.get("restaurant_menu", "")
        if menu_url and item_url.startswith(menu_url):
            return rest_id
    return None


async def parse_item(url, session, category, cat_id, semaphore, restaurant_id):
    async with semaphore:
        html = await fetch(url, session)
        if html is None:
            logging.error(f"Не удалось получить данные со страницы {url}")
            return None
        try:
            soup = BeautifulSoup(html, "html.parser")

            item_id = None
            script_tag = soup.find("script", type="application/ld+json")
            if script_tag:
                try:
                    data = json.loads(script_tag.string)
                    if isinstance(data, dict) and data.get("@type") == "Product":
                        item_id = int(data.get("sku"))
                except Exception as E:
                    logging.warning(f"Ошибка парсинга JSON-LD для SKU на {url}: {E}")

            name_tag = soup.find("h1", class_="itemTitle")
            name = clean_text(name_tag.text) if name_tag else "Нет названия"

            description_tag = soup.find("div", class_="itemDesc")
            description = clean_text(description_tag.text) if description_tag else "Нет описания"

            price_tag = soup.find("div", class_="itemPrice")
            if price_tag:
                raw_price = price_tag.get_text(strip=True)
                price = parse_price(raw_price)
            else:
                price = "Нет цены"

            nutrition_values = {}
            nutrition_section = soup.find("div", class_="itemAboutValueContent")
            if nutrition_section:
                for stat in nutrition_section.find_all("div", class_="itemStat"):
                    key_tag = stat.find("span")
                    if key_tag:
                        key = clean_text(key_tag.text)
                        value = clean_text(stat.text.replace(key, ""))
                        nutrition_values[key] = value

            composition = "Нет состава"
            composition_section = soup.find("div", class_="itemAboutCompositionContent")
            if composition_section:
                composition_p = composition_section.find("p")
                if composition_p:
                    composition = clean_text(composition_p.text)

            allergens_section = soup.find("p", style="font-style: italic")
            allergens = clean_text(allergens_section.text) if allergens_section else "Аллергены: отсутствуют"

            img_url = "Нет фото"
            item_image_div = soup.find("div", id="itemImage")
            if item_image_div:
                img_tag = item_image_div.find("img", itemprop="contentUrl")
                if img_tag and img_tag.has_attr("src"):
                    img_url = img_tag["src"]
            if img_url == "Нет фото":
                slider = soup.find("div", id="itemSlider")
                if slider:
                    first_slide = slider.find("div", class_="itemSlide")
                    if first_slide:
                        img_tag = first_slide.find("img", itemprop="contentUrl")
                        if img_tag and img_tag.has_attr("src"):
                            img_url = img_tag["src"]

            if img_url != "Нет фото":
                if img_url.lower().endswith(".svg"):
                    img_url = "Нет фото"
                elif not img_url.startswith("http"):
                    img_url = BASE_URL + img_url

            processed_img = img_url
            time_label = soup.find("div", class_="timeLabel")
            timetable = time_label.get_text(strip=True) if time_label else ""

            item = {
                "SKU": item_id,
                "Категория": category,
                "category_id": cat_id,  # добавляем идентификатор категории
                "Название": name,
                "Цена": price,
                "Описание": description,
                "Пищевая ценность": nutrition_values,
                "Состав": composition,
                "Аллергены": allergens,
                "Фото": processed_img,
                "В наличии": True,
                "TimeTable": timetable,
                "restaurant_id": restaurant_id
            }
            return item
        except Exception as E:
            logging.exception(f"Ошибка при разборе страницы {url}: {E}")
            return None


async def save_items_to_db(db_pool, items: list, table_name: str):
    if not items:
        return

    query = f"""
        INSERT INTO {table_name}
            (id, restaurant_id, category, category_id, name, price, calories, proteins, fats, carbohydrates, weight,
             description, composition, allergens, image, availability, timetable)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
        ON CONFLICT (id, restaurant_id) DO UPDATE
        SET category = EXCLUDED.category,
            category_id = EXCLUDED.category_id,
            name = EXCLUDED.name,
            price = EXCLUDED.price,
            calories = EXCLUDED.calories,
            proteins = EXCLUDED.proteins,
            fats = EXCLUDED.fats,
            carbohydrates = EXCLUDED.carbohydrates,
            weight = EXCLUDED.weight,
            description = EXCLUDED.description,
            composition = EXCLUDED.composition,
            allergens = EXCLUDED.allergens,
            image = EXCLUDED.image,
            availability = EXCLUDED.availability,
            timetable = EXCLUDED.timetable;
    """
    params_list = []
    for item in items:
        sku = item.get("SKU")
        if not sku:
            logging.warning(f"Пропускаем элемент без SKU: {item.get('Название')}")
            continue
        rest_id = item.get("restaurant_id")
        if not rest_id:
            logging.warning(f"Пропускаем элемент без restaurant_id: {item.get('Название')}")
            continue

        category = item.get("Категория", "Нет категории")
        category_id = item.get("category_id", 0)  # новый параметр
        name = item.get("Название", "Нет названия")
        price = item.get("Цена", "Нет цены")
        description = item.get("Описание", "Нет описания")
        composition = item.get("Состав", "Нет состава")
        allergens = item.get("Аллергены", "Аллергены: отсутствуют")
        img_url = item.get("Фото", "Нет фото")
        availability = item.get("В наличии", True)
        nutrition = item.get("Пищевая ценность", {})
        calories = parse_calories(nutrition.get("Ккал", "0"))
        proteins = nutrition.get("Белки", "Нет данных")
        fats = nutrition.get("Жиры", "Нет данных")
        carbs = nutrition.get("Углеводы", "Нет данных")
        weight = nutrition.get("Вес", "Нет данных")
        timetable = item.get("TimeTable", "")
        params_list.append((
            sku,
            rest_id,
            category,
            category_id,
            name,
            price,
            calories,
            proteins,
            fats,
            carbs,
            weight,
            description,
            composition,
            allergens,
            img_url,
            availability,
            timetable
        ))
    async with db_pool.acquire() as conn:
        await conn.executemany(query, params_list)


async def main():
    db_pool = await asyncpg.create_pool(**DB_CONFIG, min_size=1, max_size=10)
    restaurant_links = await get_links(db_pool)
    if not restaurant_links:
        logging.warning("Словарь ссылок ресторанов пустой.")
        return

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    connector = aiohttp.TCPConnector(ssl=False)

    async with async_playwright() as p:
        logging.info("Запуск браузера Playwright...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        async with aiohttp.ClientSession(connector=connector) as session:
            for restaurant_id, links in restaurant_links.items():
                try:
                    parsing_restaurants.add(restaurant_id)

                    menu_url = links.get("restaurant_menu")
                    wine_url = links.get("wine_card") or links.get("vine_url", "")

                    restaurant_menu_items = []
                    restaurant_wine_items = []

                    if menu_url:
                        logging.info(f"Переходим по меню ресторана {restaurant_id}: {menu_url}")
                        page = await context.new_page()
                        categories_dict = await get_categories_and_items(page, menu_url)
                        await page.close()

                        tasks = []
                        for category, details in categories_dict.items():
                            cat_id = details["id"]  # извлекаем category_id из details
                            for url in details["urls"]:
                                # Передаём category, cat_id, semaphore и restaurant_id
                                tasks.append(parse_item(url, session, category, cat_id, semaphore, restaurant_id))
                        results = await asyncio.gather(*tasks)
                        for item in results:
                            if item:
                                restaurant_menu_items.append(item)
                    else:
                        logging.warning(f"У ресторана {restaurant_id} нет ссылки на меню.")

                    if wine_url:
                        logging.info(f"Переходим по винной карте ресторана {restaurant_id}: {wine_url}")
                        page = await context.new_page()
                        wine_categories_dict = await get_categories_and_items(page, wine_url)
                        await page.close()

                        tasks = []
                        for category, details in wine_categories_dict.items():
                            cat_id = details["id"]
                            for url in details["urls"]:
                                tasks.append(parse_item(url, session, category, cat_id, semaphore, restaurant_id))
                        results = await asyncio.gather(*tasks)
                        for item in results:
                            if item:
                                restaurant_wine_items.append(item)
                    else:
                        logging.warning(f"У ресторана {restaurant_id} нет ссылки на винную карту.")

                    if restaurant_menu_items:
                        await save_items_to_db(db_pool, restaurant_menu_items, "menu")
                        logging.info(f"Синхронизация меню завершена для ресторана {restaurant_id}.")
                    else:
                        logging.info(f"Для ресторана {restaurant_id} меню не найдено или пустое.")

                    if restaurant_wine_items:
                        await save_items_to_db(db_pool, restaurant_wine_items, "vine_card")
                        logging.info(f"Синхронизация винной карты завершена для ресторана {restaurant_id}.")
                    else:
                        logging.info(f"Для ресторана {restaurant_id} винная карта не найдена или пустая.")

                except Exception as e:
                    logging.exception(f"Ошибка при парсинге ресторана {restaurant_id}: {e}")
                finally:
                    if restaurant_id in parsing_restaurants:
                        parsing_restaurants.remove(restaurant_id)

        await browser.close()
    await db_pool.close()
    logging.info("Синхронизация с сайтом завершена. Все позиции обновлены в базе данных.")

async def periodic_parser():
    while True:
        try:
            logging.info("Запуск периодического парсера...")
            await main()
            logging.info("Периодический парсер завершил работу, ожидаем час до следующего запуска.")
        except Exception as e:
            logging.exception(f"Ошибка в периодическом парсере: {e}")
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.exception(f"Ошибка: {e}")