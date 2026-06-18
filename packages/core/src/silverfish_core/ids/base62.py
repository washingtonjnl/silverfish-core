"""Base62 encoding for public book ids.

A book's identity is its 64-bit Snowflake integer; base62 is purely how that
integer appears in a URL (short and URL-safe, Instagram-style). Encoding is a
deterministic, reversible mapping — not a second id. The database never stores
the string; only the API boundary encodes on the way out and decodes on the way
in.
"""

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_BASE = len(_ALPHABET)
_INDEX = {char: i for i, char in enumerate(_ALPHABET)}


def encode_base62(value: int) -> str:
    """Encode a non-negative integer as a base62 string.

    Zero encodes to ``"0"``. Raises ``ValueError`` for negative input (ids are
    always non-negative).
    """
    if value < 0:
        msg = "cannot encode a negative value"
        raise ValueError(msg)
    if value == 0:
        return _ALPHABET[0]
    chars: list[str] = []
    while value:
        value, remainder = divmod(value, _BASE)
        chars.append(_ALPHABET[remainder])
    chars.reverse()
    return "".join(chars)


def decode_base62(text: str) -> int:
    """Decode a base62 string back to its integer.

    Raises ``ValueError`` if the string is empty or contains a character outside
    the base62 alphabet.
    """
    if not text:
        msg = "cannot decode an empty string"
        raise ValueError(msg)
    value = 0
    for char in text:
        digit = _INDEX.get(char)
        if digit is None:
            msg = f"invalid base62 character: {char!r}"
            raise ValueError(msg)
        value = value * _BASE + digit
    return value
