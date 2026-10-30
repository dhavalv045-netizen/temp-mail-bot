import re

def extract_otp(text: str) -> str | None:
    if not isinstance(text, str):
        return None
    keyword = r"\b(?:otp|verification\s+code|security\s+code|login\s+code|one[- ]time\s+(?:password|code)|passcode|code)\b"
    for pattern in [keyword + r"[^\d\n]{0,40}(?<!\w)(\d{4,8})(?!\w)", r"(?<!\w)(\d{4,8})(?!\w)[^\d\n]{0,40}" + keyword]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None
