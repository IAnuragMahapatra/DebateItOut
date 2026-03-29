from __future__ import annotations

import os
import re
import time
import uuid
from contextlib import asynccontextmanager

import db
import handlers
import moderator
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

FIELD_MAP = {
    "NAME": "name",
    "TYPE": "type",
    "API_URL": "apiUrl",
    "API_KEY": "apiKey",
    "ANTHROPIC_VERSION": "anthropicVersion",
    "MODEL": "model",
    "MAX_TOKENS": "maxTokens",
}


def load_models() -> list[dict]:
    models: dict[str, dict] = {}
    global_max_tokens = int(os.getenv("MAX_TOKENS", "16384"))

    for key, value in os.environ.items():
        m = re.match(r"^MODEL_(.+?)_(.+)$", key)
        if not m:
            continue
        model_id, field = m.group(1), m.group(2)
        if model_id not in models:
            models[model_id] = {"id": model_id.lower()}
        mapped = FIELD_MAP.get(field)
        if mapped:
            models[model_id][mapped] = int(value) if field == "MAX_TOKENS" else value

    result = []
    for m in models.values():
        if not m.get("maxTokens"):
            m["maxTokens"] = global_max_tokens
        if m.get("name") and m.get("type") and m.get("apiUrl") and m.get("model"):
            result.append(m)
    return result


MODELS = load_models()
print(f"Loaded {len(MODELS)} model(s): {', '.join(m['name'] for m in MODELS)}")

DEFAULT_MAX_ROUNDS = int(os.getenv("DEFAULT_MAX_ROUNDS", "6"))
MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "8000"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    yield
    await db.close_pool()


app = FastAPI(title="DebateItOut", lifespan=lifespan)

ALLOWED_ORIGINS = [
    "http://localhost:3002",
    "http://127.0.0.1:3002",
]
if os.getenv("ALLOWED_ORIGIN"):
    ALLOWED_ORIGINS.append(os.getenv("ALLOWED_ORIGIN"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_BODY_SIZE = 100 * 1024


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_SIZE:
        return JSONResponse(status_code=413, content={"error": "Request body too large"})
    return await call_next(request)


# --- model pool ---

@app.get("/models")
def get_models():
    return [{"id": m["id"], "name": m["name"], "type": m["type"]} for m in MODELS]


# --- debate CRUD ---

@app.post("/debates")
async def create_debate_endpoint(request: Request):
    body = await request.json()
    proposition = (body.get("proposition") or "").strip()
    faction_a = body.get("factionA") or {}
    faction_b = body.get("factionB") or {}
    max_rounds = body.get("maxRounds", DEFAULT_MAX_ROUNDS)

    if not proposition:
        raise HTTPException(400, "proposition is required")
    if len(proposition) > 2000:
        raise HTTPException(400, "proposition must be 2000 characters or fewer")

    a_models = faction_a.get("models") or []
    b_models = faction_b.get("models") or []

    if not (1 <= len(a_models) <= 5):
        raise HTTPException(400, "factionA must have 1–5 models")
    if not (1 <= len(b_models) <= 5):
        raise HTTPException(400, "factionB must have 1–5 models")

    known_ids = {m["id"] for m in MODELS}
    for mid in a_models + b_models:
        if mid not in known_ids:
            raise HTTPException(400, f"Unknown model ID: {mid}")

    if not (1 <= max_rounds <= 20):
        raise HTTPException(400, "maxRounds must be between 1 and 20")

    debate_id = str(uuid.uuid4())
    debate = await db.create_debate(
        debate_id,
        proposition,
        {"models": a_models, "stance": faction_a.get("stance") or "for"},
        {"models": b_models, "stance": faction_b.get("stance") or "against"},
        max_rounds,
    )
    return debate


@app.get("/debates")
async def list_debates_endpoint():
    try:
        return await db.get_all_debates()
    except Exception as e:
        raise HTTPException(500, f"Failed to retrieve debates: {e}")


@app.get("/debates/{debate_id}")
async def get_debate_endpoint(debate_id: str):
    debate = await db.get_debate(debate_id)
    if not debate:
        raise HTTPException(404, "Debate not found")

    messages = await db.get_messages(debate_id)
    return _build_full_response(debate, messages)


@app.patch("/debates/{debate_id}")
async def update_debate_endpoint(debate_id: str, request: Request):
    body = await request.json()
    updates: dict = {}
    if "customName" in body:
        updates["customName"] = body["customName"]
    if "pinned" in body:
        updates["pinned"] = body["pinned"]

    debate = await db.update_debate(debate_id, updates)
    if not debate:
        raise HTTPException(404, "Debate not found")
    return debate


@app.delete("/debates/{debate_id}")
async def delete_debate_endpoint(debate_id: str):
    deleted = await db.delete_debate(debate_id)
    if not deleted:
        raise HTTPException(404, "Debate not found")
    return {"success": True}


# --- turn endpoints ---

async def _execute_turn(debate_id: str, debate: dict) -> dict:
    """Shared turn logic — called after status guard from both advance and retry."""
    messages = await db.get_messages(debate_id)
    speaker = moderator.determine_next_speaker(debate, messages, MODELS)
    model = next((m for m in MODELS if m["id"] == speaker["model_id"]), None)
    if not model:
        raise ValueError(f"Model {speaker['model_id']} not found in pool")

    context = moderator.assemble_context(debate, messages, speaker, MODELS)
    context = moderator.apply_token_budget(context, speaker["model_id"])

    t0 = time.time()
    result = await handlers.dispatch(model, context["system"], context["messages"])
    latency = int((time.time() - t0) * 1000)

    parsed = moderator.parse_xml_response(result["reply"])
    if not parsed["parse_ok"]:
        print(f"[parse-fallback] debate={debate_id} round={debate['currentRound']} model={speaker['model_id']}")

    # native thinking (Anthropic) takes priority over XML-parsed thinking
    thinking = result.get("thinking") or parsed["thinking"]

    msg = await db.insert_message(
        debate_id=debate_id,
        round=debate["currentRound"],
        faction=speaker["faction"],
        model_id=speaker["model_id"],
        argument=parsed["argument"],
        team_msg=parsed["team_msg"],
        thinking=thinking,
        latency=latency,
    )

    all_messages = await db.get_messages(debate_id)
    next_status, next_round = moderator.determine_next_status(debate, all_messages)

    async with db.pool_conn() as conn:
        async with conn.transaction():
            await db.set_debate_status(conn, debate_id, next_status, next_round)

    return {
        "debateId": debate_id,
        "message": {**msg, "parseOk": parsed["parse_ok"]},
        "round": next_round if next_round is not None else debate["currentRound"],
        "status": next_status,
        "tokenEstimate": context["token_estimate"],
        "evictedRounds": context["evicted_rounds"],
    }


@app.post("/debates/{debate_id}/turn")
async def advance_turn(debate_id: str):
    async with db.pool_conn() as conn:
        async with conn.transaction():
            debate = await db.get_debate_for_update(conn, debate_id)
            if not debate:
                raise HTTPException(404, "Debate not found")
            if debate["status"] != "active":
                raise HTTPException(409, {"error": "Cannot advance turn", "status": debate["status"]})
            await db.set_debate_status(conn, debate_id, "turn_in_progress")

    try:
        return await _execute_turn(debate_id, debate)
    except HTTPException:
        raise
    except Exception as e:
        async with db.pool_conn() as conn:
            async with conn.transaction():
                await db.set_debate_status(conn, debate_id, "error")
        raise HTTPException(502, f"Model dispatch failed: {e}")


@app.post("/debates/{debate_id}/retry-turn")
async def retry_turn(debate_id: str):
    async with db.pool_conn() as conn:
        async with conn.transaction():
            debate = await db.get_debate_for_update(conn, debate_id)
            if not debate:
                raise HTTPException(404, "Debate not found")
            if debate["status"] != "error":
                raise HTTPException(409, {"error": "retry-turn only valid from error status", "status": debate["status"]})
            await db.set_debate_status(conn, debate_id, "turn_in_progress")

    try:
        return await _execute_turn(debate_id, debate)
    except HTTPException:
        raise
    except Exception as e:
        async with db.pool_conn() as conn:
            async with conn.transaction():
                await db.set_debate_status(conn, debate_id, "error")
        raise HTTPException(502, f"Model dispatch failed: {e}")





@app.get("/debates/{debate_id}/turn-preview")
async def turn_preview(debate_id: str):
    debate = await db.get_debate(debate_id)
    if not debate:
        raise HTTPException(404, "Debate not found")
    if debate["status"] not in ("active", "error"):
        raise HTTPException(409, {"error": "No pending turn", "status": debate["status"]})

    messages = await db.get_messages(debate_id)
    speaker = moderator.determine_next_speaker(debate, messages, MODELS)

    context = moderator.assemble_context(debate, messages, speaker, MODELS)
    context = moderator.apply_token_budget(context, speaker["model_id"])

    max_tokens = int(
        os.getenv(f"MAX_CONTEXT_TOKENS_{speaker['model_id'].upper()}")
        or os.getenv("MAX_CONTEXT_TOKENS", "8000")
    )

    return {
        "nextSpeaker": {
            "faction": speaker["faction"],
            "modelId": speaker["model_id"],
            "modelName": speaker.get("model_name", speaker["model_id"]),
        },
        "systemPrompt": context["system"],
        "contextMessages": context["messages"],
        "tokenEstimate": context["token_estimate"],
        "evictedRounds": context["evicted_rounds"],
        "maxContextTokens": max_tokens,
    }


# --- helpers ---

def _build_full_response(debate: dict, messages: list[dict]) -> dict:
    """Structures messages into public transcript + per-faction private data."""
    public_transcript = []
    faction_a_team: list[dict] = []
    faction_a_thinking: list[dict] = []
    faction_b_team: list[dict] = []
    faction_b_thinking: list[dict] = []

    for msg in messages:
        public_transcript.append({
            "id": msg["id"],
            "round": msg["round"],
            "faction": msg["faction"],
            "modelId": msg["modelId"],
            "argument": msg["argument"],
            "latency": msg.get("latency"),
            "createdAt": msg["createdAt"],
        })

        if msg["faction"] == "A":
            if msg.get("teamMsg"):
                faction_a_team.append({"round": msg["round"], "modelId": msg["modelId"], "teamMessage": msg["teamMsg"], "createdAt": msg["createdAt"]})
            if msg.get("thinking"):
                faction_a_thinking.append({"round": msg["round"], "modelId": msg["modelId"], "thinking": msg["thinking"], "createdAt": msg["createdAt"]})
        else:
            if msg.get("teamMsg"):
                faction_b_team.append({"round": msg["round"], "modelId": msg["modelId"], "teamMessage": msg["teamMsg"], "createdAt": msg["createdAt"]})
            if msg.get("thinking"):
                faction_b_thinking.append({"round": msg["round"], "modelId": msg["modelId"], "thinking": msg["thinking"], "createdAt": msg["createdAt"]})

    return {
        **debate,
        "publicTranscript": public_transcript,
        "factionAPrivate": {"teamMessages": faction_a_team, "thinking": faction_a_thinking},
        "factionBPrivate": {"teamMessages": faction_b_team, "thinking": faction_b_thinking},
    }


# --- static frontend ---

_frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_path):
    app.mount("/", StaticFiles(directory=_frontend_path, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "3002"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
