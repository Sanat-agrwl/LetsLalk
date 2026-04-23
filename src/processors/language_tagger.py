"""
LanguageTagger — deterministic Hindi/English detector.

Prepends [HINDI] or [ENGLISH] to TranscriptionFrame text so the LLM doesn't
have to infer language from conversation history (which was unreliable).
"""
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

_SUBSTANTIVE_HINDI_WORDS = {
    # negation / refusal
    "nahi", "nahin", "mat", "nah",
    # verbs — imperatives and conjugations
    "karo", "karna", "karta", "karti", "karein", "kar",
    "dena", "dedo", "dedena", "dedo", "de",
    "suno", "suniye", "sunlo",
    "bolo", "bolho", "bolta", "bolti", "bolein", "bol",
    "batao", "bata", "batana", "bataye",
    "aao", "aana", "aate", "aati",
    "jao", "jana", "jaate", "jaati",
    "lo", "lena", "lelo", "lete",
    "samajh", "samajhta", "samajhti", "samajhein", "samjhe",
    "chahiye", "chahta", "chahti",
    "milega", "milegi", "mila", "milne",
    "hoga", "hogi", "hua", "hui",
    "tha", "thi", "the",
    # money / amounts
    "paisa", "paise", "rupaye", "rupaya", "rupee",
    "hazaar", "lakh", "crore",
    # common nouns
    "baat", "bhai", "mushkil", "dikkat", "problem",
    # quantity / degree
    "zyada", "kam", "thoda", "bohot", "bahut", "bilkul",
    # question words
    "kyun", "kyu", "kya", "kaise", "kab", "kidhar", "kaun",
    # pronouns
    "mujhe", "mera", "meri", "mere",
    "humko", "hum", "hamara", "hamari",
    "tum", "tumhara", "tumhari",
    "aapka", "aapki", "aapke",
    # conjunctions / discourse
    "lekin", "aur", "toh", "phir", "matlab",
    "abhi", "baad", "pehle",
    "kyunki", "isliye", "magar", "alawa",
    # copula — present/future (absent from original list, extremely common)
    "hai", "hain",
    # high-frequency particles and pronouns missing from original list
    "kuch", "bhi", "koi", "sab", "sirf",
    "aap", "woh", "vo", "yeh", "jo",
    # postpositions / locatives
    "mein", "se", "par", "tak", "liye", "saath", "baad", "pehle",
}

_FILLER_ONLY = {"haan", "ha", "theek", "ji", "hmm", "achha", "okay", "ok", "arre"}


def _detect_hindi(text: str) -> bool:
    """Return True if text contains ≥1 Devanagari char OR ≥2 substantive Romanized Hindi words."""
    devanagari_count = sum(1 for c in text if 'ऀ' <= c <= 'ॿ')
    if devanagari_count >= 1:
        return True

    words = set(text.lower().split())
    substantive_hits = words & _SUBSTANTIVE_HINDI_WORDS
    return len(substantive_hits) >= 2


class LanguageTagger(FrameProcessor):
    """Tags TranscriptionFrame text with [HINDI] or [ENGLISH] prefix."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            tag = "[HINDI]" if _detect_hindi(frame.text) else "[ENGLISH]"
            tagged = TranscriptionFrame(
                text=f"{tag} {frame.text}",
                user_id=frame.user_id,
                timestamp=frame.timestamp,
            )
            await self.push_frame(tagged, direction)
        else:
            await self.push_frame(frame, direction)
