from __future__ import annotations

import json
import time
import asyncpg
import os

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "promptcouncil"),
        user=os.getenv("DB_USER", "promptcouncil"),
        password=os.getenv("DB_PASSWORD", "promptcouncil"),
        min_size=1,
        max_size=10,
    )
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id UUID PRIMARY KEY,
                custom_name TEXT,
                messages JSONB DEFAULT '[]'::jsonb,
                pinned BOOLEAN DEFAULT false,
                created_at BIGINT NOT NULL,
                updated_at BIGINT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_sessions_pinned ON sessions(pinned);
        """)
    print("Database ready")


async def close_pool() -> None:
    if _pool:
        await _pool.close()


def _pool_conn():
    assert _pool is not None, "DB pool not initialised"
    return _pool.acquire()


def _row_to_summary(row: asyncpg.Record) -> dict:
    msgs: list = row["messages"] if isinstance(row["messages"], list) else json.loads(row["messages"] or "[]")
    first_user = next((m["text"] for m in msgs if m.get("role") == "user"), None)
    return {
        "id": str(row["id"]),
        "customName": row["custom_name"],
        "messageCount": len(msgs),
        "pinned": row["pinned"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "preview": first_user,
    }


def _row_to_full(row: asyncpg.Record) -> dict:
    msgs: list = row["messages"] if isinstance(row["messages"], list) else json.loads(row["messages"] or "[]")
    return {
        "id": str(row["id"]),
        "customName": row["custom_name"],
        "messages": msgs,
        "pinned": row["pinned"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


async def get_all_sessions() -> list[dict]:
    async with _pool_conn() as conn:
        rows = await conn.fetch(
            "SELECT id, custom_name, messages, pinned, created_at, updated_at "
            "FROM sessions ORDER BY pinned DESC, updated_at DESC"
        )
    return [_row_to_summary(r) for r in rows]


async def get_session(session_id: str) -> dict | None:
    async with _pool_conn() as conn:
        row = await conn.fetchrow(
            "SELECT id, custom_name, messages, pinned, created_at, updated_at "
            "FROM sessions WHERE id = $1",
            session_id,
        )
    return _row_to_full(row) if row else None


async def create_session(session_id: str, custom_name: str | None = None) -> dict:
    now = int(time.time() * 1000)
    async with _pool_conn() as conn:
        await conn.execute(
            "INSERT INTO sessions (id, custom_name, messages, pinned, created_at, updated_at) "
            "VALUES ($1, $2, '[]'::jsonb, false, $3, $4)",
            session_id, custom_name, now, now,
        )
    return {
        "id": session_id,
        "customName": custom_name,
        "messages": [],
        "pinned": False,
        "createdAt": now,
        "updatedAt": now,
    }


async def update_session(session_id: str, updates: dict) -> dict | None:
    fields: list[str] = []
    values: list = []
    param = 1

    if "customName" in updates:
        fields.append(f"custom_name = ${param}")
        values.append(updates["customName"])
        param += 1
    if "messages" in updates:
        fields.append(f"messages = ${param}")
        values.append(json.dumps(updates["messages"]))
        param += 1
    if "pinned" in updates:
        fields.append(f"pinned = ${param}")
        values.append(updates["pinned"])
        param += 1

    if not fields:
        return await get_session(session_id)

    fields.append(f"updated_at = ${param}")
    values.append(int(time.time() * 1000))
    param += 1
    values.append(session_id)

    sql = f"UPDATE sessions SET {', '.join(fields)} WHERE id = ${param} RETURNING *"
    async with _pool_conn() as conn:
        row = await conn.fetchrow(sql, *values)

    return _row_to_full(row) if row else None


async def delete_session(session_id: str) -> bool:
    async with _pool_conn() as conn:
        result = await conn.execute(
            "DELETE FROM sessions WHERE id = $1", session_id
        )
    return result == "DELETE 1"
