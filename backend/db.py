from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager

import asyncpg
import os

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "debateitout"),
        user=os.getenv("DB_USER", "debateitout"),
        password=os.getenv("DB_PASSWORD", "debateitout"),
        min_size=1,
        max_size=10,
    )
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS debates (
                id            UUID    PRIMARY KEY,
                custom_name   TEXT,
                proposition   TEXT    NOT NULL,
                faction_a     JSONB   NOT NULL,
                faction_b     JSONB   NOT NULL,
                max_rounds    INT     NOT NULL DEFAULT 6,
                current_round INT     NOT NULL DEFAULT 1,
                status        TEXT    NOT NULL DEFAULT 'active',
                pinned        BOOLEAN DEFAULT false,
                created_at    BIGINT  NOT NULL,
                updated_at    BIGINT  NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
                debate_id   UUID    NOT NULL REFERENCES debates(id) ON DELETE CASCADE,
                round       INT     NOT NULL,
                faction     TEXT    NOT NULL,
                model_id    TEXT    NOT NULL,
                argument    TEXT    NOT NULL,
                team_msg    TEXT,
                thinking    TEXT,
                latency     INT,
                created_at  BIGINT  NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_debates_pinned_updated
                ON debates(pinned DESC, updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_messages_debate_round
                ON messages(debate_id, round);
        """)
    print("Database ready")


async def close_pool() -> None:
    if _pool:
        await _pool.close()


@asynccontextmanager
async def pool_conn():
    assert _pool is not None, "DB pool not initialised"
    async with _pool.acquire() as conn:
        yield conn


# --- helpers ---

def _debate_row_to_dict(row: asyncpg.Record) -> dict:
    return {
        "id": str(row["id"]),
        "customName": row["custom_name"],
        "proposition": row["proposition"],
        "factionA": json.loads(row["faction_a"]) if isinstance(row["faction_a"], str) else dict(row["faction_a"]),
        "factionB": json.loads(row["faction_b"]) if isinstance(row["faction_b"], str) else dict(row["faction_b"]),
        "maxRounds": row["max_rounds"],
        "currentRound": row["current_round"],
        "status": row["status"],
        "pinned": row["pinned"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _message_row_to_dict(row: asyncpg.Record) -> dict:
    return {
        "id": str(row["id"]),
        "debateId": str(row["debate_id"]),
        "round": row["round"],
        "faction": row["faction"],
        "modelId": row["model_id"],
        "argument": row["argument"],
        "teamMsg": row["team_msg"],
        "thinking": row["thinking"],
        "latency": row.get("latency"),
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
    async with _pool_conn() as conn:
        await conn.execute(
            """
            INSERT INTO debates
                (id, proposition, faction_a, faction_b, max_rounds, current_round, status, pinned, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, 1, 'active', false, $6, $7)
            """,
            debate_id,
            proposition,
            json.dumps(faction_a),
            json.dumps(faction_b),
            max_rounds,
            now,
            now,
        )
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
    async with _pool_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT d.*, COUNT(m.id) AS turn_count
            FROM debates d
            LEFT JOIN messages m ON m.debate_id = d.id
            GROUP BY d.id
            ORDER BY d.pinned DESC, d.updated_at DESC
            """
        )
    result = []
    for row in rows:
        d = _debate_row_to_dict(row)
        d["turnCount"] = row["turn_count"]
        d["propositionPreview"] = row["proposition"][:100]
        result.append(d)
    return result


async def get_debate(debate_id: str) -> dict | None:
    async with _pool_conn() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM debates WHERE id = $1", debate_id
        )
    return _debate_row_to_dict(row) if row else None


async def get_debate_for_update(conn: asyncpg.Connection, debate_id: str) -> dict | None:
    """SELECT ... FOR UPDATE — must be called inside an active transaction."""
    row = await conn.fetchrow(
        "SELECT * FROM debates WHERE id = $1 FOR UPDATE", debate_id
    )
    return _debate_row_to_dict(row) if row else None


async def update_debate(debate_id: str, updates: dict) -> dict | None:
    """Only handles customName and pinned — status/round go through set_debate_status."""
    fields: list[str] = []
    values: list = []
    param = 1

    if "customName" in updates:
        fields.append(f"custom_name = ${param}")
        values.append(updates["customName"])
        param += 1
    if "pinned" in updates:
        fields.append(f"pinned = ${param}")
        values.append(updates["pinned"])
        param += 1

    if not fields:
        return await get_debate(debate_id)

    fields.append(f"updated_at = ${param}")
    values.append(int(time.time() * 1000))
    param += 1
    values.append(debate_id)

    sql = f"UPDATE debates SET {', '.join(fields)} WHERE id = ${param} RETURNING *"
    async with _pool_conn() as conn:
        row = await conn.fetchrow(sql, *values)
    return _debate_row_to_dict(row) if row else None


async def delete_debate(debate_id: str) -> bool:
    async with _pool_conn() as conn:
        result = await conn.execute(
            "DELETE FROM debates WHERE id = $1", debate_id
        )
    return result == "DELETE 1"


async def set_debate_status(
    conn: asyncpg.Connection,
    debate_id: str,
    status: str,
    current_round: int | None = None,
) -> None:
    """Status + optional round transition — always called inside a transaction."""
    now = int(time.time() * 1000)
    if current_round is not None:
        await conn.execute(
            "UPDATE debates SET status = $1, current_round = $2, updated_at = $3 WHERE id = $4",
            status, current_round, now, debate_id,
        )
    else:
        await conn.execute(
            "UPDATE debates SET status = $1, updated_at = $2 WHERE id = $3",
            status, now, debate_id,
        )


# --- message CRUD ---

async def get_messages(debate_id: str) -> list[dict]:
    async with _pool_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM messages
            WHERE debate_id = $1
            ORDER BY round ASC, created_at ASC
            """,
            debate_id,
        )
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
    async with _pool_conn() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO messages
                (debate_id, round, faction, model_id, argument, team_msg, thinking, latency, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            debate_id, round, faction, model_id, argument, team_msg, thinking, latency, now,
        )
    return _message_row_to_dict(row)
