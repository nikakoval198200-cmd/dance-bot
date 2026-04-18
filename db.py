import aiosqlite

DB_NAME = "dance.db"


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            schedule TEXT,
            limit_count INTEGER
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            fio TEXT,
            phone TEXT,
            age TEXT,
            style TEXT,
            group_id INTEGER,
            status TEXT
        )
        """)

        await db.commit()


async def get_groups():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM groups")
        return await cursor.fetchall()


async def get_group(group_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM groups WHERE id = ?", (group_id,))
        return await cursor.fetchone()


async def count_in_group(group_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM bookings WHERE group_id = ? AND status='approved'",
            (group_id,))
        return (await cursor.fetchone())[0]


async def add_booking(data):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
        INSERT INTO bookings (user_id, fio, phone, age, style, group_id, status)
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
        """, (
            data["user_id"],
            data["fio"],
            data["phone"],
            data["age"],
            data["style"],
            data["group_id"]
        ))
        await db.commit()
        return cursor.lastrowid


async def update_status(booking_id, status):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE bookings SET status=? WHERE id=?",
            (status, booking_id)
        )
        await db.commit()


async def get_booking(booking_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,))
        return await cursor.fetchone()