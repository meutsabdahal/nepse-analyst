from langdetect import detect, LangDetectException

_DEVANAGARI_RANGE = range(0x0900, 0x097F + 1)

def _contains_devanagari(text: str) -> bool:
    return any(ord(c) in _DEVANAGARI_RANGE for c in text)

def detect_language(text: str) -> str:

    if not text or not text.strip():
        return "en"
    
    has_devanagari = _contains_devanagari(text)
    
    try:
        detected = detect(text)
    except LangDetectException:
        return "ne" if has_devanagari else "en"
    
    # langdetect often returns 'hi' for Nepali text (both use Devanagari)
    # Override: if Devanagari characters are present, treat as Nepali
    if has_devanagari:
        return "mixed" if detected == "en" else "ne"
    
    if detected == "en":
        return "en"
    
    # Mixed: significant Devanagari words mixed with English (common in NEPSE news)
    return "en"   # default for non-Devanagari non-English → treat as English

def is_nepali(text: str) -> bool:
    return detect_language(text) == "ne"

def is_mixed(text: str) -> bool:
    return detect_language(text) == "mixed"