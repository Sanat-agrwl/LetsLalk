"""
RawPCMSerializer — sends/receives raw 16-bit PCM bytes over WebSocket.

The browser JS already speaks this format:
  - Out: raw bytes → browser decodes as Int16Array, plays via AudioContext
  - In:  browser sends raw bytes → pipecat wraps in InputAudioRawFrame
"""
import struct
from typing import Optional

import numpy as np
from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame, StartFrame
from pipecat.serializers.base_serializer import FrameSerializer

_SAMPLE_RATE = 16_000
_NUM_CHANNELS = 1


class RawPCMSerializer(FrameSerializer):
    """Minimal serializer: audio frames ↔ raw PCM bytes. No framing overhead."""

    async def setup(self, frame: StartFrame):
        pass

    async def serialize(self, frame: Frame) -> bytes | None:
        if isinstance(frame, OutputAudioRawFrame):
            return bytes(frame.audio)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, bytes) and len(data) > 0:
            return InputAudioRawFrame(
                audio=data,
                sample_rate=_SAMPLE_RATE,
                num_channels=_NUM_CHANNELS,
            )
        return None
