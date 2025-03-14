import asyncio
import asyncpg
import os
import re
import logging

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    Message,
    BotCommand,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove
)

from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from parser import periodic_parser
from cart import router as cart_router, set_db_pool, get_cart_items, add_item_to_cart, clear_cart, save_order_from_cart, get_order_history
from db_queries import get_menu_item_by_id, get_wine_item_by_id
from config1 import BOT_TOKEN, DB_CONFIG

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

async def get_restaurants_list() -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT restaurant_id, name FROM restaurants ORDER BY name;")
    return [{"id": r["restaurant_id"], "name": r["name"]} for r in rows]

async def get_restaurant_info(restaurant_id: int) -> dict:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT restaurant_id, name, address, image, metro, description, veranda, 
                   changing_table, animation, work_time, contacts, vine_card
            FROM restaurants
            WHERE restaurant_id = $1
        """, restaurant_id)
    return dict(row) if row else {}

async def get_menu_categories(restaurant_id: int) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT category, category_id
            FROM menu
            WHERE restaurant_id = $1
            ORDER BY category;
        """, restaurant_id)
    return [{"category": r["category"], "category_id": r["category_id"]} for r in rows]

async def get_menu_items(restaurant_id: int, category_id: int) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, price, calories, proteins, fats, carbohydrates, weight, 
                   description, allergens, availability, image, category, 
                   restaurant_id, category_id
            FROM menu
            WHERE restaurant_id = $1 AND category_id = $2
            ORDER BY name;
        """, restaurant_id, category_id)
    return [dict(r) for r in rows]

async def get_wine_categories(restaurant_id: int) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT category, category_id
            FROM vine_card
            WHERE restaurant_id = $1
            ORDER BY category;
        """, restaurant_id)
    return [{"category": r["category"], "category_id": r["category_id"]} for r in rows]

async def get_wine_items(restaurant_id: int, category_id: int) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, price, calories, proteins, fats, carbohydrates, weight, 
                   description, allergens, availability, image, category, 
                   restaurant_id, category_id
            FROM vine_card
            WHERE restaurant_id = $1 AND category_id = $2
            ORDER BY name;
        """, restaurant_id, category_id)
    return [dict(r) for r in rows]


def make_reply_menu_button() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Меню")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return kb

def make_main_menu_inline() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выбрать ресторан", callback_data="choose_restaurant")],
        [InlineKeyboardButton(text="История заказов", callback_data="order_history")],
    ])
    return kb

def make_restaurants_inline(restaurants: list) -> InlineKeyboardMarkup:
    rows = []
    for r in restaurants:
        rows.append([InlineKeyboardButton(text=r["name"], callback_data=f"rest_info:{r['id']}")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="back_to_inline_main_menu")])  # <-- вернёт в «главное меню»
    return InlineKeyboardMarkup(inline_keyboard=rows)

def make_restaurant_actions_inline(restaurant_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Меню ресторана", callback_data=f"menu:{restaurant_id}")],
        [InlineKeyboardButton(text="🍷 Винная карта", callback_data=f"wine:{restaurant_id}")],
        [InlineKeyboardButton(text="Назад", callback_data="back_to_restaurants_list")]
    ])

def make_categories_inline(restaurant_id: int, categories: list, is_wine=False) -> InlineKeyboardMarkup:
    buttons = []
    for cat in categories:
        if not is_wine:
            buttons.append([
                InlineKeyboardButton(
                    text=cat["category"],
                    callback_data=f"cat_menu:{restaurant_id}:{cat['category_id']}"
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    text=cat["category"],
                    callback_data=f"cat_wine:{restaurant_id}:{cat['category_id']}"
                )
            ])
    callback_back = f"rest_info:{restaurant_id}"
    buttons.append([InlineKeyboardButton(text="Назад", callback_data=callback_back)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def make_items_inline(items: list, is_wine=False) -> InlineKeyboardMarkup:
    buttons = []
    for it in items:
        if not is_wine:
            buttons.append([InlineKeyboardButton(text=it["name"], callback_data=f"dish_menu:{it['id']}")])
        else:
            buttons.append([InlineKeyboardButton(text=it["name"], callback_data=f"dish_wine:{it['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

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
    parts = []
    if info.get("name"):
        parts.append(f"*{info['name'].strip()}*")
    if info.get("address"):
        parts.append(f"📍 *Адрес:* {info['address'].strip()}")
    if info.get("metro"):
        parts.append(f"🚇 *Метро:* {info['metro'].strip()}")
    if info.get("work_time"):
        parts.append(f"⏰ *Время работы:* {info['work_time'].strip()}")
    if info.get("contacts"):
        parts.append(f"☎ *Контакты:* {str(info['contacts']).strip()}")
    if info.get("veranda"):
        parts.append(f"🌞 *Веранда:* {info['veranda'].strip()}")
    if info.get("changing_table"):
        parts.append(f"👶 *Пеленальный столик:* {info['changing_table'].strip()}")
    if info.get("animation"):
        parts.append(f"🎉 *Анимация:* {info['animation'].strip()}")
    if info.get("vine_card"):
        parts.append(f"🍷 *Винная карта:* {info['vine_card'].strip()}")
    if info.get("description"):
        trimmed_desc = smart_trim(info["description"].strip(), MAX_CAPTION_LENGTH)
        parts.append(f"📖 *Описание:* {trimmed_desc}")
    return "\n\n".join(parts)


async def send_restaurant_info(message: Message, restaurant_id: int):
    info = await get_restaurant_info(restaurant_id)
    if not info:
        await message.answer("Ошибка: ресторан не найден.")
        return
    rest_text = format_restaurant_info(info)
    kb = make_restaurant_actions_inline(restaurant_id)
    image_path = info.get("image", "")

    if image_path and image_path.startswith("http"):
        await message.answer_photo(
            photo=image_path,
            caption=rest_text,
            parse_mode="Markdown",
            reply_markup=kb
        )
    else:
        await message.answer(rest_text, parse_mode="Markdown", reply_markup=kb)

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
    restaurant_id = item.get("restaurant_id")
    category_id = item.get("category_id", 0)

    if not is_wine:
        back_cb = f"back_to_category_menu:{restaurant_id}:{category_id}"
    else:
        back_cb = f"back_to_category_wine:{restaurant_id}:{category_id}"

    add_to_cart_cb = f"add_to_cart:{restaurant_id}:{item['id']}:{is_wine}"
    add_button = InlineKeyboardButton(text="Добавить в корзину", callback_data=add_to_cart_cb)
    view_cart_button = InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart")
    back_button = InlineKeyboardButton(text="Назад", callback_data=back_cb)

    new_kb = InlineKeyboardMarkup(inline_keyboard=[
        [add_button, view_cart_button],
        [back_button]
    ])

    image_path = item.get("image", "")
    if image_path and image_path.startswith("http"):
        await message.answer_photo(
            photo=image_path,
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
        await message.answer("Меню пока пустое.")
        return
    inline_kb = make_categories_inline(restaurant_id, categories, is_wine=False)
    await message.answer("Выберите категорию меню:", reply_markup=inline_kb)

async def send_wine_categories(message: Message, restaurant_id: int):
    categories = await get_wine_categories(restaurant_id)
    if not categories:
        await message.answer("Винная карта пока пуста.")
        return
    inline_kb = make_categories_inline(restaurant_id, categories, is_wine=True)
    await message.answer("Выберите категорию вин:", reply_markup=inline_kb)


@dp.message(CommandStart())
async def start_command(message: Message, state: FSMContext):
    await connect_db()
    user_id = int(message.from_user.id)
    reg = await user_exists_reg(user_id)
    if reg:
        user_name = reg["name"]
        await message.answer(
            f"☕️ Добро пожаловать, {user_name}, в сеть Coffemania!\nНажмите «Меню» для выбора действий☺️",
            reply_markup=make_reply_menu_button()
        )
    else:
        await state.set_state(RegStates.fio)
        await message.answer(
            "Добро пожаловать в сеть Coffemaia!\n"
            "Пожалуйста, сначала зарегистрируйтесь. Введите ваше ФИО (Фамилия Имя Отчество):",
            reply_markup=ReplyKeyboardRemove()
        )

def make_gender_inline() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Мужской", callback_data="gender:Мужской"),
            InlineKeyboardButton(text="Женский", callback_data="gender:Женский")
        ]
    ])
    return kb

def make_contact_keyboard() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Поделиться контактом", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    return kb

@dp.message(RegStates.fio)
async def get_fio(message: Message, state: FSMContext):
    fio_parts = message.text.strip().split()
    if len(fio_parts) != 3:
        await message.answer("Ошибка формата. Введите ФИО в формате: Фамилия Имя Отчество.")
        return
    surname, name, patronymic = fio_parts
    await state.update_data(surname=surname, name=name, patronymic=patronymic)
    await state.set_state(RegStates.gender)
    await message.answer("Выберите ваш пол:", reply_markup=make_gender_inline())

@dp.callback_query(lambda c: c.data.startswith("gender:"))
async def cb_gender(callback: types.CallbackQuery, state: FSMContext):
    _, gender = callback.data.split(":", 1)
    await state.update_data(gender=gender)
    await state.set_state(RegStates.age)
    await callback.message.answer("Введите ваш возраст:")
    await callback.answer()

@dp.message(RegStates.age)
async def get_age(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Возраст должен быть числом. Повторите ввод:")
        return
    await state.update_data(age=int(message.text))
    await state.set_state(RegStates.phone)
    await message.answer(
        "Введите ваш номер телефона или нажмите кнопку для отправки контакта (если он сохранён):",
        reply_markup=make_contact_keyboard()
    )

@dp.message(RegStates.phone, F.contact)
async def get_phone_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    data = await state.get_data()
    user_id = int(message.from_user.id)
    await add_user(
        user_id,
        data["surname"],
        data["name"],
        data["patronymic"],
        data["gender"],
        data["age"],
        phone
    )
    full_name = f"{data['surname']} {data['name']} {data['patronymic']}"
    await message.answer(
        f"✅ {full_name}, регистрация успешно завершена!\n"
        "Нажмите «Меню» для продолжения.",
        reply_markup=make_reply_menu_button()
    )
    await state.clear()

@dp.message(RegStates.phone)
async def get_phone_text(message: Message, state: FSMContext):
    if message.contact:
        return
    phone = message.text.strip()
    if (any(char.isalpha() for char in phone)) or (phone.count("+") > 1):
        await message.answer("Неверный формат номера. Пожалуйста, введите номер, содержащий только цифры и знак '+', например: +79998887766")
        return

    pattern = re.compile(r'^\+?[0-9]+$')
    if not pattern.fullmatch(phone):
        await message.answer("Неверный формат номера. Пожалуйста, введите номер, содержащий только цифры и знак '+', например: +79998887766")
        return

    data = await state.get_data()
    user_id = int(message.from_user.id)
    await add_user(
        user_id,
        data["surname"],
        data["name"],
        data["patronymic"],
        data["gender"],
        data["age"],
        phone
    )
    full_name = f"{data['surname']} {data['name']} {data['patronymic']}"
    await message.answer(
        f"✅ {full_name}, регистрация успешно завершена!\n"
        "Нажмите «Меню» для продолжения.",
        reply_markup=make_reply_menu_button()
    )
    await state.clear()


@dp.message(lambda m: m.text == "Меню")
async def show_inline_main_menu(message: Message):
    await message.answer(
        "Выберите действие в боте:",
        reply_markup=make_main_menu_inline()
    )

@dp.callback_query(lambda c: c.data == "choose_restaurant")
async def cb_choose_restaurant(callback: types.CallbackQuery):
    restaurants = await get_restaurants_list()
    if not restaurants:
        await callback.message.answer("Нет ресторанов в базе.")
    else:
        inline_kb = make_restaurants_inline(restaurants)
        await callback.message.answer("Выберите ресторан:", reply_markup=inline_kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "order_history")
async def cb_order_history(callback: types.CallbackQuery):
    orders = await get_order_history(callback.from_user.id)
    if not orders:
        text = "У вас пока нет истории заказов."
    else:
        text = "История ваших заказов:\n\n"
        for order in orders:
            order_date = order['payment_date'].strftime('%d.%m.%Y %H:%M')
            text += (
                f"📝 Заказ {order['order_id']} от {order_date}\n"
                f"🍽 Меню: {order['menu_items'] or 'нет'}\n"
                f"🍷 Винная карта: {order['wine_items'] or 'нет'}\n"
                f"🔢 Количество: {order['count']}\n\n"
            )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="back_to_inline_main_menu")]
    ])
    await callback.message.answer(text, reply_markup=kb)  # <-- Изменено
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_inline_main_menu")
async def back_to_inline_main_menu(callback: types.CallbackQuery):
    await callback.message.answer(
        "Выберите действие в боте:",
        reply_markup=make_main_menu_inline()
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("rest_info:"))
async def cb_rest_info(callback: types.CallbackQuery):
    restaurant_id = int(callback.data.split(":")[1])
    await send_restaurant_info(callback.message, restaurant_id)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_restaurants_list")
async def cb_back_to_restaurants_list(callback: types.CallbackQuery):
    restaurants = await get_restaurants_list()
    if not restaurants:
        await callback.message.delete()
        await callback.message.answer("Нет ресторанов в базе.")
    else:
        kb = make_restaurants_inline(restaurants)
        await callback.message.delete()
        await callback.message.answer("Выберите ресторан:", reply_markup=kb)
    await callback.answer()




@dp.callback_query(lambda c: c.data.startswith("menu:"))
async def menu_callback(callback: types.CallbackQuery):
    restaurant_id = int(callback.data.split(":")[1])
    await send_menu_categories(callback.message, restaurant_id)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("wine:"))
async def wine_callback(callback: types.CallbackQuery):
    restaurant_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    async with db_pool.acquire() as conn:
        user_info = await conn.fetchrow("SELECT age FROM clients WHERE user_id = $1", user_id)
    # Если возраст меньше 18, отправляем сообщение с отказом
    if user_info and user_info["age"] < 18:
        await callback.message.answer("Вам меньше 18 лет, просмотр винной карты недоступен!😠")
        await send_restaurant_info(callback.message, restaurant_id)
    else:
        await send_wine_categories(callback.message, restaurant_id)
    await callback.answer()



@dp.callback_query(lambda c: c.data.startswith("cat_menu:"))
async def cat_menu_callback(callback: types.CallbackQuery):
    _, rest_id_str, cat_id_str = callback.data.split(":")
    restaurant_id = int(rest_id_str)
    category_id = int(cat_id_str)
    items = await get_menu_items(restaurant_id, category_id)
    if not items:
        await callback.message.answer("В этой категории пока нет блюд.")
    else:
        inline_kb = make_items_inline(items, is_wine=False)
        back_btn = InlineKeyboardButton(
            text="Назад",
            callback_data=f"menu:{restaurant_id}"
        )
        inline_kb.inline_keyboard.append([back_btn])
        await callback.message.answer("🍽 Меню выбранной категории:", reply_markup=inline_kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("cat_wine:"))
async def cat_wine_callback(callback: types.CallbackQuery):
    _, rest_id_str, cat_id_str = callback.data.split(":")
    restaurant_id = int(rest_id_str)
    category_id = int(cat_id_str)
    items = await get_wine_items(restaurant_id, category_id)
    if not items:
        await callback.message.answer("В этой категории пока нет напитков.")
    else:
        inline_kb = make_items_inline(items, is_wine=True)
        back_btn = InlineKeyboardButton(
            text="Назад",
            callback_data=f"wine:{restaurant_id}"
        )
        inline_kb.inline_keyboard.append([back_btn])
        await callback.message.answer("🍷 Винная карта выбранной категории:", reply_markup=inline_kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("dish_menu:"))
async def dish_menu_callback(callback: types.CallbackQuery):
    _, item_id_str = callback.data.split(":", 1)
    item_id = int(item_id_str)
    dish = await get_menu_item_by_id(db_pool, item_id)
    if dish:
        await send_item_info(callback.message, dish, is_wine=False)
    else:
        await callback.message.answer("Блюдо не найдено.")
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("dish_wine:"))
async def dish_wine_callback(callback: types.CallbackQuery):
    _, item_id_str = callback.data.split(":", 1)
    item_id = int(item_id_str)
    wine = await get_wine_item_by_id(db_pool, item_id)
    if wine:
        await send_item_info(callback.message, wine, is_wine=True)
    else:
        await callback.message.answer("Напиток не найден.")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("back_to_category_menu:"))
async def back_to_category_menu_callback(callback: types.CallbackQuery):
    _, rest_id_str, cat_id_str = callback.data.split(":")
    restaurant_id = int(rest_id_str)
    category_id = int(cat_id_str)
    items = await get_menu_items(restaurant_id, category_id)
    if not items:
        await callback.message.answer("В этой категории пока нет блюд.")
    else:
        inline_kb = make_items_inline(items, is_wine=False)
        back_btn = InlineKeyboardButton(
            text="Назад",
            callback_data=f"menu:{restaurant_id}"
        )
        inline_kb.inline_keyboard.append([back_btn])
        await callback.message.answer("🍽 Меню выбранной категории:", reply_markup=inline_kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("back_to_category_wine:"))
async def back_to_category_wine_callback(callback: types.CallbackQuery):
    _, rest_id_str, cat_id_str = callback.data.split(":")
    restaurant_id = int(rest_id_str)
    category_id = int(cat_id_str)
    items = await get_wine_items(restaurant_id, category_id)
    if not items:
        await callback.message.answer("В этой категории пока нет вин/напитков.")
    else:
        inline_kb = make_items_inline(items, is_wine=True)
        back_btn = InlineKeyboardButton(
            text="Назад",
            callback_data=f"wine:{restaurant_id}"
        )
        inline_kb.inline_keyboard.append([back_btn])
        await callback.message.answer("🍷 Винная карта выбранной категории:", reply_markup=inline_kb)
    await callback.answer()

@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    logger.info(f"Получен успешный платеж: {message.successful_payment}")
    order_id = await save_order_from_cart(message.from_user.id)
    await clear_cart(message.from_user.id)
    user = await user_exists_reg(message.from_user.id)
    user_name = user["name"]
    await message.answer(
        f"✅ *Платеж прошёл успешно!*\n\n"
        f"💰 *Сумма платежа:* {message.successful_payment.total_amount // 100} {message.successful_payment.currency}\n"
        f"🆔 *Номер заказа:* {order_id}\n\n"
        f"Спасибо, {user_name}, что выбрали Coffemania!\n"
        f"Ваш заказ принят и скоро начнёт готовиться😇"
    )

    await message.answer(
        "Вы можете снова открыть «Меню» для дальнейших действий.",
        reply_markup=make_reply_menu_button()
    )


async def set_main_menu():
    commands = [BotCommand(command="start", description="Начать работу")]
    await bot.set_my_commands(commands)

async def start_bot():
    await connect_db()
    await set_main_menu()
    asyncio.create_task(periodic_parser())
    await dp.start_polling(bot)

async def main():
    await start_bot()

if __name__ == "__main__":
    asyncio.run(main())
