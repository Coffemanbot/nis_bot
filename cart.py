import asyncio
import asyncpg
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.types import LabeledPrice, PreCheckoutQuery, ContentType, SuccessfulPayment
from config import DB_CONFIG, PAYMENT_PROVIDER_TOKEN
from db_queries import get_menu_item_by_id, get_wine_item_by_id
import re

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

router = Router()

db_pool = None


def set_db_pool(pool):
    global db_pool
    db_pool = pool


async def add_item_to_cart(user_id: int, restaurant_id: int, item_id: int, is_wine: bool = False):
    if is_wine:
        item = await get_wine_item_by_id(db_pool, item_id)
    else:
        item = await get_menu_item_by_id(db_pool, item_id)

    if not item:
        logger.error(f"Товар с id {item_id} не найден в базе.")
        raise Exception("Товар не найден")

    item_name = item["name"]
    price_str = item.get("price", "0")
    price_digits = re.sub(r"[^\d]", "", price_str)
    price = int(price_digits) * 100 if price_digits else 0

    async with db_pool.acquire() as conn:
        existing_item = await conn.fetchrow(
            "SELECT count FROM cart WHERE user_id=$1 AND item_id=$2 AND restaurant_id=$3 AND is_wine=$4",
            user_id, item_id, restaurant_id, bool(int(is_wine))
        )
        if existing_item:
            await conn.execute(
                "UPDATE cart SET count = count + 1 WHERE user_id=$1 AND item_id=$2 AND restaurant_id=$3 AND is_wine=$4",
                user_id, item_id, restaurant_id, bool(int(is_wine))
            )
            logger.info(f"Увеличено количество товара {item_id} для пользователя {user_id}.")
        else:
            await conn.execute(
                "INSERT INTO cart (user_id, item_id, restaurant_id, item_name, price, is_wine, count) VALUES ($1, $2, $3, $4, $5, $6, 1)",
                user_id, item_id, restaurant_id, item_name, price, bool(int(is_wine))
            )
            logger.info(f"Товар {item_id} добавлен в корзину для пользователя {user_id}.")


@router.callback_query(F.data.startswith("add_to_cart:"))
async def add_to_cart_callback(callback: types.CallbackQuery):
    try:
        _, restaurant_id_str, item_id_str, is_wine_str = callback.data.split(":", 3)
        restaurant_id = int(restaurant_id_str)
        item_id = int(item_id_str)
        is_wine = is_wine_str == "True"
        user_id = callback.from_user.id

        await add_item_to_cart(user_id, restaurant_id, item_id, is_wine)
        await callback.answer("Товар добавлен в корзину!")
    except Exception as e:
        logger.exception(f"Ошибка в add_to_cart_callback: {e}")
        await callback.answer("Ошибка при добавлении товара в корзину.", show_alert=True)

async def clear_cart(user_id: int):
    async with db_pool.acquire() as conn:
        result = await conn.execute("DELETE FROM cart WHERE user_id=$1", user_id)
        logger.info(f"clear_cart: Выполнен запрос для user_id={user_id}, результат: {result}")

@router.callback_query(lambda c: c.data == "view_cart")
async def view_cart_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    items = await get_cart_items(user_id)
    if not items:
        await callback.message.answer("🛒 Ваша корзина пуста.\nДобавьте товары, чтобы оформить заказ😊")
        await callback.answer()
        return

    total = sum(i['price'] * i['count'] for i in items)
    cart_text = "🛒 Ваш заказ:\n\n"
    for item in items:
        item_total = item['price'] * item['count']
        cart_text += (
            f"{item['item_name']}\n"
            f"   📦 Кол-во: {item['count']} шт.  |  💵 Сумма: {item_total / 100:.2f} руб.\n"
        )
    cart_text += f"\n💰 Итого: {total / 100:.2f} руб."

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Оплатить заказ", callback_data="checkout")],
        [types.InlineKeyboardButton(text="Очистить корзину", callback_data="clear_cart")]
    ])
    await callback.message.answer(cart_text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "clear_cart")
async def clear_cart_callback(callback: types.CallbackQuery):
    await clear_cart(callback.from_user.id)
    await callback.message.edit_text("Корзина очищена.")
    await callback.answer()


@router.callback_query(F.data == "checkout")
async def checkout_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    items = await get_cart_items(user_id)
    if not items:
        await callback.answer("Ваша корзина пуста.", show_alert=True)
        return

    total = sum(i['price'] * i['count'] for i in items)
    prices = [LabeledPrice(label="Ваш заказ", amount=total)]

    await callback.bot.send_invoice(
        chat_id=user_id,
        title="Оплата заказа",
        description="Оплата заказа из корзины",
        payload="test-invoice-payload",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="cart-payment"
    )
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)
    logger.info(f"Pre checkout query обработан: {query.id}")


async def get_cart_items(user_id: int):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT item_name, price, count FROM cart WHERE user_id=$1", user_id)
        return [{"item_name": r["item_name"], "price": r["price"], "count": r["count"]} for r in rows]


async def save_order_from_cart(user_id: int):
    # Получаем товары корзины с нужными полями (включая id, is_wine и restaurant_id)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, item_name, price, count, is_wine, restaurant_id FROM cart WHERE user_id=$1",
            user_id
        )
    items = [dict(r) for r in rows]
    if not items:
        return None

    order_id_candidate = min(item['id'] for item in items)

    restaurant_id = items[0]['restaurant_id']

    menu_items = []
    wine_items = []
    total_count = 0
    for item in items:
        total_count += item['count']
        if item['is_wine']:
            wine_items.append(f"{item['item_name']} (x{item['count']})")
        else:
            menu_items.append(f"{item['item_name']} (x{item['count']})")

    menu_text = ", ".join(menu_items) if menu_items else ""
    wine_text = ", ".join(wine_items) if wine_items else ""

    async with db_pool.acquire() as conn:
        await conn.execute("""
                INSERT INTO orders (order_id, user_id, restaurant_id, menu_items, wine_items, count)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, order_id_candidate, user_id, restaurant_id, menu_text, wine_text, total_count)

    await clear_cart(user_id)

    return order_id_candidate


async def get_order_history(user_id: int) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
                SELECT order_id, payment_date, menu_items, wine_items, count
                FROM orders
                WHERE user_id = $1
                ORDER BY payment_date DESC;
            """, user_id)
    return rows