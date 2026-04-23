"""
Baseline pipeline — Deepgram STT + OpenAI TTS + GPT-4o-mini.

No Hinglish-specific handling:
  • No Hindi number normalization → "pachas hazaar" reaches LLM as-is
  • No language stability filter → single Hindi word can trigger a "switch"
  • OpenAI TTS doesn't natively understand Hinglish well

Used for measurement comparison against the custom pipeline.
Run with: python -m baseline.pipeline
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from loguru import logger

load_dotenv()

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from src.agent.prompts import SYSTEM_PROMPT  # same prompt, fair comparison

BASELINE_SYSTEM = SYSTEM_PROMPT  # identical prompt; difference is only the STT/TTS layer


async def run_baseline(websocket):
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True,
        ),
    )

    stt = DeepgramSTTService(
        api_key=os.environ["DEEPGRAM_API_KEY"],
        language="hi",  # Deepgram's Hinglish model
    )

    llm = OpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        model="gpt-4o-mini",
    )

    tts = OpenAITTSService(
        api_key=os.environ["OPENAI_API_KEY"],
        voice="shimmer",
        model="tts-1",
    )

    messages = [{"role": "system", "content": BASELINE_SYSTEM}]
    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            # ← NO HindiNumberNormalizer here (that's the variable under test)
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(allow_interruptions=True, enable_metrics=True),
    )

    await PipelineRunner().run(task)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Baseline pipeline starting …")
    yield


app = FastAPI(title="Baseline Pipeline", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    return (Path(__file__).parent.parent / "src/static/index.html").read_text()


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        await run_baseline(websocket)
    except Exception as e:
        logger.exception(e)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("baseline.pipeline:app", host="0.0.0.0", port=8766, reload=False)
