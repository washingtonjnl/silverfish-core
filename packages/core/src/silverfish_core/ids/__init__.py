"""Identifier generation and encoding for standalone-mode book ids.

``SnowflakeGenerator`` mints 64-bit, time-ordered ids without a database
round-trip; ``encode_base62``/``decode_base62`` render those ids as short,
URL-friendly strings at the API boundary. The integer is the identity; base62 is
presentation only.
"""

from silverfish_core.ids.base62 import decode_base62, encode_base62
from silverfish_core.ids.snowflake import SnowflakeGenerator

__all__ = [
    "SnowflakeGenerator",
    "decode_base62",
    "encode_base62",
]
