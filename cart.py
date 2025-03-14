import asyncio
import asyncpg
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import LabeledPrice, PreCheckoutQuery, ContentType, SuccessfulPayment, InlineKeyboardButton, InlineKeyboardMarkup
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
    # Проверяем, если в корзине уже есть товары, то их restaurant_id должен совпадать с новым
    async with db_pool.acquire() as conn:
        existing_restaurant = await conn.fetchrow(
            "SELECT restaurant_id FROM cart WHERE user_id=$1 LIMIT 1", user_id
        )
        if existing_restaurant and existing_restaurant["restaurant_id"] != restaurant_id:
            raise Exception("Нельзя добавлять блюда из разных ресторанов🥲")

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
        await callback.message.answer(str(e))
        await callback.answer()

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
        [types.InlineKeyboardButton(text="Очистить корзину", callback_data="clear_cart")],
        [types.InlineKeyboardButton(text="Удалить позицию", callback_data="remove_from_cart_prompt")]
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

class DeleteStates(StatesGroup):
    awaiting_quantity = State()

async def remove_item_from_cart(user_id: int, restaurant_id: int, item_id: int, remove_count: int, is_wine: bool = False):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT count FROM cart WHERE user_id=$1 AND item_id=$2 AND restaurant_id=$3 AND is_wine=$4",
            user_id, item_id, restaurant_id, bool(int(is_wine))
        )
        if not row:
            logger.error(f"Товар с id {item_id} не найден в корзине для пользователя {user_id}.")
            raise Exception("Товар не найден в корзине")
        current_count = row["count"]
        if remove_count >= current_count:
            await conn.execute(
                "DELETE FROM cart WHERE user_id=$1 AND item_id=$2 AND restaurant_id=$3 AND is_wine=$4",
                user_id, item_id, restaurant_id, bool(int(is_wine))
            )
            logger.info(f"Позиция {item_id} полностью удалена для пользователя {user_id}.")
        else:
            await conn.execute(
                "UPDATE cart SET count = count - $1 WHERE user_id=$2 AND item_id=$3 AND restaurant_id=$4 AND is_wine=$5",
                remove_count, user_id, item_id, restaurant_id, bool(int(is_wine))
            )
            logger.info(f"Количество товара {item_id} уменьшено на {remove_count} для пользователя {user_id}.")

@router.callback_query(F.data == "remove_from_cart_prompt")
async def remove_from_cart_prompt(callback: types.CallbackQuery):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, item_id, item_name, count, restaurant_id, is_wine FROM cart WHERE user_id=$1",
            callback.from_user.id
        )
    items = [dict(r) for r in rows]
    if not items:
        await callback.message.answer("Ваша корзина пуста.")
        await callback.answer()
        return

    buttons = []
    for item in items:
        cb_data = f"choose_delete_item:{item['item_id']}:{item['restaurant_id']}:{item['is_wine']}"
        button_text = f"{item['item_name']}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=cb_data)])
    buttons.append([InlineKeyboardButton(text="Отмена", callback_data="view_cart")])
    inline_kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("🗑️Выберите позицию для удаления:", reply_markup=inline_kb)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("choose_delete_item:"))
async def choose_delete_item_callback(callback: types.CallbackQuery, state: FSMContext):
    try:
        _, item_id_str, restaurant_id_str, is_wine_str = callback.data.split(":", 3)
        item_id = int(item_id_str)
        restaurant_id = int(restaurant_id_str)
        is_wine = is_wine_str == "True"
        await state.update_data(item_id=item_id, restaurant_id=restaurant_id, is_wine=is_wine)
        await callback.message.answer("🔢Введите количество для удаления:")
        await state.set_state(DeleteStates.awaiting_quantity)
        await callback.answer()
    except Exception as e:
        logger.exception(f"Ошибка при выборе товара для удаления: {e}")
        await callback.answer("Ошибка при выборе товара.", show_alert=True)

@router.message(DeleteStates.awaiting_quantity)
async def process_deletion_quantity(message: types.Message, state: FSMContext):
    try:
        remove_count = int(message.text.strip())
        if remove_count <= 0:
            await message.answer("Количество должно быть положительным числом. Попробуйте снова.")
            return

        data = await state.get_data()
        item_id = data.get("item_id")
        restaurant_id = data.get("restaurant_id")
        is_wine = data.get("is_wine")
        await remove_item_from_cart(message.from_user.id, restaurant_id, item_id, remove_count, is_wine)
        await message.answer("✅Позиции обновлены. Проверьте вашу корзину.")
        await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число😊")
    except Exception as e:
        logger.exception(f"Ошибка при удалении позиции: {e}")
        await message.answer("Ошибка при удалении позиции. Попробуйте ещё раз.")
