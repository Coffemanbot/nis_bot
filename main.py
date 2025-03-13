import asyncio
import asyncpg
import os
import re
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    Message,
    BotCommand,
    ReplyKeyboardMarkup,
    KeyboardButton,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from config1 import BOT_TOKEN, DB_CONFIG
from parser import periodic_parser
from cart import router as cart_router, set_db_pool, get_cart_items, add_item_to_cart, clear_cart

db_pool = None

async def connect_db():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(**DB_CONFIG)
        set_db_pool(db_pool)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(cart_router)
MAX_CAPTION_LENGTH = 1024

user_selected_restaurant = {}
restaurants_mapping = {}



async def set_main_menu():
    commands = [
        BotCommand(command="/start", description="Начать работу"),
    ]
    await bot.set_my_commands(commands)


async def get_restaurants_list() -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT restaurant_id, name FROM restaurants ORDER BY name;")
    return [{"id": r["restaurant_id"], "name": r["name"]} for r in rows]


async def get_restaurant_info(restaurant_id: int) -> dict:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT restaurant_id, name, address, image, metro, description, veranda, changing_table, animation, work_time, contacts, vine_card
            FROM restaurants
            WHERE restaurant_id = $1
        """, restaurant_id)
    return dict(row) if row else {}


async def get_menu_categories(restaurant_id: int) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT category 
            FROM menu
            WHERE restaurant_id = $1
            ORDER BY category;
        """, restaurant_id)
    return [r["category"] for r in rows]


async def get_menu_items(restaurant_id: int, category: str) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, price, calories, proteins, fats, carbohydrates, weight, description, allergens, availability, image 
            FROM menu
            WHERE restaurant_id = $1 AND category = $2
            ORDER BY name;
        """, restaurant_id, category)
    return [dict(r) for r in rows]


async def get_menu_item_by_id(item_id: int) -> dict:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, price, calories, proteins, fats, carbohydrates, weight, description, allergens, availability, image, category, restaurant_id
            FROM menu
            WHERE id = $1
        """, item_id)
    return dict(row) if row else {}


async def get_wine_categories(restaurant_id: int) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT category
            FROM vine_card
            WHERE restaurant_id = $1
            ORDER BY category;
        """, restaurant_id)
    return [r["category"] for r in rows]


async def get_wine_items(restaurant_id: int, category: str) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, price, calories, proteins, fats, carbohydrates, weight, description, allergens, availability, image
            FROM vine_card
            WHERE restaurant_id = $1 AND category = $2
            ORDER BY name;
        """, restaurant_id, category)
    return [dict(r) for r in rows]


async def get_wine_item_by_id(item_id: int) -> dict:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, price, calories, proteins, fats, carbohydrates, weight, description, allergens, availability, image, category, restaurant_id
            FROM vine_card
            WHERE id = $1
        """, item_id)
    return dict(row) if row else {}


def make_restaurants_reply_keyboard(restaurants: list) -> ReplyKeyboardMarkup:
    kb = [[KeyboardButton(text=r["name"])] for r in restaurants]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)


def make_restaurant_actions_inline(restaurant_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Меню ресторана", callback_data=f"menu:{restaurant_id}")],
        [InlineKeyboardButton(text="🍷 Винная карта", callback_data=f"wine:{restaurant_id}")],
        [InlineKeyboardButton(text="🔙 Назад к выбору ресторана", callback_data="back_to_restaurants")]
    ])
    return kb


def make_categories_inline(restaurant_id: int, categories: list, is_wine=False) -> InlineKeyboardMarkup:
    buttons = []
    for cat in categories:
        if not is_wine:
            buttons.append([InlineKeyboardButton(text=cat, callback_data=f"cat_menu:{restaurant_id}:{cat}")])
        else:
            buttons.append([InlineKeyboardButton(text=cat, callback_data=f"cat_wine:{restaurant_id}:{cat}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_restaurant_actions:{restaurant_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def make_items_inline(items: list, is_wine=False) -> InlineKeyboardMarkup:
    buttons = []
    for it in items:
        if not is_wine:
            buttons.append([InlineKeyboardButton(text=it["name"], callback_data=f"dish_menu:{it['id']}")])
        else:
            buttons.append([InlineKeyboardButton(text=it["name"], callback_data=f"dish_wine:{it['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def make_category_reply_keyboard(categories: list) -> ReplyKeyboardMarkup:
    if not categories:
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Нет категорий")]], resize_keyboard=True)
    keyboard = [[KeyboardButton(text=cat)] for cat in categories]
    keyboard.append([KeyboardButton(text="Назад")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=True)


def smart_trim(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    sentences = re.split(r'(?<=[.!?])\s+', text)
    result = ""
    for sentence in sentences:
        candidate = result + (" " if result else "") + sentence
        if len(candidate) <= max_length:
            result = candidate
        else:
            break
    if result:
        return result.strip()
    else:
        return text[:max_length - 3] + "..."


def format_restaurant_info(info: dict) -> str:
    def valid(value):
        return value and value.strip() and value.strip().lower() not in ["нет", "нет описания"]

    parts = []
    if valid(info.get("name")):
        parts.append(f"*{info['name'].strip()}*")
    if valid(info.get("address")):
        parts.append(f"📍 *Адрес:* {info['address'].strip()}")
    if valid(info.get("metro")):
        parts.append(f"🚇 *Метро:* {info['metro'].strip()}")
    if valid(info.get("work_time")):
        parts.append(f"⏰ *Время работы:* {info['work_time'].strip()}")
    if valid(info.get("contacts")):
        parts.append(f"☎ *Контакты:* {info['contacts'].strip()}")
    if valid(info.get("veranda")):
        parts.append(f"🌞 *Веранда:* {info['veranda'].strip()}")
    if valid(info.get("changing_table")):
        parts.append(f"👶 *Пеленальный столик:* {info['changing_table'].strip()}")
    if valid(info.get("animation")):
        parts.append(f"🎉 *Анимация:* {info['animation'].strip()}")
    if valid(info.get("vine_card")):
        parts.append(f"🍷 *Винная карта:* {info['vine_card'].strip()}")
    if valid(info.get("description")):
        parts.append(f"📖 *Описание:* {info['description'].strip()}")
    return "\n\n".join(parts)


async def send_restaurant_info(message: Message, restaurant_id: int):
    info = await get_restaurant_info(restaurant_id)
    if not info:
        await message.answer("Ошибка: ресторан не найден.")
        return
    rest_text = format_restaurant_info(info)
    rest_text = smart_trim(rest_text, MAX_CAPTION_LENGTH)
    kb = make_restaurant_actions_inline(restaurant_id)
    image_path = info.get("image", "")
    if image_path and os.path.exists(image_path) and os.path.isfile(image_path):
        photo = FSInputFile(image_path)
        await message.answer_photo(
            photo=photo,
            caption=rest_text,
            parse_mode="Markdown",
            reply_markup=kb
        )
    else:
        await message.answer(
            rest_text,
            parse_mode="Markdown",
            reply_markup=kb
        )


async def send_item_info(message: Message, item: dict, is_wine=False):
    icon = "🍽" if not is_wine else "🍷"
    item_text = (
        f"{icon} *{item['name']}*\n"
        f"💰 Цена: {item.get('price', 'N/A')}\n"
        f"🔥 Калории: {item.get('calories', 'N/A')} ккал\n"
        f"🥩 Белки: {item.get('proteins', 'N/A')}\n"
        f"🥑 Жиры: {item.get('fats', 'N/A')}\n"
        f"🍞 Углеводы: {item.get('carbohydrates', 'N/A')}\n"
        f"⚖️ Вес: {item.get('weight', 'N/A')}\n\n"
        f"📖 *Описание:*\n{item.get('description', '')[:500]}\n\n"
        f"⚠️ *Аллергены:* {item.get('allergens', 'N/A')}\n\n"
        f"🛒 Присутствует в наличии: {'да' if item.get('availability') else 'нет'}"
    )
    category = item.get("category", "")
    restaurant_id = item.get("restaurant_id")
    # Callback для возврата в меню с блюдами выбранной категории:
    if not is_wine:
        back_cb = f"back_to_items_menu:{restaurant_id}:{category}"
    else:
        back_cb = f"back_to_items_wine:{restaurant_id}:{category}"

    price_str = item.get('price', '0')
    price_parts = price_str.split()  # разделяет строку по пробелам
    price_int = int(price_parts[0])*100 if price_parts else 0
    short_item_name = item['name'].replace(" ", "_")[:10]

    add_to_cart_cb = f"add_to_cart:{item['id']}:{restaurant_id}:{is_wine}:{short_item_name}:{price_int}"
    add_button = InlineKeyboardButton(text="Добавить в корзину", callback_data=add_to_cart_cb)
    view_cart_button = InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart")
    back_button = InlineKeyboardButton(text="🔙 Назад", callback_data=back_cb)

    new_kb = InlineKeyboardMarkup(inline_keyboard=[
        [add_button, view_cart_button],
        [back_button]
    ])

    image_path = item.get("image", "")
    if image_path and os.path.exists(image_path):
        photo = FSInputFile(image_path)
        await message.answer_photo(
            photo=photo,
            caption=item_text,
            parse_mode="Markdown",
            reply_markup=new_kb
        )
    else:
        await message.answer(
            item_text,
            parse_mode="Markdown",
            reply_markup=new_kb
        )


async def send_menu_categories(message: Message, restaurant_id: int):
    categories = await get_menu_categories(restaurant_id)
    if not categories:
        await message.answer("Меню пока пустое.", reply_markup=ReplyKeyboardRemove())
        return
    inline_kb = make_categories_inline(restaurant_id, categories, is_wine=False)
    await message.answer("Выберите категорию меню:", reply_markup=inline_kb)


async def send_wine_categories(message: Message, restaurant_id: int):
    categories = await get_wine_categories(restaurant_id)
    if not categories:
        await message.answer("Винная карта пока пуста.", reply_markup=ReplyKeyboardRemove())
        return
    inline_kb = make_categories_inline(restaurant_id, categories, is_wine=True)
    await message.answer("Выберите категорию вин:", reply_markup=inline_kb)


@dp.message(lambda msg: msg.text and msg.text.strip().lower() == "назад")
async def handle_back_category(message: Message):
    await message.answer("", reply_markup=ReplyKeyboardRemove())


class RegStates(StatesGroup):
    fio = State()
    gender = State()
    age = State()
    phone = State()


async def user_exists_reg(user_id: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id, name FROM clients WHERE user_id = $1", user_id)
    return row


async def add_user(user_id: int, surname: str, name: str, patronymic: str, gender: str, age: int, phone: str):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO clients(user_id, surname, name, patronymic, gender, age, phone)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, user_id, surname, name, patronymic, gender, age, phone)


@dp.message(Command("start"))
async def start_command(message: Message, state: FSMContext):
    await connect_db()
    await set_main_menu()
    user_id = int(message.from_user.id)
    reg = await user_exists_reg(user_id)
    logger.info(f"Проверка регистрации для user_id={user_id}: {reg}")
    if reg:
        user_name = reg["name"]
        restaurants = await get_restaurants_list()
        if not restaurants:
            await message.answer("Нет ресторанов в базе.")
            return
        global restaurants_mapping
        restaurants_mapping = {r["name"].strip().lower(): r["id"] for r in restaurants}
        kb = make_restaurants_reply_keyboard(restaurants)
        await message.answer(
            f"☕️ Добро пожаловать, {user_name}! Выберите ресторан в сети Coffemaia:",
            reply_markup=kb
        )
    else:
        await state.set_state(RegStates.fio)
        await message.answer(
            "Добро пожаловать в сеть Coffemaia!\nПожалуйста,сначала зарегистрируйтесь. Введите ваше ФИО:")


@dp.message(RegStates.fio)
async def get_fio(message: Message, state: FSMContext):
    fio_parts = message.text.strip().split()
    if len(fio_parts) != 3:
        await message.answer("Ошибка формата. Введите ФИО в формате: Фамилия Имя Отчество.")
        return
    surname, name, patronymic = fio_parts
    await state.update_data(surname=surname, name=name, patronymic=patronymic)
    gender_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await state.set_state(RegStates.gender)
    await message.answer("Выберите ваш пол:", reply_markup=gender_keyboard)


@dp.message(RegStates.gender)
async def get_gender(message: Message, state: FSMContext):
    gender = message.text.strip()
    if gender.lower() not in ["мужской", "женский"]:
        await message.answer("Пожалуйста, выберите один из предложенных вариантов: Мужской или Женский.")
        return
    await state.update_data(gender=gender)
    await state.set_state(RegStates.age)
    await message.answer("Введите ваш возраст:", reply_markup=ReplyKeyboardRemove())


@dp.message(RegStates.age)
async def get_age(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Возраст должен быть числом. Повторите ввод:")
        return
    await state.update_data(age=int(message.text))
    await state.set_state(RegStates.phone)
    contact_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Отправить контакт", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Пожалуйста, отправьте ваш контакт или введите номер телефона (например, +79998887766):",
                         reply_markup=contact_keyboard)


@dp.message(RegStates.phone)
async def get_phone(message: Message, state: FSMContext):
    if message.contact and message.contact.phone_number:
        phone = message.contact.phone_number
    else:
        phone = message.text.strip()
    await state.update_data(phone=phone)
    data = await state.get_data()
    user_id = int(message.from_user.id)
    await add_user(user_id, data["surname"], data["name"], data["patronymic"], data["gender"], data["age"],
                   data["phone"])
    full_name = f"{data['name']} {data['patronymic']} "
    nam = f"{data['name']}"
    await message.answer(f"✅ {full_name}, регистрация успешно завершена!", reply_markup=ReplyKeyboardRemove())
    await state.clear()
    restaurants = await get_restaurants_list()
    if not restaurants:
        await message.answer("Нет ресторанов в базе.")
        return
    global restaurants_mapping
    restaurants_mapping = {r["name"].strip().lower(): r["id"] for r in restaurants}
    kb = make_restaurants_reply_keyboard(restaurants)
    await message.answer(f"Добро пожаловать, {nam}! Выберите ресторан в сети Coffemaia:", reply_markup=kb)


@dp.message()
async def handle_text_restaurant_selection(message: Message):
    text = message.text.strip().lower()
    if text in restaurants_mapping:
        restaurant_id = restaurants_mapping[text]
        user_selected_restaurant[message.from_user.id] = restaurant_id
        await message.answer("Переход к информации о ресторане...", reply_markup=ReplyKeyboardRemove())
        await send_restaurant_info(message, restaurant_id)
    else:
        await message.answer("Неизвестный ресторан. Попробуйте снова или /start.")


@dp.callback_query(lambda c: c.data == "back_to_restaurants")
async def back_to_restaurants_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    restaurants = await get_restaurants_list()
    kb = make_restaurants_reply_keyboard(restaurants)
    await bot.send_message(callback.from_user.id, "Выберите ресторан:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "view_cart")
async def view_cart_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    # Получаем товары корзины (функция get_cart_items уже определена в cart.py)
    items = await get_cart_items(user_id)
    if not items:
        await callback.message.answer("Корзина пуста.")
        await callback.answer()
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

    await callback.message.answer(cart_text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("menu:"))
async def menu_callback(callback: types.CallbackQuery):
    restaurant_id = int(callback.data.split(":")[1])
    user_selected_restaurant[callback.from_user.id] = restaurant_id
    await send_menu_categories(callback.message, restaurant_id)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("wine:"))
async def wine_callback(callback: types.CallbackQuery):
    restaurant_id = int(callback.data.split(":")[1])
    user_selected_restaurant[callback.from_user.id] = restaurant_id
    await send_wine_categories(callback.message, restaurant_id)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("cat_menu:"))
async def cat_menu_callback(callback: types.CallbackQuery):
    _, rest_id_str, category = callback.data.split(":", 2)
    restaurant_id = int(rest_id_str)
    items = await get_menu_items(restaurant_id, category)
    if not items:
        await callback.message.answer("В этой категории пока нет блюд.")
        await callback.answer()
        return
    inline_kb = make_items_inline(items, is_wine=False)
    back_btn = InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_menu_categories:{restaurant_id}")
    inline_kb.inline_keyboard.append([back_btn])
    await callback.message.answer(
        text=f"🍽 Меню категории *{category}*:",
        parse_mode="Markdown",
        reply_markup=inline_kb
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("cat_wine:"))
async def cat_wine_callback(callback: types.CallbackQuery):
    _, rest_id_str, category = callback.data.split(":", 2)
    restaurant_id = int(rest_id_str)
    items = await get_wine_items(restaurant_id, category)
    if not items:
        await callback.message.answer("В этой категории пока нет вин/напитков.")
        await callback.answer()
        return
    inline_kb = make_items_inline(items, is_wine=True)
    back_btn = InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_to_wine_categories:{restaurant_id}")
    inline_kb.inline_keyboard.append([back_btn])
    await callback.message.answer(
        text=f"🍷 Винная карта категории *{category}*:",
        parse_mode="Markdown",
        reply_markup=inline_kb
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("dish_menu:"))
async def dish_menu_callback(callback: types.CallbackQuery):
    _, item_id_str = callback.data.split(":", 1)
    item_id = int(item_id_str)
    dish = await get_menu_item_by_id(item_id)
    if dish:
        await send_item_info(callback.message, dish, is_wine=False)
    else:
        await callback.message.answer("Блюдо не найдено.")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("dish_wine:"))
async def dish_wine_callback(callback: types.CallbackQuery):
    _, item_id_str = callback.data.split(":", 1)
    item_id = int(item_id_str)
    wine = await get_wine_item_by_id(item_id)
    if wine:
        await send_item_info(callback.message, wine, is_wine=True)
    else:
        await callback.message.answer("Напиток не найден.")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("back_to_menu_categories:"))
async def back_to_menu_categories_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("back_to_wine_categories:"))
async def back_to_wine_categories_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("back_to_restaurant_actions:"))
async def back_to_restaurant_actions_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("back_to_items_menu:"))
async def back_to_items_menu_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("back_to_items_wine:"))
async def back_to_items_wine_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()


async def start_bot():
    await connect_db()
    await set_main_menu()
    try:
        await dp.start_polling(bot)
    finally:
        await db_pool.close()


async def main():
    await connect_db()
    await set_main_menu()
    asyncio.create_task(periodic_parser())
    await start_bot()


if __name__ == "__main__":
    asyncio.run(main())