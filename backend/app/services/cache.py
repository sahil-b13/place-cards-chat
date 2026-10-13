import time
from typing import Any, Callable, Optional


class TTLCache:
    """Tiny in-memory TTL cache (keyed by place_id etc.). Not shared across processes."""

    def __init__(self, ttl_seconds: int = 86400, clock: Callable[[], float] = time.monotonic,
                 max_items: int = 2000):
        self.ttl = ttl_seconds
        self._clock = clock
        self._max = max_items
        self._data: dict[str, tuple[float, Any]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        item = self._data.get(key)
        if item is None:
            self.misses += 1
            return None
        expires, value = item
        if self._clock() >= expires:
            del self._data[key]
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, key: str, value: Any) -> None:
        if len(self._data) >= self._max:
            # drop the oldest-expiring entry
            oldest = min(self._data, key=lambda k: self._data[k][0])
            del self._data[oldest]
        self._data[key] = (self._clock() + self.ttl, value)

    def __len__(self) -> int:
        return len(self._data)
