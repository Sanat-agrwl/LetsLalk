"""
Pipecat pipeline for the Hinglish debt collection agent.

Flow:
  transport.input()
    → FasterWhisperSTTService (open-source, Hinglish-primed, VAD-gated)
    → TranscriptTap           (recorder: logs user speech + timing)
    → HindiNumberNormalizer   ("pachas hazaar" → "50000")
    → OpenAILLMContextAggregator.user()
    → OpenAILLMService        (fact-grounded prompt, auto lang-switch)
    → SarvamTTSService        (bulbul:v3 hi-IN — single voice, zero switch latency)
    → AudioTap                (recorder: saves agent audio to WAV)
    → transport.output()
    → OpenAILLMContextAggregator.assistant()
"""
import os

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.openai.llm import OpenAILLMService

from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from src.agent.prompts import SYSTEM_PROMPT
from src.processors.hinglish import HindiNumberNormalizer
from src.processors.language_tagger import LanguageTagger
from src.processors.recorder import AudioTap, RecordingSession, TranscriptTap
from src.serializer import RawPCMSerializer
from src.services.faster_whisper_stt import FasterWhisperSTTService
from src.services.sarvam_tts import SarvamTTSService


async def run_pipeline(websocket):
    """Build and run one pipeline instance per WebSocket connection."""

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_out_sample_rate=16_000,
            add_wav_header=False,
            serializer=RawPCMSerializer(),
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    stop_secs=0.3,
                    min_volume=0.6,
                )
            ),
            vad_audio_passthrough=True,
        ),
    )

    stt = FasterWhisperSTTService(
        model_size=os.getenv("WHISPER_MODEL", "small"),
    )

    language_tagger = LanguageTagger()
    normalizer = HindiNumberNormalizer()

    llm = OpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        model="gpt-4o-mini",
        params=OpenAILLMService.InputParams(max_tokens=200),
    )

    tts = SarvamTTSService(
        api_key=os.environ["SARVAM_API_KEY"],
        speaker=os.getenv("SARVAM_SPEAKER", "rohan"),
        language_code="hi-IN",
    )

    _OPENING_LINE = (
        "Hello, am I speaking with the account holder for the FinServ personal loan of ₹50,000?"
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    rec = RecordingSession()

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            TranscriptTap(rec),
            language_tagger,
            normalizer,
            context_aggregator.user(),
            llm,
            tts,
            AudioTap(rec),
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_connected(t, client):
        logger.info("Browser connected — playing opening greeting via TTS.")
        await task.queue_frames([TTSSpeakFrame(_OPENING_LINE)])

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(_t, _client):
        logger.info("Browser disconnected — cancelling pipeline.")
        await task.cancel()

    await PipelineRunner().run(task)
