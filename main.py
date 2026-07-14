"""
FastAPI app for the AI-Assisted UX Evaluation System (v2 — the 5-module
staged pipeline from the ../docs spec set).

- Serves the static frontend from ./static
- POST /api/analyze  {url?, page_content?, screenshots?, organization_description?,
                      primary_user_tasks?, known_concerns?}  ->  structured report
- Per-visitor rate limit (default: 1 evaluation per 5 minutes) so a public
  link can't drain Anthropic credits.
- ANALYSIS_ENABLED env kill switch ("false" pauses the demo, no redeploy).

Run (dev):  uvicorn main:app --reload --port 8000   or   python3 main.py
The API key stays server-side and is never sent to the browser.
"""

import asyncio
import base64
import os
import time
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pipeline import EvaluationError, run_evaluation

load_dotenv()

MODEL = os.environ.get("MODEL", "claude-haiku-4-5")
PORT = int(os.environ.get("PORT", "8000"))
HERE = os.path.dirname(os.path.abspath(__file__))
RATE_LIMIT_SECONDS = int(os.environ.get("RATE_LIMIT_SECONDS", "300"))
ANALYSIS_ENABLED = os.environ.get("ANALYSIS_ENABLED", "true").lower() != "false"

MAX_SCREENSHOTS = 3
MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024        # per image, decoded
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

_last_request = {}  # client_ip -> monotonic timestamp of last evaluation


@asynccontextmanager
async def lifespan(app: FastAPI):
    from anthropic import AsyncAnthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    app.state.anthropic = AsyncAnthropic(api_key=api_key) if api_key else None
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY is not set. /api/analyze will 500.")
    yield
    if app.state.anthropic is not None:
        await app.state.anthropic.close()


app = FastAPI(lifespan=lifespan)


class Screenshot(BaseModel):
    media_type: str
    data: str            # base64, no data: prefix


class AnalyzeRequest(BaseModel):
    url: str | None = None
    page_content: str | None = Field(default=None, max_length=40_000)
    organization_description: str | None = Field(default=None, max_length=4_000)
    primary_user_tasks: str | None = Field(default=None, max_length=4_000)
    known_concerns: str | None = Field(default=None, max_length=4_000)
    screenshots: list[Screenshot] | None = None


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _validate_screenshots(shots):
    """Returns the cleaned screenshot list or raises EvaluationError."""
    if not shots:
        return []
    if len(shots) > MAX_SCREENSHOTS:
        raise EvaluationError(f"At most {MAX_SCREENSHOTS} screenshots are accepted.")
    out = []
    for s in shots:
        if s.media_type not in ALLOWED_IMAGE_TYPES:
            raise EvaluationError(f"Unsupported image type: {s.media_type}")
        try:
            raw = base64.b64decode(s.data, validate=True)
        except Exception:
            raise EvaluationError("A screenshot was not valid base64.")
        if len(raw) > MAX_SCREENSHOT_BYTES:
            raise EvaluationError("Each screenshot must be under 4 MB.")
        if len(raw) < 100:
            raise EvaluationError("A screenshot appears to be empty/unreadable.")
        out.append({"media_type": s.media_type, "data": s.data})
    return out


# --- background jobs ---------------------------------------------------
# The staged pipeline takes 1-3 minutes; reverse proxies (HF Spaces) kill
# long-held requests (ERR_CONNECTION_CLOSED). So POST starts a job and
# returns immediately; the browser polls GET /api/analyze/{job_id}.
JOB_TTL_SECONDS = 30 * 60
_jobs = {}  # job_id -> {status, created, report?, error?, ip}


def _prune_jobs():
    cutoff = time.monotonic() - JOB_TTL_SECONDS
    for jid in [j for j, v in _jobs.items() if v["created"] < cutoff]:
        _jobs.pop(jid, None)


async def _run_job(job_id, inputs):
    job = _jobs[job_id]
    try:
        report = await run_evaluation(app.state.anthropic, MODEL, inputs)
        job["report"] = report
        job["status"] = "done"
    except (EvaluationError, ValueError) as e:
        # Validation/fetch failures spend few-to-no tokens — release the slot.
        _last_request.pop(job["ip"], None)
        job["error"] = str(e)
        job["status"] = "error"
    except Exception as e:  # last-resort guard
        _last_request.pop(job["ip"], None)
        job["error"] = f"Unexpected error: {e}"
        job["status"] = "error"


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest, request: Request):
    if not ANALYSIS_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "This demo is paused — live analysis is "
                              "temporarily disabled. Check back later."})

    if app.state.anthropic is None:
        return JSONResponse(status_code=500,
                            content={"error": "Server is missing ANTHROPIC_API_KEY."})

    # Minimum-evidence rule (Doc 1 p.8): at least one observable source.
    if not (req.url or req.page_content or req.screenshots):
        return JSONResponse(
            status_code=400,
            content={"error": "An evaluation cannot be performed without "
                              "observable webpage evidence. Provide a URL, "
                              "screenshots, or page content."})

    # Screenshot validation is cheap and spends no tokens — do it BEFORE
    # consuming the visitor's rate-limit slot.
    try:
        screenshots = _validate_screenshots(req.screenshots)
    except EvaluationError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    # --- rate limit (on STARTING a job; polling is never limited) ---------
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
            content={"error": f"Rate limit: this demo allows one evaluation "
                              f"every {RATE_LIMIT_SECONDS // 60} minutes. "
                              f"Please try again in {human}."})
    _last_request[ip] = now
    # ---------------------------------------------------------------------

    _prune_jobs()
    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"status": "running", "created": now, "ip": ip}
    inputs = {
        "url": req.url,
        "page_content": req.page_content,
        "organization_description": req.organization_description,
        "primary_user_tasks": req.primary_user_tasks,
        "known_concerns": req.known_concerns,
        "screenshots": screenshots,
    }
    asyncio.create_task(_run_job(job_id, inputs))
    return JSONResponse(status_code=202, content={"job_id": job_id})


@app.get("/api/analyze/{job_id}")
async def api_analyze_status(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        return JSONResponse(status_code=404,
                            content={"error": "Unknown or expired job."})
    if job["status"] == "running":
        return {"status": "running"}
    if job["status"] == "error":
        return {"status": "error", "error": job["error"]}
    return {"status": "done", "report": job["report"]}


@app.get("/api/health")
async def health():
    return {"ok": True, "analysis_enabled": ANALYSIS_ENABLED, "model": MODEL}


app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True),
          name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
