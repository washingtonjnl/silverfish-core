"""Tests for public book-id encoding, which depends on the library mode (TDD).

The public id is always a string, but how the internal integer is rendered
differs by mode:

* standalone — the core mints large Snowflake ids, so they are shortened to
  base62 (Instagram-style); the decimal form would be unwieldy.
* calibre — the id is Calibre's small autoincrement integer, shown as its plain
  decimal string so it matches exactly what Calibre desktop displays (book 14 is
  "14", not "E").

Either way the round-trip (encode then decode) returns the original integer, and
a malformed public id is rejected.
"""

import pytest

from silverfish_api.config import LibraryMode
from silverfish_api.public_id import PublicIdCodec


class TestStandalone:
    codec = PublicIdCodec(LibraryMode.STANDALONE)

    def test_encodes_to_base62(self) -> None:
        # 14 -> "E" in base62 (A=10 ... E=14).
        assert self.codec.encode(14) == "E"

    def test_large_id_is_shortened(self) -> None:
        big = 7_213_445_678_901_234_567
        encoded = self.codec.encode(big)
        assert len(encoded) < len(str(big))

    def test_round_trips(self) -> None:
        for n in (0, 1, 14, 61, 62, 7_213_445_678_901_234_567):
            assert self.codec.decode(self.codec.encode(n)) == n


class TestCalibre:
    codec = PublicIdCodec(LibraryMode.CALIBRE)

    def test_encodes_as_plain_decimal_string(self) -> None:
        # Matches what Calibre desktop shows: 14 stays "14".
        assert self.codec.encode(14) == "14"

    def test_round_trips(self) -> None:
        for n in (1, 14, 999):
            assert self.codec.decode(self.codec.encode(n)) == n

    def test_decode_rejects_non_numeric(self) -> None:
        with pytest.raises(ValueError, match=r"invalid|not"):
            self.codec.decode("E")


class TestDecodeErrors:
    def test_standalone_rejects_out_of_alphabet(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            PublicIdCodec(LibraryMode.STANDALONE).decode("not-valid")

    def test_calibre_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match=r"invalid|empty|not"):
            PublicIdCodec(LibraryMode.CALIBRE).decode("")
