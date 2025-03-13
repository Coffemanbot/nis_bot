import asyncio
import asyncpg
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery
from config import DB_CONFIG, PAYMENT_PROVIDER_TOKEN

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


router = Router()

db_pool = None

def set_db_pool(pool):
    global db_pool
    db_pool = pool

async def add_item_to_cart(user_id: int, item_id: int, restaurant_id: int, item_name: str, price: int, is_wine: bool):

    async with db_pool.acquire() as conn:
        existing_item = await conn.fetchrow(
            "SELECT count FROM cart WHERE user_id=$1 AND item_id=$2 AND restaurant_id=$3 AND is_wine=$4",
            user_id, item_id, restaurant_id, is_wine
        )
        if existing_item:
            await conn.execute(
                "UPDATE cart SET count = count + 1 WHERE user_id=$1 AND item_id=$2 AND restaurant_id=$3 AND is_wine=$4",
                user_id, item_id, restaurant_id, is_wine
            )
            logger.info(f"Увеличено количество товара {item_id} для пользователя {user_id}.")
        else:
            await conn.execute(
                "INSERT INTO cart (user_id, item_id, restaurant_id, item_name, price, is_wine, count) VALUES ($1, $2, $3, $4, $5, $6, 1)",
                user_id, item_id, restaurant_id, item_name, price, is_wine
            )
            logger.info(f"Товар {item_id} добавлен в корзину для пользователя {user_id}.")

async def get_cart_items(user_id: int):

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT item_name, price, count FROM cart WHERE user_id=$1", user_id)
        return [{"item_name": r["item_name"], "price": r["price"], "count": r["count"]} for r in rows]

async def clear_cart(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM cart WHERE user_id=$1", user_id)
    logger.info(f"Корзина пользователя {user_id} очищена.")

@router.callback_query(F.data.startswith("add_to_cart:"))
async def add_to_cart_callback(callback: types.CallbackQuery):
    try:
        _, item_id, restaurant_id, is_wine, item_name, price = callback.data.split(":", 5)
        user_id = callback.from_user.id
        await add_item_to_cart(user_id, int(item_id), int(restaurant_id), item_name, int(price), is_wine == "True")
        await callback.answer("Товар добавлен в корзину!")
    except Exception as e:
        logger.exception(f"Ошибка в add_to_cart_callback: {e}")
        await callback.answer("Ошибка при добавлении товара в корзину.", show_alert=True)

@router.message(Command("cart"))
async def view_cart(message: types.Message):
    user_id = message.from_user.id
    items = await get_cart_items(user_id)
    if not items:
        await message.answer("Корзина пуста.")
        return

    total = sum(i['price'] * i['count'] for i in items)
    cart_text = "Ваш заказ:\n\n"
    for item in items:
        item_total = item['price'] * item['count']
        cart_text += f"{item['item_name']} x{item['count']} - {item_total / 100:.2f} руб.\n"
    cart_text += f"\nИтого: {total / 100:.2f} руб."

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Оплатить заказ", callback_data="checkout")],
        [types.InlineKeyboardButton(text="Очистить корзину", callback_data="clear_cart")]
    ])

    await message.answer(cart_text, reply_markup=kb)

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
        payload="cart_payment",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="cart-payment"
    )
    await callback.answer()

@router.pre_checkout_query()
async def process_pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@router.message(lambda message: message.successful_payment)
async def successful_payment_handler(message: types.Message):
    await clear_cart(message.from_user.id)
    await message.answer("Спасибо за оплату! Ваш заказ принят.")

async def main():
    await create_db_pool()
    logger.info("Модуль корзины запущен. Ожидаем команды...")
    await asyncio.sleep(3600)
    await db_pool.close()
    logger.info("DB Pool закрыт.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.exception(f"Ошибка: {e}")