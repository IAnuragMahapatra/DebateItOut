from __future__ import annotations

import json
import httpx

HTTP_TIMEOUT = httpx.Timeout(120.0)

async def chat_anthropic(endpoint: dict, model_slug: str, system: str, messages: list[dict]) -> dict:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "x-api-key": endpoint["apiKey"],
        "anthropic-version": "2023-06-01",
    }
    
    # Strip trailing slash from base_url if present
    base_url = endpoint["baseUrl"].rstrip("/")
    # Anthropic's standard chat endpoint is /v1/messages
    # If the base URL already ends with /v1/messages or similar, we should handle it, but standard is just base URL
    if not base_url.endswith("/v1/messages"):
        url = f"{base_url}/v1/messages"
    else:
        url = base_url

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.post(
            url,
            headers=headers,
            json={
                "model": model_slug,
                "max_tokens": 4096,
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

    return {
        "reply": text_block["text"] if text_block else "No response from model.",
        "thinking": thinking_block["thinking"] if thinking_block else None,
    }


async def chat_openai(endpoint: dict, model_slug: str, messages: list[dict]) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {endpoint['apiKey']}",
    }

    base_url = endpoint["baseUrl"].rstrip("/")
    if not base_url.endswith("/chat/completions"):
        if base_url.endswith("/v1"):
            url = f"{base_url}/chat/completions"
        else:
            url = f"{base_url}/v1/chat/completions"
    else:
        url = base_url

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.post(
            url,
            headers=headers,
            json={
                "model": model_slug,
                "messages": messages,
                "max_tokens": 4096,
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

    return {"reply": content or "No response from model.", "thinking": None}


async def dispatch(endpoint: dict, model_slug: str, system: str, messages: list[dict]) -> dict:
    if endpoint["type"] == "anthropic":
        return await chat_anthropic(endpoint, model_slug, system, messages)
    full_messages = [{"role": "system", "content": system}] + messages
    return await chat_openai(endpoint, model_slug, full_messages)
