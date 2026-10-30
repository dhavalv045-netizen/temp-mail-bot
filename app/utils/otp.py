import re


def extract_otp(text: str) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None

    # Accept a numeric code only when the message mentions verification.
    keyword = (
        r"\b(?:otp|verification\s+code|security\s+code|"
        r"login\s+code|one[- ]time\s+(?:password|code)|"
        r"passcode|code)\b"
    )

    patterns = [
        keyword + r"[^\d\n]{0,40}(?<!\w)(\d{4,8})(?!\w)",
        r"(?<!\w)(\d{4,8})(?!\w)[^\d\n]{0,40}" + keyword,
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return None
