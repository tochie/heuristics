"""
FastAPI app for the UX Review Assistant demo.

- Serves the static frontend from ./static
- POST /api/analyze  { "url": "..." }  ->  analysis JSON
- Per-visitor rate limit (default: 1 analysis per 5 minutes) so a public
  link can't drain your Anthropic credits.

Run (dev, with auto-reload):
    uvicorn main:app --reload --port 8000
Or just:
    python3 main.py

The API key stays server-side and is never sent to the browser.
"""

import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from analyzer import analyze

load_dotenv()  # read .env into the environment, like dotenv in Node

# Cheap, current Haiku. Override anytime by setting a MODEL variable on the
# Space (e.g. claude-sonnet-4-6 for top quality) — no redeploy needed.
MODEL = os.environ.get("MODEL", "claude-haiku-4-5")
PORT = int(os.environ.get("PORT", "8000"))
HERE = os.path.dirname(os.path.abspath(__file__))

# Rate limit: one token-spending analysis per client per this many seconds.
# Configurable via the RATE_LIMIT_SECONDS env var.
RATE_LIMIT_SECONDS = int(os.environ.get("RATE_LIMIT_SECONDS", "300"))
_last_request = {}  # client_ip -> monotonic timestamp of last analysis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create one reusable Anthropic client on startup, close it on shutdown."""
    from anthropic import AsyncAnthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    app.state.anthropic = AsyncAnthropic(api_key=api_key) if api_key else None
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY is not set. "
              "Add it to .env (local) or Space secrets (HF) before analyzing.")
    yield
    if app.state.anthropic is not None:
        await app.state.anthropic.close()


app = FastAPI(title="UX Research - Review Assistant", lifespan=lifespan)


class AnalyzeRequest(BaseModel):
    url: str


def client_ip(request: Request) -> str:
    """Real client IP. Behind HF's proxy the socket IP is the proxy, so prefer
    the X-Forwarded-For header (first hop is the original client)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest, request: Request):
    client = app.state.anthropic
    if client is None:
        return JSONResponse(status_code=500,
                            content={"error": "Server is missing ANTHROPIC_API_KEY."})

    # --- rate limit -------------------------------------------------------
    ip = client_ip(request)
    now = time.monotonic()
    last = _last_request.get(ip)
    if last is not None and now - last < RATE_LIMIT_SECONDS:
        wait = int(RATE_LIMIT_SECONDS - (now - last)) + 1
        mins = wait // 60
        human = f"{mins} min {wait % 60}s" if mins else f"{wait}s"
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(wait)},
            content={"error": f"Rate limit: this demo allows one analysis every "
                              f"{RATE_LIMIT_SECONDS // 60} minutes. Please try again in {human}."},
        )
    # Reserve the slot now so concurrent/burst requests are also limited.
    _last_request[ip] = now
    # ---------------------------------------------------------------------

    try:
        result = await analyze(client, MODEL, req.url)
        return result
    except ValueError as e:
        # Fetch/validation failures spend no Claude tokens — release the slot
        # so the visitor can correct the URL and retry immediately.
        _last_request.pop(ip, None)
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # last-resort guard
        _last_request.pop(ip, None)
        return JSONResponse(status_code=500,
                            content={"error": f"Unexpected error: {e}"})


# Serve the frontend. Mounted LAST so /api/* routes take precedence.
# html=True makes "/" serve static/index.html automatically.
app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True),
          name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=PORT, reload=True)
