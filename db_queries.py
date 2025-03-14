import asyncpg

async def get_menu_item_by_id(db_pool, item_id: int) -> dict:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, price, calories, proteins, fats, carbohydrates, weight,
                   description, allergens, availability, image, category, restaurant_id, category_id
            FROM menu
            WHERE id = $1
        """, item_id)
    return dict(row) if row else {}

async def get_wine_item_by_id(db_pool, item_id: int) -> dict:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, price, calories, proteins, fats, carbohydrates, weight,
                   description, allergens, availability, image, category, restaurant_id, category_id
            FROM vine_card
            WHERE id = $1
        """, item_id)
    return dict(row) if row else {}