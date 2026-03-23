from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager

import db
from dotenv import load_dotenv
from fastapi import FastAPI, Request
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
        return JSONResponse(
            status_code=413, content={"error": "Request body too large"}
        )
    return await call_next(request)


@app.get("/models")
def get_models():
    return [{"id": m["id"], "name": m["name"], "type": m["type"]} for m in MODELS]


# debate endpoints wired in phase 4


_frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_path):
    app.mount("/", StaticFiles(directory=_frontend_path, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "3002"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
