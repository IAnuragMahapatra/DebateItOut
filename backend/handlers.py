from __future__ import annotations

import json

import httpx

# model dispatch layer
# takes pre-assembled system + messages from the caller
# context assembly is moderator.py's job

HTTP_TIMEOUT = httpx.Timeout(120.0)


async def chat_anthropic(model: dict, system: str, messages: list[dict]) -> dict:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "x-api-key": model.get("apiKey", ""),
    }
    if model.get("anthropicVersion"):
        headers["anthropic-version"] = model["anthropicVersion"]

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.post(
            model["apiUrl"],
            headers=headers,
            json={
                "model": model["model"],
                "max_tokens": model["maxTokens"],
                "system": system,
                "messages": messages,
            },
        )

    response.raise_for_status()
    data = response.json()

    if "error" in data:
        err = data["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise ValueError(f"Model error: {msg}")

    content: list = data.get("content", [])
    text_block = next((c for c in content if c.get("type") == "text"), None)
    thinking_block = next((c for c in content if c.get("type") == "thinking"), None)

    if not text_block:
        print(f"[{model['name']}] Unexpected response shape: {json.dumps(data)}")

    return {
        "reply": text_block["text"] if text_block else "No response from model.",
        "thinking": thinking_block["thinking"] if thinking_block else None,
    }


async def chat_openai(model: dict, messages: list[dict]) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {model.get('apiKey', '')}",
    }

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.post(
            model["apiUrl"],
            headers=headers,
            json={
                "model": model["model"],
                "messages": messages,
                "max_tokens": model["maxTokens"],
            },
        )

    response.raise_for_status()
    data = response.json()

    if "error" in data:
        err = data["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise ValueError(f"Model error: {msg}")

    choice = (data.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content")

    if not content:
        print(f"[{model['name']}] Unexpected response shape: {json.dumps(data)}")

    return {"reply": content or "No response from model.", "thinking": None}


async def dispatch(model: dict, system: str, messages: list[dict]) -> dict:
    """Single entry point — routes to anthropic or openai based on model type."""
    if model["type"] == "anthropic":
        return await chat_anthropic(model, system, messages)
    # OpenAI-compatible endpoints take system as the first message
    full_messages = [{"role": "system", "content": system}] + messages
    return await chat_openai(model, full_messages)

