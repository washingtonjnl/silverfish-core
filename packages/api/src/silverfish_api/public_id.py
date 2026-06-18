"""Public book-id encoding, parameterised by library mode.

The public id is always a string so the OpenAPI contract keeps one shape, but
its rendering depends on the mode:

* standalone — ids are large Snowflake integers, rendered as short base62
  (the decimal form would be unwieldy in a URL).
* calibre — ids are Calibre's small autoincrement integers, rendered as their
  plain decimal string so they match exactly what Calibre desktop shows
  (book 14 is ``"14"``, not ``"E"``). This keeps the API a faithful layer over
  an existing Calibre library.

Both directions round-trip, and a malformed public id raises ``ValueError`` (the
boundary turns that into a 404 — a value that cannot be decoded names no book).
"""

from silverfish_api.config import LibraryMode
from silverfish_core.ids import decode_base62, encode_base62


class PublicIdCodec:
    """Encode/decode the public id form for a given library mode."""

    def __init__(self, mode: LibraryMode) -> None:
        self._mode = mode

    def encode(self, internal_id: int) -> str:
        if self._mode is LibraryMode.CALIBRE:
            return str(internal_id)
        return encode_base62(internal_id)

    def decode(self, public_id: str) -> int:
        if self._mode is LibraryMode.CALIBRE:
            if not public_id.isdigit():
                msg = f"invalid book id: {public_id!r}"
                raise ValueError(msg)
            return int(public_id)
        return decode_base62(public_id)
