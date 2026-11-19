import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import llm
from .rag import Index

log = logging.getLogger("app")
BASE = Path(__file__).parent
DATA_PATH = Path(os.getenv("DATA_PATH", BASE.parent / "data" / "pages.json"))
index = Index()

SYSTEM = (
    "You are an assistant for DarGlobal (Dar Global, property developer) and Wasalt (property platform). "
    "Answer ONLY from the numbered context passages provided with each question. "
    "If the context does not contain the answer, say you could not find it in the website data and suggest "
    "what the user could ask instead. Never invent prices, dates, locations or project names. "
    "Be concise (under 150 words), and use a short list when comparing items."
)
NOT_FOUND = (
    "I couldn't find that in the DarGlobal or Wasalt pages I have. "
    "Try asking about their projects, locations, or services."
)


@asynccontextmanager
async def lifespan(_app):
    index.load(DATA_PATH)
    log.info("Loaded %d chunks", len(index.chunks))
    yield


app = FastAPI(title="DarGlobal and Wasalt Assistant", lifespan=lifespan)


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    history: list[Turn] = Field(default_factory=list, max_length=10)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "chunks": len(index.chunks)}


@app.get("/")
def home():
    return FileResponse(BASE / "static" / "index.html")


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not index.ready:
        raise HTTPException(503, "The knowledge base is empty. Run the scraper and rebuild the image.")

    query = req.message
    if len(query.split()) < 6:  # short follow-up: borrow the previous question for retrieval
        earlier = [t.content for t in req.history if t.role == "user"]
        if earlier:
            query = f"{earlier[-1]} {query}"

    hits = index.search(query, k=6)
    if not hits:
        return {"answer": NOT_FOUND, "sources": [], "model": None}

    context = "\n\n".join(f"[{i}] {h['title']} ({h['url']})\n{h['text']}" for i, h in enumerate(hits, 1))
    messages = (
        [{"role": "system", "content": SYSTEM}]
        + [{"role": t.role, "content": t.content} for t in req.history[-6:]]
        + [{"role": "user", "content": f"Context:\n{context}\n\nQuestion: {req.message}"}]
    )
    try:
        answer, model = await llm.complete(messages)
    except llm.LLMError as exc:
        log.error("LLM failure: %s", exc)
        raise HTTPException(502, "The language model is busy or unavailable. Please try again in a moment.")

    sources, seen = [], set()
    for h in hits[:4]:
        if h["url"] not in seen:
            seen.add(h["url"])
            sources.append({"title": h["title"], "url": h["url"]})
    return {"answer": answer, "sources": sources, "model": model}
