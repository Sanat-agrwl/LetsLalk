"""
SarvamTTSService — pipecat TTSService wrapping Sarvam AI's bulbul:v1 model.

Uses a single hi-IN voice throughout the conversation (Indian English accent
handles both Hindi and English naturally).  This eliminates the 2-3 s latency
spike that occurs when swapping between two separate STT/TTS providers on a
language switch, because there is no swap — one model, one voice, always.

Sentence-level chunking is handled by pipecat's TTSService base class;
run_tts() is called once per sentence so first audio plays while the LLM is
still generating the rest of the response.
"""
import base64
import io
import wave
from typing import AsyncGenerator

import aiohttp
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService

import os

_SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
_SAMPLE_RATE = 16_000
_SARVAM_MODEL = os.getenv("SARVAM_MODEL", "bulbul:v1")

# Valid Sarvam AI speakers (as of April 2026)
SARVAM_SPEAKERS = [
    "anushka", "abhilash", "manisha", "vidya", "arya", "karun", "hitesh",
    "aditya", "ritu", "priya", "neha", "rahul", "pooja", "rohan", "simran",
    "kavya", "amit", "dev", "ishita", "shreya", "ratan", "varun", "manan",
    "sumit", "roopa", "kabir", "aayan", "shubh", "ashutosh", "advait",
    "anand", "tanya", "tarun", "sunny", "mani", "gokul", "vijay", "shruti",
    "suhani", "mohit", "kavitha", "rehan", "soham", "rupali",
]


def _wav_bytes_to_pcm(wav_data: bytes) -> tuple[bytes, int]:
    """Strip WAV header and return (raw 16-bit PCM bytes, actual sample rate)."""
    with wave.open(io.BytesIO(wav_data)) as wf:
        return wf.readframes(wf.getnframes()), wf.getframerate()


class SarvamTTSService(TTSService):
    def __init__(
        self,
        api_key: str,
        speaker: str = "rohan",
        language_code: str = "hi-IN",
        **kwargs,
    ):
        super().__init__(
            settings=TTSSettings(model=None, voice=speaker, language=None),
            **kwargs,
        )
        self._api_key = api_key
        self._speaker = speaker
        self._language_code = language_code
        self._session: aiohttp.ClientSession | None = None

    def can_generate_metrics(self) -> bool:
        return True

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def cleanup(self):
        if self._session and not self._session.closed:
            await self._session.close()
        await super().cleanup()

    async def run_tts(self, text: str, context_id: str = "") -> AsyncGenerator[Frame, None]:
        logger.debug(f"[TTS] Sarvam → {text!r}")

        await self.start_ttfb_metrics()

        try:
            session = await self._get_session()
            async with session.post(
                _SARVAM_TTS_URL,
                headers={"api-subscription-key": self._api_key},
                json={
                    "inputs": [text],
                    "target_language_code": self._language_code,
                    "speaker": self._speaker,
                    "model": _SARVAM_MODEL,
                    "speech_sample_rate": _SAMPLE_RATE,
                    "enable_preprocessing": True,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"Sarvam TTS {resp.status}: {body}")
                    yield ErrorFrame(f"Sarvam TTS HTTP {resp.status}")
                    return

                data = await resp.json()
                audio_b64: str = data["audios"][0]
                wav_bytes = base64.b64decode(audio_b64)
                pcm_bytes, actual_sr = _wav_bytes_to_pcm(wav_bytes)
                if actual_sr != _SAMPLE_RATE:
                    logger.warning(f"[TTS] Sarvam returned {actual_sr}Hz, declared {_SAMPLE_RATE}Hz — using actual")

        except Exception as exc:
            logger.exception(f"Sarvam TTS error: {exc}")
            yield ErrorFrame(str(exc))
            return

        await self.stop_ttfb_metrics()

        chunk_size = 4_096
        for offset in range(0, len(pcm_bytes), chunk_size):
            yield TTSAudioRawFrame(
                audio=pcm_bytes[offset : offset + chunk_size],
                sample_rate=actual_sr,
                num_channels=1,
                context_id=context_id,
            )
