"""Tests for the Snowflake id generator (TDD).

A book id in standalone mode is a 64-bit integer laid out as
``[timestamp ms][machine id][sequence]``. Because the timestamp occupies the
high bits, ids are monotonically increasing over time — which is what gives the
database sequential inserts and lets ``ORDER BY id`` mean "by creation". The
generator needs no database round-trip (so it scales across nodes), but does
need a per-node machine id so two nodes never collide on the same sequence.

The clock is injectable so these tests are deterministic without sleeping.
"""

import pytest

from silverfish_core.ids import SnowflakeGenerator

# 2024-01-01T00:00:00Z in ms — the custom epoch the generator counts from.
_EPOCH_MS = 1_704_067_200_000


class _FakeClock:
    """A controllable millisecond clock."""

    def __init__(self, now_ms: int) -> None:
        self._now = now_ms

    def __call__(self) -> int:
        return self._now

    def advance(self, ms: int) -> None:
        self._now += ms


def _gen(
    now_ms: int = _EPOCH_MS + 1000, machine_id: int = 1
) -> tuple[SnowflakeGenerator, _FakeClock]:
    clock = _FakeClock(now_ms)
    gen = SnowflakeGenerator(machine_id=machine_id, epoch_ms=_EPOCH_MS, clock=clock)
    return gen, clock


class TestUniqueness:
    def test_consecutive_ids_are_distinct_within_same_ms(self) -> None:
        # Up to 4096 ids fit in a single millisecond's sequence; all distinct.
        gen, _ = _gen()
        ids = [gen.next_id() for _ in range(4096)]
        assert len(set(ids)) == len(ids)

    def test_distinct_when_clock_advances_each_call(self) -> None:
        gen, clock = _gen()
        ids = []
        for _ in range(5000):
            ids.append(gen.next_id())
            clock.advance(1)
        assert len(set(ids)) == len(ids)

    def test_sequence_overflow_waits_for_next_ms(self) -> None:
        # The 4097th id in one ms must wait for the clock to tick. We model that
        # by advancing the clock once the overflow path starts polling it.
        clock = _FakeClock(_EPOCH_MS + 1000)
        ticked = {"n": 0}

        def advancing_clock() -> int:
            # First 4096 reads stay in the same ms; subsequent reads advance,
            # letting the generator escape the wait loop.
            ticked["n"] += 1
            if ticked["n"] > 4097:
                clock.advance(1)
            return clock()

        gen = SnowflakeGenerator(machine_id=1, epoch_ms=_EPOCH_MS, clock=advancing_clock)
        ids = [gen.next_id() for _ in range(4098)]
        assert len(set(ids)) == len(ids)

    def test_ids_distinct_across_time(self) -> None:
        gen, clock = _gen()
        first = gen.next_id()
        clock.advance(5)
        second = gen.next_id()
        assert first != second


class TestMonotonicity:
    def test_ids_increase_within_same_ms(self) -> None:
        gen, _ = _gen()
        ids = [gen.next_id() for _ in range(1000)]
        assert ids == sorted(ids)

    def test_ids_increase_as_time_advances(self) -> None:
        gen, clock = _gen()
        early = gen.next_id()
        clock.advance(1000)
        late = gen.next_id()
        assert late > early

    def test_later_timestamp_outranks_full_sequence(self) -> None:
        # An id minted one ms later must exceed one minted now even if "now"
        # had exhausted much of its sequence — timestamp lives in the high bits.
        gen, clock = _gen()
        now_ids = [gen.next_id() for _ in range(100)]
        clock.advance(1)
        later = gen.next_id()
        assert later > max(now_ids)


class TestLayout:
    def test_id_is_positive_64_bit(self) -> None:
        gen, _ = _gen()
        value = gen.next_id()
        assert 0 < value < (1 << 63)

    def test_machine_id_separates_two_nodes(self) -> None:
        # Same instant, two machine ids -> different ids (no cross-node collision).
        clock_a = _FakeClock(_EPOCH_MS + 1000)
        clock_b = _FakeClock(_EPOCH_MS + 1000)
        gen_a = SnowflakeGenerator(machine_id=1, epoch_ms=_EPOCH_MS, clock=clock_a)
        gen_b = SnowflakeGenerator(machine_id=2, epoch_ms=_EPOCH_MS, clock=clock_b)
        assert gen_a.next_id() != gen_b.next_id()


class TestErrors:
    def test_machine_id_out_of_range_rejected(self) -> None:
        clock = _FakeClock(_EPOCH_MS)
        with pytest.raises(ValueError, match="machine"):
            SnowflakeGenerator(machine_id=10_000, epoch_ms=_EPOCH_MS, clock=clock)

    def test_negative_machine_id_rejected(self) -> None:
        clock = _FakeClock(_EPOCH_MS)
        with pytest.raises(ValueError, match="machine"):
            SnowflakeGenerator(machine_id=-1, epoch_ms=_EPOCH_MS, clock=clock)

    def test_clock_before_epoch_rejected(self) -> None:
        gen, _ = _gen(now_ms=_EPOCH_MS - 1)
        with pytest.raises(ValueError, match=r"epoch|clock|time"):
            gen.next_id()
