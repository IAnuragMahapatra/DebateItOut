from __future__ import annotations

import json
import time
import uuid
import os
from pathlib import Path
from contextlib import asynccontextmanager

import aiosqlite

DB_PATH = Path.home() / ".debateitout" / "app.db"
_conn: aiosqlite.Connection | None = None


async def init_pool() -> None:
    global _conn
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    _conn = await aiosqlite.connect(DB_PATH)
    _conn.row_factory = aiosqlite.Row
    
    await _conn.execute("""
        CREATE TABLE IF NOT EXISTS endpoints (
            id TEXT PRIMARY KEY,
            name TEXT,
            type TEXT NOT NULL,
            base_url TEXT NOT NULL,
            api_key TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
    """)

    await _conn.execute("""
        CREATE TABLE IF NOT EXISTS debates (
            id            TEXT    PRIMARY KEY,
            custom_name   TEXT,
            proposition   TEXT    NOT NULL,
            faction_a     TEXT   NOT NULL,
            faction_b     TEXT   NOT NULL,
            max_rounds    INTEGER NOT NULL DEFAULT 6,
            current_round INTEGER NOT NULL DEFAULT 1,
            status        TEXT    NOT NULL DEFAULT 'active',
            pinned        INTEGER DEFAULT 0,
            created_at    INTEGER NOT NULL,
            updated_at    INTEGER NOT NULL
        );
    """)

    await _conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          TEXT    PRIMARY KEY,
            debate_id   TEXT    NOT NULL REFERENCES debates(id) ON DELETE CASCADE,
            round       INTEGER NOT NULL,
            faction     TEXT    NOT NULL,
            model_id    TEXT    NOT NULL,
            argument    TEXT    NOT NULL,
            team_msg    TEXT,
            thinking    TEXT,
            latency     INTEGER,
            created_at  INTEGER NOT NULL
        );
    """)

    await _conn.execute("CREATE INDEX IF NOT EXISTS idx_debates_pinned_updated ON debates(pinned DESC, updated_at DESC);")
    await _conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_debate_round ON messages(debate_id, round);")
    
    await _conn.commit()
    print("Database ready at", DB_PATH)


async def close_pool() -> None:
    if _conn:
        await _conn.close()


@asynccontextmanager
async def pool_conn():
    assert _conn is not None, "DB not initialised"
    yield _conn


# --- helpers ---

def _debate_row_to_dict(row: aiosqlite.Row) -> dict:
    return {
        "id": row["id"],
        "customName": row["custom_name"],
        "proposition": row["proposition"],
        "factionA": json.loads(row["faction_a"]) if row["faction_a"] else {},
        "factionB": json.loads(row["faction_b"]) if row["faction_b"] else {},
        "maxRounds": row["max_rounds"],
        "currentRound": row["current_round"],
        "status": row["status"],
        "pinned": bool(row["pinned"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _message_row_to_dict(row: aiosqlite.Row) -> dict:
    return {
        "id": row["id"],
        "debateId": row["debate_id"],
        "round": row["round"],
        "faction": row["faction"],
        "modelId": row["model_id"],
        "argument": row["argument"],
        "teamMsg": row["team_msg"],
        "thinking": row["thinking"],
        "latency": row["latency"],
        "createdAt": row["created_at"],
    }

def _endpoint_row_to_dict(row: aiosqlite.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "baseUrl": row["base_url"],
        "apiKey": row["api_key"],
        "createdAt": row["created_at"],
    }

# --- debate CRUD ---

async def create_debate(
    debate_id: str,
    proposition: str,
    faction_a: dict,
    faction_b: dict,
    max_rounds: int = 6,
) -> dict:
    now = int(time.time() * 1000)
    async with pool_conn() as conn:
        await conn.execute(
            """
            INSERT INTO debates
                (id, proposition, faction_a, faction_b, max_rounds, current_round, status, pinned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, 'active', 0, ?, ?)
            """,
            (debate_id, proposition, json.dumps(faction_a), json.dumps(faction_b), max_rounds, now, now)
        )
        await conn.commit()
    return {
        "id": debate_id,
        "customName": None,
        "proposition": proposition,
        "factionA": faction_a,
        "factionB": faction_b,
        "maxRounds": max_rounds,
        "currentRound": 1,
        "status": "active",
        "pinned": False,
        "createdAt": now,
        "updatedAt": now,
    }


async def get_all_debates() -> list[dict]:
    async with pool_conn() as conn:
        async with conn.execute(
            """
            SELECT d.*, COUNT(m.id) AS turn_count
            FROM debates d
            LEFT JOIN messages m ON m.debate_id = d.id
            GROUP BY d.id
            ORDER BY d.pinned DESC, d.updated_at DESC
            """
        ) as cursor:
            rows = await cursor.fetchall()
            
    result = []
    for row in rows:
        d = _debate_row_to_dict(row)
        d["turnCount"] = row["turn_count"]
        d["propositionPreview"] = row["proposition"][:100]
        result.append(d)
    return result


async def get_debate(debate_id: str) -> dict | None:
    async with pool_conn() as conn:
        async with conn.execute("SELECT * FROM debates WHERE id = ?", (debate_id,)) as cursor:
            row = await cursor.fetchone()
    return _debate_row_to_dict(row) if row else None


async def get_debate_for_update(conn: aiosqlite.Connection, debate_id: str) -> dict | None:
    # SQLite row-level locking isn't identical to Postgres FOR UPDATE. 
    # We rely on the transaction scope.
    async with conn.execute("SELECT * FROM debates WHERE id = ?", (debate_id,)) as cursor:
        row = await cursor.fetchone()
    return _debate_row_to_dict(row) if row else None


async def update_debate(debate_id: str, updates: dict) -> dict | None:
    fields: list[str] = []
    values: list = []

    if "customName" in updates:
        fields.append("custom_name = ?")
        values.append(updates["customName"])
    if "pinned" in updates:
        fields.append("pinned = ?")
        values.append(1 if updates["pinned"] else 0)

    if not fields:
        return await get_debate(debate_id)

    fields.append("updated_at = ?")
    values.append(int(time.time() * 1000))
    values.append(debate_id)

    sql = f"UPDATE debates SET {', '.join(fields)} WHERE id = ?"
    async with pool_conn() as conn:
        await conn.execute(sql, tuple(values))
        await conn.commit()
    return await get_debate(debate_id)


async def delete_debate(debate_id: str) -> bool:
    async with pool_conn() as conn:
        cursor = await conn.execute("DELETE FROM debates WHERE id = ?", (debate_id,))
        await conn.commit()
        return cursor.rowcount == 1


async def set_debate_status(
    conn: aiosqlite.Connection,
    debate_id: str,
    status: str,
    current_round: int | None = None,
) -> None:
    now = int(time.time() * 1000)
    if current_round is not None:
        await conn.execute(
            "UPDATE debates SET status = ?, current_round = ?, updated_at = ? WHERE id = ?",
            (status, current_round, now, debate_id),
        )
    else:
        await conn.execute(
            "UPDATE debates SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, debate_id),
        )
    await conn.commit()


# --- message CRUD ---

async def get_messages(debate_id: str) -> list[dict]:
    async with pool_conn() as conn:
        async with conn.execute(
            "SELECT * FROM messages WHERE debate_id = ? ORDER BY round ASC, created_at ASC",
            (debate_id,)
        ) as cursor:
            rows = await cursor.fetchall()
    return [_message_row_to_dict(r) for r in rows]


async def insert_message(
    debate_id: str,
    round: int,
    faction: str,
    model_id: str,
    argument: str,
    team_msg: str | None,
    thinking: str | None,
    latency: int | None = None,
) -> dict:
    now = int(time.time() * 1000)
    msg_id = str(uuid.uuid4())
    async with pool_conn() as conn:
        await conn.execute(
            """
            INSERT INTO messages
                (id, debate_id, round, faction, model_id, argument, team_msg, thinking, latency, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (msg_id, debate_id, round, faction, model_id, argument, team_msg, thinking, latency, now)
        )
        await conn.commit()
        
        async with conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)) as cursor:
            row = await cursor.fetchone()
            
    return _message_row_to_dict(row)

# --- endpoints CRUD ---

async def create_endpoint(name: str, type: str, base_url: str, api_key: str) -> dict:
    now = int(time.time() * 1000)
    ep_id = str(uuid.uuid4())
    if not name:
        name = base_url
    async with pool_conn() as conn:
        await conn.execute(
            "INSERT INTO endpoints (id, name, type, base_url, api_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ep_id, name, type, base_url, api_key, now)
        )
        await conn.commit()
        async with conn.execute("SELECT * FROM endpoints WHERE id = ?", (ep_id,)) as cursor:
            row = await cursor.fetchone()
    return _endpoint_row_to_dict(row)

async def get_all_endpoints() -> list[dict]:
    async with pool_conn() as conn:
        async with conn.execute("SELECT * FROM endpoints ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()
    return [_endpoint_row_to_dict(r) for r in rows]

async def delete_endpoint(ep_id: str) -> bool:
    async with pool_conn() as conn:
        cursor = await conn.execute("DELETE FROM endpoints WHERE id = ?", (ep_id,))
        await conn.commit()
        return cursor.rowcount == 1
