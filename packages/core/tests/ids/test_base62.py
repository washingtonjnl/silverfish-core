"""Tests for base62 encoding of book ids (TDD).

The public API exposes a book's 64-bit Snowflake id as a short, URL-friendly
base62 string (Instagram-style). Encoding is pure presentation: the integer is
the identity, base62 is just how it appears in a URL. Encoding must round-trip
exactly and reject malformed input.
"""

import pytest

from silverfish_core.ids import decode_base62, encode_base62

# A representative large Snowflake-sized integer (well over 32 bits).
_SNOWFLAKE = 7_213_445_678_901_234_567


class TestRoundTrip:
    def test_encode_then_decode_is_identity(self) -> None:
        assert decode_base62(encode_base62(_SNOWFLAKE)) == _SNOWFLAKE

    def test_zero_round_trips(self) -> None:
        assert decode_base62(encode_base62(0)) == 0

    def test_small_values_round_trip(self) -> None:
        for n in range(200):
            assert decode_base62(encode_base62(n)) == n


class TestEncoding:
    def test_uses_only_base62_alphabet(self) -> None:
        encoded = encode_base62(_SNOWFLAKE)
        alphabet = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
        assert set(encoded) <= alphabet

    def test_zero_encodes_to_single_char(self) -> None:
        assert encode_base62(0) == "0"

    def test_is_shorter_than_decimal_for_large_ids(self) -> None:
        encoded = encode_base62(_SNOWFLAKE)
        assert len(encoded) < len(str(_SNOWFLAKE))

    def test_distinct_values_encode_distinctly(self) -> None:
        seen = {encode_base62(n) for n in range(1000)}
        assert len(seen) == 1000


class TestErrors:
    def test_negative_value_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"negative|non-negative"):
            encode_base62(-1)

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"empty|invalid"):
            decode_base62("")

    def test_non_alphabet_char_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            decode_base62("abc-def")
