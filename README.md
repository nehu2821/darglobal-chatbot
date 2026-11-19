# DarGlobal and Wasalt assistant

A retrieval-augmented chatbot that answers questions about DarGlobal and Wasalt using data scraped from their public websites.

## How it works

1. `scraper/scrape.py` crawls both sites (robots.txt respected, rate limited) and writes `data/pages.json`. It reads page text, JSON-LD, and Next.js `__NEXT_DATA__`, and can ingest JSON feeds.
2. At startup the app splits pages into ~170-word chunks and indexes them with BM25 (`rank-bm25`). No embedding model or vector DB is needed, so the image stays small.
3. Each question retrieves the top chunks, which go to a free OpenRouter model together with a system prompt that restricts it to the supplied context. Answers include source links.
4. If the first model is rate limited or fails, the app tries the next one in `OPENROUTER_MODELS`.

Stack: FastAPI, rank-bm25, httpx, plain HTML/JS front end, Docker.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-scraper.txt && playwright install chromium   # scraper only
python scraper/scrape.py            # add --js for JavaScript-rendered pages

pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-or-...
uvicorn app.main:app --reload --port 7860
```

Open http://localhost:7860.

## Docker

```bash
docker build -t darglobal-bot .
docker run -p 7860:7860 -e OPENROUTER_API_KEY=sk-or-... darglobal-bot
```

`data/pages.json` is baked into the image, so scrape first and commit it.

## Deploy on Hugging Face Spaces (free)

1. Create a Space, choose SDK **Docker**.
2. Add this block to the very top of README.md in the Space repo:
   ```
   ---
   title: DarGlobal Assistant
   sdk: docker
   app_port: 7860
   ---
   ```
3. Space Settings, Variables and secrets: add secret `OPENROUTER_API_KEY`.
4. Push the repo to the Space. The public URL is `https://<user>-<space>.hf.space`.

## Configuration

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | Required. Set as a secret, never commit it. |
| `OPENROUTER_MODELS` | Comma-separated free model ids, tried in order. |
| `DATA_PATH` | Override the data file location. |
| `PORT` | Server port (default 7860). |

## Limitations

- Keyword (BM25) retrieval can miss paraphrased questions; embeddings would improve recall.
- Data is a snapshot from scrape time, so re-run the scraper and redeploy to refresh it.
- Free models have rate limits and can change or disappear; the fallback list reduces but does not remove this.
- Answers are only as good as the pages scraped, and listing-heavy pages may be partly covered.
