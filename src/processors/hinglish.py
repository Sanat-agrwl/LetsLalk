"""
HindiNumberNormalizer: converts Hindi/Hinglish number words to digits before the LLM sees them.

Examples:
  "pachas hazaar" → "50000"
  "paanch lakh" → "500000"
  "I can pay pachas thousand rupees" → "I can pay 50000 rupees"
  "do lakh pachas hazaar" → "250000"
"""
import re

try:
    from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
    from pipecat.frames.frames import Frame, TranscriptionFrame
    _PIPECAT_AVAILABLE = True
except ImportError:
    _PIPECAT_AVAILABLE = False

# ── vocabulary ────────────────────────────────────────────────────────────────

_ONES: dict[str, int] = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5,
    "chhe": 6, "chhah": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "barah": 12, "terah": 13, "chaudah": 14, "pandrah": 15,
    "solah": 16, "satrah": 17, "atharah": 18, "unnis": 19,
    "bees": 20, "ikkees": 21, "baaees": 22, "teis": 23, "chaubees": 24,
    "pachees": 25, "chhabbees": 26, "sattaees": 27, "atthaees": 28, "untees": 29,
    "tees": 30, "ikattees": 31, "battees": 32, "taintees": 33, "chautees": 34,
    "paintees": 35, "chhattees": 36, "saintees": 37, "artees": 38, "untaalees": 39,
    "chalis": 40, "ikhtaalees": 41, "bayalees": 42, "taintaalees": 43,
    "chawaalees": 44, "paintaalees": 45, "chhiyaalees": 46, "saintaalees": 47,
    "artaalees": 48, "unchaas": 49,
    "pachas": 50, "pachpan": 55, "saath": 60, "sattar": 70, "assi": 80,
    "nabbe": 90, "nabbey": 90,
}

_MULTIPLIERS: dict[str, int] = {
    "sau": 100,
    "hazaar": 1_000, "hajar": 1_000, "hazar": 1_000,
    "lakh": 100_000, "lac": 100_000, "lakhs": 100_000,
    "crore": 10_000_000, "karod": 10_000_000, "crores": 10_000_000,
    # English multipliers that follow Hindi ones (e.g. "pachas thousand")
    "thousand": 1_000,
    "million": 1_000_000,
}

# Fillers that should not shift language detection
HINDI_FILLERS = {
    "haan", "ha", "ji", "hnji", "acha", "theek", "theek hai", "bas",
    "yaar", "bhai", "arre", "areh", "hmm", "um", "uh", "oh", "ah", "matlab",
}


# ── number parser ─────────────────────────────────────────────────────────────

def _parse_number_at(tokens: list[str], start: int) -> tuple[int | None, int]:
    """
    Greedily parse a Hindi/mixed number starting at tokens[start].
    Returns (value, tokens_consumed) or (None, 0) if no number found.
    """
    i = start
    total = 0
    current = 0
    consumed = 0

    while i < len(tokens) and i < start + 10:
        tok = tokens[i].lower().rstrip(".,;!")

        if tok in _ONES:
            current = _ONES[tok]
            consumed = i - start + 1
            i += 1

        elif tok in _MULTIPLIERS:
            mult = _MULTIPLIERS[tok]
            # Cross-lingual multipliers (thousand/million) only fire when a
            # Hindi ones-word preceded them; prevents bare "thousand" converting
            # when the leading word is English (e.g. "fifty thousand").
            if tok in ("thousand", "million") and current == 0 and total == 0:
                break
            if mult == 100:
                current = (current or 1) * 100
            else:
                total += (current or 1) * mult
                current = 0
            consumed = i - start + 1
            i += 1

        else:
            break

    value = total + current
    return (value, consumed) if value > 0 else (None, 0)


def normalize_hindi_numbers(text: str) -> str:
    """Replace Hindi/Hinglish number words with their digit equivalents."""
    tokens = text.split()
    result: list[str] = []
    i = 0

    while i < len(tokens):
        value, consumed = _parse_number_at(tokens, i)
        if value is not None and consumed > 0:
            # Preserve trailing punctuation from the last consumed token
            last = tokens[i + consumed - 1]
            suffix = re.search(r"[.,;!?]+$", last)
            result.append(str(value) + (suffix.group() if suffix else ""))
            i += consumed
        else:
            result.append(tokens[i])
            i += 1

    return " ".join(result)


# ── pipecat processor (only defined when pipecat is present) ──────────────────

if _PIPECAT_AVAILABLE:

    class HindiNumberNormalizer(FrameProcessor):
        """
        Sits between STT and the LLM context aggregator.
        Rewrites transcripts so "pachas hazaar" becomes "50000" before the LLM
        processes them — the primary defence against numeric fact corruption.
        """

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)

            if isinstance(frame, TranscriptionFrame):
                normalized = normalize_hindi_numbers(frame.text)
                if normalized != frame.text:
                    frame = TranscriptionFrame(
                        text=normalized,
                        user_id=frame.user_id,
                        timestamp=frame.timestamp,
                        language=getattr(frame, "language", None),
                    )

            await self.push_frame(frame, direction)
