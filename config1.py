import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "FAKE_BOT_TOKEN")
PAYMENT_PROVIDER_TOKEN = os.environ.get("PAYMENT_PROVIDER_TOKEN", "FAKE_PAYMENT_PROVIDER_TOKEN")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "project")
DB_USER = os.environ.get("DB_USER", "user")
DB_PASS = os.environ.get("DB_PASS", "pass")

DB_CONFIG = {
    "database": DB_NAME,
    "user": DB_USER,
    "password": DB_PASS,
    "host": DB_HOST,
    "port": DB_PORT
}
BASE_URL = os.environ.get("BASE_URL", "https://coffeemania.ru")
print("Hello worl")