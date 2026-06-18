"""Snowflake id generator for standalone-mode book ids.

A 64-bit integer laid out as ``[timestamp ms][machine id][sequence]``:

    bits 63..22  (41 bits)  milliseconds since a custom epoch
    bits 21..12  (10 bits)  machine id (per-node, avoids cross-node collision)
    bits 11..0   (12 bits)  per-ms sequence (4096 ids per millisecond)

The timestamp occupies the high bits, so ids increase monotonically over time:
the database inserts sequentially (compact, unfragmented index) and ``ORDER BY
id`` means "by creation". No database round-trip is needed to mint an id, so the
scheme scales across nodes — provided each node carries a distinct machine id.

The clock is injectable (a callable returning epoch milliseconds) so behaviour
is deterministic in tests. The result always fits in 63 bits, so it is a
positive signed 64-bit integer (a ``BIGINT`` everywhere).
"""

from collections.abc import Callable

_SEQUENCE_BITS = 12
_MACHINE_BITS = 10

_MAX_SEQUENCE = (1 << _SEQUENCE_BITS) - 1
_MAX_MACHINE_ID = (1 << _MACHINE_BITS) - 1

_MACHINE_SHIFT = _SEQUENCE_BITS
_TIMESTAMP_SHIFT = _SEQUENCE_BITS + _MACHINE_BITS


class SnowflakeGenerator:
    """Mint monotonically-increasing 64-bit ids without touching the database."""

    def __init__(
        self,
        *,
        machine_id: int,
        epoch_ms: int,
        clock: Callable[[], int],
    ) -> None:
        if not (0 <= machine_id <= _MAX_MACHINE_ID):
            msg = f"machine_id must be between 0 and {_MAX_MACHINE_ID}, got {machine_id}"
            raise ValueError(msg)
        self._machine_id = machine_id
        self._epoch_ms = epoch_ms
        self._clock = clock
        self._last_ms = -1
        self._sequence = 0

    def next_id(self) -> int:
        """Return the next id. Monotonic across calls, unique per (node, time)."""
        now = self._clock()
        if now < self._epoch_ms:
            msg = "clock is before the configured epoch"
            raise ValueError(msg)

        if now == self._last_ms:
            self._sequence += 1
            if self._sequence > _MAX_SEQUENCE:
                # Sequence exhausted this millisecond: wait for the next tick.
                now = self._wait_next_ms(now)
                self._sequence = 0
        else:
            self._sequence = 0
        self._last_ms = now

        elapsed = now - self._epoch_ms
        return (elapsed << _TIMESTAMP_SHIFT) | (self._machine_id << _MACHINE_SHIFT) | self._sequence

    def _wait_next_ms(self, current: int) -> int:
        now = self._clock()
        while now <= current:
            now = self._clock()
        return now
