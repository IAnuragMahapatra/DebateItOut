from __future__ import annotations

import os
import time
import uuid
import httpx
import asyncio
from contextlib import asynccontextmanager

import db
import handlers
import moderator
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

DEFAULT_MAX_ROUNDS = 6
AUTO_ADVANCE = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    yield
    await db.close_pool()

app = FastAPI(title="DebateItOut", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


# --- endpoints CRUD ---

@app.post("/api/endpoints")
async def create_endpoint_api(request: Request):
    body = await request.json()
    name = (body.get("name") or "").strip()
    type = body.get("type")
    base_url = body.get("baseUrl")
    api_key = body.get("apiKey")
    
    if not type or type not in ["openai", "anthropic"]:
        raise HTTPException(400, "Type must be openai or anthropic")
    if not base_url or not api_key:
        raise HTTPException(400, "baseUrl and apiKey are required")
        
    ep = await db.create_endpoint(name, type, base_url, api_key)
    return ep

@app.get("/api/endpoints")
async def get_endpoints_api():
    return await db.get_all_endpoints()

@app.delete("/api/endpoints/{ep_id}")
async def delete_endpoint_api(ep_id: str):
    deleted = await db.delete_endpoint(ep_id)
    if not deleted:
        raise HTTPException(404, "Endpoint not found")
    return {"success": True}

# --- model pool ---

@app.get("/api/models")
async def get_models():
    endpoints = await db.get_all_endpoints()
    all_models = []
    
    async def fetch_models(ep):
        try:
            base_url = ep["baseUrl"].rstrip("/")
            # If Anthropic, standard models endpoint is new, we fallback to hardcoded list or allow manually typing
            if ep["type"] == "anthropic":
                # Currently we'll just mock 2 standard models, ideally we query /v1/models if the API supports it
                # For safety, let's just use hardcoded popular Anthropic models
                return [
                    {"id": f"{ep['id']}|claude-3-5-sonnet-20240620", "name": "claude-3-5-sonnet", "type": "anthropic", "endpointId": ep["id"]},
                    {"id": f"{ep['id']}|claude-3-haiku-20240307", "name": "claude-3-haiku", "type": "anthropic", "endpointId": ep["id"]}
                ]
            else:
                # OpenAI compatible
                url = f"{base_url}/models" if not base_url.endswith("/v1") else f"{base_url}/models"
                if not url.endswith("/models"):
                    url = f"{base_url}/v1/models"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    headers = {"Authorization": f"Bearer {ep['apiKey']}"}
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        data_models = data.get("data", [])
                        res = []
                        for m in data_models:
                            slug = m["id"]
                            res.append({"id": f"{ep['id']}|{slug}", "name": slug, "type": ep["type"], "endpointId": ep["id"]})
                        return res
        except Exception as e:
            print(f"Error fetching models from {ep['name']}: {e}")
        return []
    
    tasks = [fetch_models(ep) for ep in endpoints]
    results = await asyncio.gather(*tasks)
    for r in results:
        all_models.extend(r)
        
    return all_models

@app.get("/api/config")
def get_config():
    return {"autoAdvance": AUTO_ADVANCE}

# --- debate CRUD ---

@app.post("/api/debates")
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

    if len(a_models) != len(set(a_models)):
        raise HTTPException(400, "Duplicate models in factionA")
    if len(b_models) != len(set(b_models)):
        raise HTTPException(400, "Duplicate models in factionB")
    if set(a_models) & set(b_models):
        raise HTTPException(400, "A model cannot appear in both factions")

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


@app.get("/api/debates")
async def list_debates_endpoint():
    try:
        return await db.get_all_debates()
    except Exception as e:
        raise HTTPException(500, f"Failed to retrieve debates: {e}")


@app.get("/api/debates/{debate_id}")
async def get_debate_endpoint(debate_id: str):
    debate = await db.get_debate(debate_id)
    if not debate:
        raise HTTPException(404, "Debate not found")

    messages = await db.get_messages(debate_id)
    return _build_full_response(debate, messages)


@app.patch("/api/debates/{debate_id}")
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


@app.delete("/api/debates/{debate_id}")
async def delete_debate_endpoint(debate_id: str):
    deleted = await db.delete_debate(debate_id)
    if not deleted:
        raise HTTPException(404, "Debate not found")
    return {"success": True}

# --- turn endpoints ---

async def _execute_turn(debate_id: str, debate: dict) -> dict:
    messages = await db.get_messages(debate_id)
    speaker = moderator.determine_next_speaker(debate, messages)
    
    ep_id, model_slug = speaker["model_id"].split("|", 1)
    endpoints = await db.get_all_endpoints()
    ep = next((e for e in endpoints if e["id"] == ep_id), None)
    
    if not ep:
        raise ValueError(f"Endpoint config for {ep_id} not found")

    context = moderator.assemble_context(debate, messages, speaker)
    context = moderator.apply_token_budget(context, speaker["model_id"])

    t0 = time.time()
    result = await handlers.dispatch(ep, model_slug, context["system"], context["messages"])
    latency = int((time.time() - t0) * 1000)

    parsed = moderator.parse_xml_response(result["reply"])
    if not parsed["parse_ok"]:
        print(f"[parse-fallback] debate={debate_id} round={debate['currentRound']} model={speaker['model_id']}")

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
        await db.set_debate_status(conn, debate_id, next_status, next_round)

    return {
        "debateId": debate_id,
        "message": {**msg, "parseOk": parsed["parse_ok"]},
        "round": next_round if next_round is not None else debate["currentRound"],
        "status": next_status,
        "tokenEstimate": context["token_estimate"],
        "evictedRounds": context["evicted_rounds"],
    }


@app.post("/api/debates/{debate_id}/turn")
async def advance_turn(debate_id: str):
    async with db.pool_conn() as conn:
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
            await db.set_debate_status(conn, debate_id, "error")
        raise HTTPException(502, f"Model dispatch failed: {e}")


@app.post("/api/debates/{debate_id}/retry-turn")
async def retry_turn(debate_id: str):
    async with db.pool_conn() as conn:
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
            await db.set_debate_status(conn, debate_id, "error")
        raise HTTPException(502, f"Model dispatch failed: {e}")

@app.get("/api/debates/{debate_id}/turn-preview")
async def turn_preview(debate_id: str):
    debate = await db.get_debate(debate_id)
    if not debate:
        raise HTTPException(404, "Debate not found")
    if debate["status"] not in ("active", "error"):
        raise HTTPException(409, {"error": "No pending turn", "status": debate["status"]})

    messages = await db.get_messages(debate_id)
    speaker = moderator.determine_next_speaker(debate, messages)

    context = moderator.assemble_context(debate, messages, speaker)
    context = moderator.apply_token_budget(context, speaker["model_id"])

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
        "maxContextTokens": 8000,
    }


def _build_full_response(debate: dict, messages: list[dict]) -> dict:
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


_frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_path):
    app.mount("/", StaticFiles(directory=_frontend_path, html=True), name="frontend")
