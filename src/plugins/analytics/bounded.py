"""Bounded, memory-safe primitives for the analytics engine.

Every dimension the engine tracks (tools, orgs, callers) must have a hard cap so
memory is O(caps), not O(traffic) or O(tenant-count). These primitives enforce that.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Callable, Dict, Generic, Iterator, Tuple, TypeVar

V = TypeVar("V")


class LRUMap(Generic[V]):
    """A dict with a hard capacity that evicts least-recently-used keys.

    Used for the tool / org / caller dimensions so a large tenant base can never
    OOM the process -- past ``capacity`` distinct keys, the coldest is dropped.
    """

    def __init__(self, capacity: int, factory: Callable[[], V]):
        self._cap = max(1, int(capacity))
        self._factory = factory
        self._data: "OrderedDict[str, V]" = OrderedDict()
        self.evictions = 0

    def get_or_create(self, key: str) -> V:
        v = self._data.get(key)
        if v is None:
            v = self._factory()
            self._data[key] = v
            if len(self._data) > self._cap:
                self._data.popitem(last=False)
                self.evictions += 1
        else:
            self._data.move_to_end(key)
        return v

    def peek(self, key: str) -> V | None:
        return self._data.get(key)

    def items(self) -> Iterator[Tuple[str, V]]:
        return iter(list(self._data.items()))

    def __len__(self) -> int:
        return len(self._data)


class HyperLogLog:
    """Tiny HyperLogLog for approximate unique counting with fixed memory.

    ~1.5 KB of registers, ~2% standard error -- used for "unique callers" so the
    count never grows with the number of distinct callers (bounded, approximate).
    """

    def __init__(self, p: int = 10):
        self.p = p
        self.m = 1 << p
        self.registers = bytearray(self.m)

    def add(self, value: str) -> None:
        import hashlib
        h = int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")
        idx = h & (self.m - 1)
        w = h >> self.p
        rank = 1
        while w & 1 == 0 and rank <= 64 - self.p:
            rank += 1
            w >>= 1
        if rank > self.registers[idx]:
            self.registers[idx] = rank

    def count(self) -> int:
        import math
        if self.p == 4:
            alpha = 0.673
        elif self.p == 5:
            alpha = 0.697
        else:
            alpha = 0.7213 / (1 + 1.079 / self.m)
        s = sum(2.0 ** -r for r in self.registers)
        est = alpha * self.m * self.m / s
        # small-range correction
        if est <= 2.5 * self.m:
            zeros = self.registers.count(0)
            if zeros:
                est = self.m * math.log(self.m / zeros)
        return int(est)
