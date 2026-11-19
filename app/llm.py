import asyncio
import logging
import os

import httpx

log = logging.getLogger("llm")
URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODELS = "openrouter/free"


class LLMError(Exception):
    pass


async def complete(messages):
    """Try each configured free model in order; return (answer, model_used)."""
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    models = [m.strip() for m in os.getenv("OPENROUTER_MODELS", DEFAULT_MODELS).split(",") if m.strip()]
    headers = {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": os.getenv("APP_URL", "http://localhost"),
        "X-Title": "DarGlobal and Wasalt Assistant",
    }
    last = "no models configured"
    async with httpx.AsyncClient(timeout=60) as client:
        for model in models:
            for attempt in range(4):
                try:
                    r = await client.post(URL, headers=headers, json={
                        "model": model, "messages": messages, "temperature": 0.2, "max_tokens": 1500,
                    })
                except httpx.HTTPError as exc:
                    last = f"{model}: {exc}"
                    break
                if r.status_code == 200:
                    try:
                        text = (r.json()["choices"][0]["message"]["content"] or "").strip()
                    except (KeyError, IndexError, ValueError):
                        text = ""
                    if text:
                        return text, model
                    last = f"{model}: empty reply"
                    continue
                last = f"{model}: HTTP {r.status_code}"
                log.warning(last)
                if r.status_code == 429 and attempt == 0:
                    await asyncio.sleep(1.5)
                    continue
                break
    raise LLMError(last)
