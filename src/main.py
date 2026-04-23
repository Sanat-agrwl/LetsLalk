"""
FastAPI server — serves the web UI and the WebSocket endpoint.

One command starts everything:
  uvicorn src.main:app --host 0.0.0.0 --port 8765
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

load_dotenv()

from src.pipeline import run_pipeline  # noqa: E402  (after env load)


async def _prewarm_sarvam():
    """Hit Sarvam with a short phrase so their model is warm for the first real call."""
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.sarvam.ai/text-to-speech",
                headers={"api-subscription-key": api_key},
                json={
                    "inputs": ["हाँ।"],
                    "target_language_code": "hi-IN",
                    "speaker": os.getenv("SARVAM_SPEAKER", "rohan"),
                    "model": os.getenv("SARVAM_MODEL", "bulbul:v1"),
                    "speech_sample_rate": 16000,
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    logger.info("Sarvam pre-warm complete.")
                else:
                    body = await resp.text()
                    logger.warning(f"Sarvam pre-warm got HTTP {resp.status}: {body[:200]}")
    except Exception as exc:
        logger.warning(f"Sarvam pre-warm failed (non-fatal): {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FinServ Hinglish Collection Agent starting …")
    await _prewarm_sarvam()
    yield
    logger.info("Shutting down.")


app = FastAPI(title="FinServ Hinglish Voice Agent", lifespan=lifespan)

_STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (_STATIC / "index.html").read_text()


_RECORDINGS = Path("/app/recordings")


@app.get("/recordings")
async def list_recordings():
    _RECORDINGS.mkdir(parents=True, exist_ok=True)
    files = sorted(_RECORDINGS.glob("session_*"), reverse=True)
    return {"recordings": [f.name for f in files]}


@app.get("/recordings/{filename}")
async def download_recording(filename: str):
    path = _RECORDINGS / filename
    if not path.exists() or not path.is_file() or ".." in filename:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(str(path), filename=filename)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info(f"WebSocket connected from {websocket.client}")
    try:
        await run_pipeline(websocket)
    except Exception as exc:
        logger.exception(f"Pipeline error: {exc}")
    finally:
        logger.info("WebSocket closed.")
