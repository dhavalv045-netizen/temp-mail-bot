"""
OTP extraction.

Looks for 4-8 digit codes near common "this is a verification code" style
phrases. Falls back to a bare digit-group scan if no phrase match is found,
but only returns a code if it's actually confident one was found — never
fabricates a result.
"""

import re

_KEYWORDS = re.compile(
    r"(verification code|one[- ]?time password|\botp\b|security code|"
    r"confirmation code|login code|access code|auth code)",
    re.IGNORECASE,
)

# 4, 5, 6, or 8 digit codes (optionally with spaces/dashes like "123 456")
_CODE_NEAR_KEYWORD = re.compile(r"\b(\d[\d\s-]{2,10}\d)\b")
_BARE_CODE = re.compile(r"\b\d{4,8}\b")


def _clean(code: str) -> str:
    return re.sub(r"[\s-]", "", code)


def extract_otp(text: str) -> str | None:
    """
    Returns the most likely OTP code found in `text`, or None if nothing
    confident was found. `text` should be the plain-text version of an
    email body (strip HTML first).
    """
    if not text:
        return None

    for match in _KEYWORDS.finditer(text):
        # look in a window after the keyword (most services put the code
        # right after the phrase) and a smaller window before it
        window = text[match.end(): match.end() + 60]
        code_match = _CODE_NEAR_KEYWORD.search(window)
        if code_match:
            cleaned = _clean(code_match.group(1))
            if 4 <= len(cleaned) <= 8:
                return cleaned
        window_before = text[max(0, match.start() - 60): match.start()]
        code_match = _CODE_NEAR_KEYWORD.search(window_before)
        if code_match:
            cleaned = _clean(code_match.group(1))
            if 4 <= len(cleaned) <= 8:
                return cleaned

    # Fallback: a single standalone 4-8 digit run somewhere in a short body
    # (only if there's exactly one candidate, to avoid grabbing a random
    # order number / date / phone fragment)
    candidates = _BARE_CODE.findall(text)
    if len(candidates) == 1:
        return candidates[0]

    return None
