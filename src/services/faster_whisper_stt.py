"""
FasterWhisperSTTService — pipecat FrameProcessor wrapping faster-whisper.

Collects audio while the user is speaking (VAD-gated), then transcribes
the full utterance after UserStoppedSpeakingFrame arrives.  The initial_prompt
primes Whisper for Hinglish and common loan-call vocabulary so it handles
code-switched speech without flipping languages mid-utterance.
"""
import asyncio
import time

import numpy as np
from loguru import logger
from pipecat.frames.frames import (
    AudioRawFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    StartFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Keep this very short — tiny model hallucinates long prompts back as speech.
_INITIAL_PROMPT = "haan, nahi, pachas hazaar, rupaye, theek hai."

_INPUT_AUDIO_SAMPLE_RATE = 16_000  # pipecat default pipeline rate

# Unicode ranges for scripts that indicate hallucination (not Hindi or English)
_HALLUCINATION_RANGES = [
    (0x1100, 0x11FF),   # Korean Hangul Jamo
    (0xAC00, 0xD7AF),   # Korean Hangul Syllables
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3000, 0x303F),   # CJK Symbols
    (0x0600, 0x06FF),   # Arabic
    (0x0590, 0x05FF),   # Hebrew
    (0x0400, 0x04FF),   # Cyrillic
]

# Substrings that only appear when the model hallucinates the initial_prompt or
# the system context leaks through (in any case, not real user speech).
_HALLUCINATED_PHRASES = [
    "loan amount is fifty",
    "the borrower may switch",
    "hindi and english mid-sentence",
    "pachas hazaar rupaye",
    "common hindi words",
    "this is a hinglish",
    "fifty thousand rupees",
    "mid-sentence",
]


def _is_hallucination(text: str) -> bool:
    """Return True if this transcription looks like a Whisper hallucination."""
    if not text or len(text.strip()) < 2:
        return True

    # Punctuation/symbol-only output (e.g. "। । । । ।") — no real words
    if not any(c.isalpha() or c.isdigit() for c in text):
        logger.warning(f"[STT] Hallucination (no word content): {text!r}")
        return True

    text_lower = text.lower()

    # Known prompt-bleed phrases
    for phrase in _HALLUCINATED_PHRASES:
        if phrase in text_lower:
            logger.warning(f"[STT] Hallucination (prompt bleed): {text!r}")
            return True

    # Non-Hindi/non-Latin scripts
    for ch in text:
        cp = ord(ch)
        for lo, hi in _HALLUCINATION_RANGES:
            if lo <= cp <= hi:
                logger.warning(f"[STT] Hallucination (foreign script U+{cp:04X}): {text!r}")
                return True

    return False


class FasterWhisperSTTService(FrameProcessor):
    """
    Open-source STT using faster-whisper.  Satisfies the assignment's
    requirement for at least one open-source pipeline component.
    """

    def __init__(self, model_size: str = "small", **kwargs):
        super().__init__(**kwargs)
        self._model_size = model_size
        self._model = None          # loaded lazily on StartFrame
        self._audio_chunks: list[bytes] = []
        self._recording = False

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def _load_model(self):
        if self._model is not None:
            return
        from faster_whisper import WhisperModel
        logger.info(f"Loading faster-whisper model '{self._model_size}' …")
        self._model = WhisperModel(
            self._model_size,
            device="auto",          # CUDA if available, else CPU
            compute_type="int8",    # quantised — 2-4× faster, tiny accuracy loss
        )
        logger.info("faster-whisper ready.")

    # ── frame routing ──────────────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await asyncio.get_event_loop().run_in_executor(None, self._load_model)
            await self.push_frame(frame, direction)

        elif isinstance(frame, UserStartedSpeakingFrame):
            self._audio_chunks = []
            self._recording = True
            await self.push_frame(frame, direction)

        elif isinstance(frame, (AudioRawFrame, InputAudioRawFrame)) and self._recording:
            self._audio_chunks.append(frame.audio)
            # Cap at 8 s (256 KB) to avoid processing long echo-bleed buffers.
            if sum(len(c) for c in self._audio_chunks) > 256_000:
                logger.warning("[STT] Audio buffer exceeded 8 s — resetting (possible echo)")
                self._audio_chunks = []
            # Do NOT forward raw audio — it's consumed here.

        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._recording = False
            if self._audio_chunks:
                try:
                    text = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, self._transcribe),
                        timeout=20.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("[STT] Whisper timed out (>20 s) — dropping utterance")
                    text = None
                if text and not _is_hallucination(text):
                    logger.debug(f"[STT] {text!r}")
                    await self.push_frame(
                        TranscriptionFrame(
                            text=text,
                            user_id="user",
                            timestamp=str(time.time()),
                        ),
                        direction,
                    )
                elif text:
                    logger.debug(f"[STT] Dropped hallucination: {text!r}")
            self._audio_chunks = []
            await self.push_frame(frame, direction)

        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ── transcription ──────────────────────────────────────────────────────────

    def _transcribe(self) -> str:
        """Run faster-whisper synchronously (called inside executor)."""
        audio_bytes = b"".join(self._audio_chunks)
        audio_f32 = (
            np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32_768.0
        )

        segments, info = self._model.transcribe(
            audio_f32,
            language="en",              # force Roman output; prevents danda hallucinations for Hinglish
            task="transcribe",
            initial_prompt=_INITIAL_PROMPT,
            vad_filter=True,            # skip silent pads within the utterance
            vad_parameters={"min_silence_duration_ms": 300},
        )

        return " ".join(s.text.strip() for s in segments).strip()
