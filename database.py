from sqlalchemy import create_engine, Column, BigInteger, String, Integer, Text, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base
from config1 import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode=disable"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()

class User(Base):
    __tablename__ = "clients"
    user_id = Column(BigInteger, primary_key=True)
    surname = Column(String, nullable=False)
    name = Column(String, nullable=False)
    patronymic = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    phone = Column(String, nullable=False)

Base.metadata.create_all(bind=engine)

class Menu(Base):
    __tablename__ = "menu"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    category = Column(String(255))
    name = Column(String(255), nullable=False)
    price = Column(String(50))
    calories = Column(Integer)
    proteins = Column(String(50))
    fats = Column(String(50))
    carbohydrates = Column(String(50))
    weight = Column(String(50))
    description = Column(Text)
    composition = Column(Text)
    allergens = Column(Text)
    image = Column(Text)
    availability = Column(Boolean, default=True)
    timetable = Column(Text)
    restaurant_id = Column(Integer, primary_key=True, nullable=False, default=0)

class VineCard(Base):
    __tablename__ = "vine_card"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    category = Column(String(255))
    name = Column(String(255), nullable=False)
    price = Column(String(50))
    calories = Column(Integer)
    proteins = Column(String(50))
    fats = Column(String(50))
    carbohydrates = Column(String(50))
    weight = Column(String(50))
    description = Column(Text)
    composition = Column(Text)
    allergens = Column(Text)
    image = Column(Text)
    availability = Column(Boolean, default=True)
    timetable = Column(Text)
    restaurant_id = Column(Integer, primary_key=True, nullable=False)

class Restaurant(Base):
    __tablename__ = "restaurants"

    restaurant_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    address = Column(Text)
    image = Column(Text)
    metro = Column(Text)
    description = Column(Text)
    veranda = Column(Text)
    changing_table = Column(Text)
    animation = Column(Text)
    work_time = Column(Text)
    contacts = Column(Text)
    vine_card = Column(Text)

Base.metadata.create_all(bind=engine)