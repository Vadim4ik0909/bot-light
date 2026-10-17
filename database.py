import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
import aiosqlite
from config import config

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    notify_outage INTEGER DEFAULT 1,
                    notify_restore INTEGER DEFAULT 1,
                    notify_warning INTEGER DEFAULT 15,
                    notify_schedule_change INTEGER DEFAULT 1,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.commit()
        logger.info("Database initialized successfully.")

    async def add_subscriber(self, chat_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO subscribers (chat_id, username, first_name, is_active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(chat_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    is_active = 1;
            """, (chat_id, username, first_name))
            await db.commit()
            return True

    async def get_subscriber(self, chat_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM subscribers WHERE chat_id = ?", (chat_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None

    async def get_active_subscribers(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM subscribers WHERE is_active = 1") as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def update_setting(self, chat_id: int, key: str, value: Any):
        allowed_keys = {
            "notify_outage",
            "notify_restore",
            "notify_warning",
            "notify_schedule_change",
            "is_active"
        }
        if key not in allowed_keys:
            raise ValueError(f"Invalid setting key: {key}")

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"UPDATE subscribers SET {key} = ? WHERE chat_id = ?", (value, chat_id))
            await db.commit()

    async def set_state(self, key: str, value: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO state (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP;
            """, (key, value))
            await db.commit()

    async def get_state(self, key: str, default: Optional[str] = None) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT value FROM state WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0]
                return default

db = Database()
