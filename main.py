"""
FastAPI app for the UX Review Assistant demo.

- Serves the static frontend from ./static
- POST /api/analyze  { "url": "..." }  ->  analysis JSON

Run (dev, with auto-reload):
    uvicorn main:app --reload --port 8000
Or just:
    python3 main.py

The API key stays server-side and is never sent to the browser.
"""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from analyzer import analyze

load_dotenv()  # read .env into the environment, like dotenv in Node

MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")
PORT = int(os.environ.get("PORT", "8000"))
HERE = os.path.dirname(os.path.abspath(__file__))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create one reusable Anthropic client on startup, close it on shutdown."""
    from anthropic import AsyncAnthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    app.state.anthropic = AsyncAnthropic(api_key=api_key) if api_key else None
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY is not set. "
              "Add it to .env before analyzing.")
    yield
    if app.state.anthropic is not None:
        await app.state.anthropic.close()


app = FastAPI(title="UX Review Assistant", lifespan=lifespan)


class AnalyzeRequest(BaseModel):
    url: str


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest):
    client = app.state.anthropic
    if client is None:
        return JSONResponse(status_code=500,
                            content={"error": "Server is missing ANTHROPIC_API_KEY."})
    try:
        result = await analyze(client, MODEL, req.url)
        return result
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # last-resort guard
        return JSONResponse(status_code=500,
                            content={"error": f"Unexpected error: {e}"})


# Serve the frontend. Mounted LAST so /api/* routes take precedence.
# html=True makes "/" serve static/index.html automatically.
app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True),
          name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=PORT, reload=True)
