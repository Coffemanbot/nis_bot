import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton
from database import SessionLocal, User
from config1 import BOT_TOKEN

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class RegStates(StatesGroup):
    fio = State()
    gender = State()
    age = State()
    phone = State()

def user_exists(user_id: int):
    db = SessionLocal()
    exists = db.query(User).filter(User.user_id == user_id).first()
    db.close()
    return exists

def add_user(user_id: int, surname: str, name: str, patronymic: str, gender: str, age: int, phone: str):
    db = SessionLocal()
    user = User(
        user_id=user_id,
        surname=surname,
        name=name,
        patronymic=patronymic,
        gender=gender,
        age=age,
        phone=phone
    )
    db.add(user)
    db.commit()
    db.close()

@dp.message(CommandStart())
async def start_reg(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_exists(user_id):
        user = user_exists(user_id)
        fio_full = f"{user.name}"
        await message.answer(f"👋 Привет, {fio_full}, вы уже зарегистрированы!")
        return
    await state.set_state(RegStates.fio)
    await message.answer("Введите ваше ФИО в формате: Фамилия Имя Отчество:")

@dp.message(RegStates.fio)
async def get_fio(message: types.Message, state: FSMContext):
    fio_parts = message.text.strip().split()
    if len(fio_parts) != 3:
        return await message.answer("Ошибка формата. Введите ФИО в формате: Фамилия Имя Отчество.")
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
async def get_gender(message: types.Message, state: FSMContext):
    gender = message.text.strip()
    if gender.lower() not in ["мужской", "женский"]:
        return await message.answer("Пожалуйста, выберите один из предложенных вариантов: Мужской или Женский.")
    await state.update_data(gender=gender)
    await state.set_state(RegStates.age)
    await message.answer("Введите ваш возраст:", reply_markup=ReplyKeyboardRemove())

@dp.message(RegStates.age)
async def get_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Возраст должен быть числом. Повторите ввод:")
    await state.update_data(age=int(message.text))
    await state.set_state(RegStates.phone)
    contact_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Отправить контакт", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "Пожалуйста, отправьте ваш контакт или введите номер телефона вручную (например, +79998887766):",
        reply_markup=contact_keyboard
    )

@dp.message(RegStates.phone)
async def get_phone(message: types.Message, state: FSMContext):
    if message.contact:
        phone = message.contact.phone_number
    else:
        phone = message.text.strip()
    await state.update_data(phone=phone)
    data = await state.get_data()
    user_id = message.from_user.id
    add_user(user_id, data['surname'], data['name'], data['patronymic'], data['gender'], data['age'], data['phone'])
    full_name = f"{data['surname']} {data['name']}"
    await message.answer(f"✅ {full_name}, регистрация успешно завершена!", reply_markup=ReplyKeyboardRemove())
    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())