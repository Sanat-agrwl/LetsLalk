"""
Tests for HindiNumberNormalizer and the number parsing logic.

Run with: pytest tests/ -v
"""
import pytest
from src.processors.hinglish import normalize_hindi_numbers


# ── basic single-word numbers ──────────────────────────────────────────────────
@pytest.mark.parametrize("inp,expected", [
    ("pachas", "50"),
    ("ek", "1"),
    ("bees", "20"),
    ("sau", "100"),
])
def test_single_word(inp, expected):
    assert normalize_hindi_numbers(inp) == expected


# ── compound numbers ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("inp,expected", [
    ("pachas hazaar", "50000"),
    ("paanch lakh", "500000"),
    ("ek crore", "10000000"),
    ("do lakh pachas hazaar", "250000"),
    ("teen sau", "300"),
    ("ek hazaar paanch sau", "1500"),
])
def test_compound(inp, expected):
    assert normalize_hindi_numbers(inp) == expected


# ── critical demo scenario: mid-sentence mixed number ─────────────────────────
@pytest.mark.parametrize("inp,expected", [
    ("I can pay pachas thousand rupees", "I can pay 50000 rupees"),
    ("pachas hazaar ka loan hai mera", "50000 ka loan hai mera"),
    ("settlement offer is pachas hazaar", "settlement offer is 50000"),
    ("main do lakh de sakta hoon", "main 200000 de sakta hoon"),
    ("ek lakh bees hazaar", "120000"),
])
def test_mixed_sentence(inp, expected):
    assert normalize_hindi_numbers(inp) == expected


# ── should NOT mangle plain English numbers ────────────────────────────────────
@pytest.mark.parametrize("inp", [
    "I will pay 50000 rupees",
    "the amount is 42500",
    "hello how are you",
    "haan theek hai",          # fillers only
])
def test_english_passthrough(inp):
    assert normalize_hindi_numbers(inp) == inp


# ── punctuation preservation ───────────────────────────────────────────────────
def test_punctuation():
    assert normalize_hindi_numbers("pachas hazaar.") == "50000."


# ── edge cases ─────────────────────────────────────────────────────────────────
def test_empty():
    assert normalize_hindi_numbers("") == ""

def test_only_fillers():
    assert normalize_hindi_numbers("haan theek hai ji") == "haan theek hai ji"
