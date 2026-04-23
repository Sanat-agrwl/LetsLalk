"""
ConversationRecorder — two in-pipeline taps sharing one recording session.

TranscriptTap  — place between STT and normalizer; captures user transcripts.
AudioTap       — place between TTS and transport.output(); captures agent audio.

Files written to /app/recordings/ (mounted to ./recordings/ on the host):
  session_YYYYMMDD_HHMMSS_agent.wav   — agent TTS audio (16kHz, 16-bit, mono)
  session_YYYYMMDD_HHMMSS_events.jsonl — timestamped event log
"""
import json
import time
import wave
from datetime import datetime
from pathlib import Path

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

_RECORDINGS_DIR = Path("/app/recordings")
_SAMPLE_RATE = 16_000


class RecordingSession:
    """Shared state between TranscriptTap and AudioTap for one call."""

    def __init__(self):
        _RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._audio_path = _RECORDINGS_DIR / f"session_{ts}_agent.wav"
        self._log_path = _RECORDINGS_DIR / f"session_{ts}_events.jsonl"
        self._wav: wave.Wave_write | None = None
        self._log_fh = None
        self._t0 = time.time()
        self._turn = 0
        logger.info(f"[Recorder] New session → {self._audio_path.name}")

    # ── internal ───────────────────────────────────────────────────────────────

    def _open_wav(self):
        wf = wave.open(str(self._audio_path), "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)
        self._wav = wf

    def _open_log(self):
        self._log_fh = open(self._log_path, "w", encoding="utf-8")

    # ── public API ─────────────────────────────────────────────────────────────

    def log_event(self, event: str, **data):
        if self._log_fh is None:
            self._open_log()
        entry = {"t": round(time.time() - self._t0, 3), "event": event, **data}
        self._log_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._log_fh.flush()

    def write_audio(self, audio: bytes):
        if self._wav is None:
            self._open_wav()
        self._wav.writeframes(audio)

    def close(self):
        if self._wav:
            self._wav.close()
            self._wav = None
            logger.info(f"[Recorder] Agent audio saved → {self._audio_path.name}")
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None
            logger.info(f"[Recorder] Event log saved → {self._log_path.name}")

    def next_turn(self) -> int:
        self._turn += 1
        return self._turn


class TranscriptTap(FrameProcessor):
    """Sits between STT and normalizer. Logs user transcripts + speaking events."""

    def __init__(self, session: RecordingSession, **kwargs):
        super().__init__(**kwargs)
        self._s = session

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            turn = self._s.next_turn()
            self._s.log_event("user_transcript", turn=turn, text=frame.text)
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._s.log_event("user_started_speaking")
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._s.log_event("user_stopped_speaking")

        await self.push_frame(frame, direction)


class AudioTap(FrameProcessor):
    """Sits between TTS and transport.output(). Records agent audio to WAV."""

    def __init__(self, session: RecordingSession, **kwargs):
        super().__init__(**kwargs)
        self._s = session

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TTSAudioRawFrame):
            self._s.write_audio(frame.audio)
        elif isinstance(frame, (EndFrame, CancelFrame)):
            self._s.close()

        await self.push_frame(frame, direction)
