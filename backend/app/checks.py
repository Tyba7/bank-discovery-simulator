import re
import unicodedata

MAX_MESSAGE_CHARS = 1000
_ZERO_WIDTH = re.compile("[\u200b-\u200f\u2060\ufeff]")
_MIXED_SCRIPT = re.compile(r"[A-Za-z][\u0370-\u03ff\u0400-\u04ff]|[\u0370-\u03ff\u0400-\u04ff][A-Za-z]")
_INJECTION = re.compile(
    r"ignore (?:all |any |your |the |my )*(?:previous |prior |above )*(?:instructions|rules|prompt)"
    r"|<\|im_(?:start|end)\|>|\[/?INST\]|<</?SYS>>"
    r"|\b(?:system|developer) (?:prompt|message|override|mode)\b|\bdebug mode\b"
    r"|\b(?:hidden|secret)[ _](?:needs?|information|info|profile|instructions?|fields?)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORDS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
_NUMBER_WORDS = {w: float(i) for i, w in enumerate(_WORDS.split())} | {"thirty": 30.0, "forty": 40.0, "fifty": 50.0}


def clean(text: str) -> str:
    return _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", text)).strip()


def check_input(raw: str) -> tuple[str, str | None]:
    text = clean(raw)
    if not text:
        return text, "empty"
    if len(text) > MAX_MESSAGE_CHARS:
        return text, "too_long"
    if _INJECTION.search(text) or _MIXED_SCRIPT.search(text):
        return text, "injection"
    return text, None


def fence(text: str) -> str:
    return text.replace("<", "").replace(">", "")


def numbers(text: str, words: bool = False) -> set[float]:
    found = {float(m.replace(",", "")) for m in _NUMBER.findall(text)}
    if words:
        found |= {_NUMBER_WORDS[w] for w in re.findall(r"[a-z]+", text.lower()) if w in _NUMBER_WORDS}
    return found


def check_numbers(reply: str, allowed_text: str, locked_text: str) -> tuple[bool, bool]:
    # Numbers are compared as numbers, not substrings. Number words count only on the allowed side,
    # so "one of the hospitals" in a reply is never read as a number.
    allowed = numbers(allowed_text, words=True)
    locked = numbers(locked_text, words=True) - allowed
    said = numbers(reply)
    return bool(said & locked), bool(said - allowed - locked)
