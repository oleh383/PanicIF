# -*- coding: utf-8 -*-
"""Прості обмеження навантаження для PanicIF Bot (без бази даних).

Містить ковзний ліміт частоти запитів на одного користувача. Уся статистика
тримається в пам'яті процесу й не потребує жодних зовнішніх залежностей.

Обмеження одночасних важких операцій реалізовано в :mod:`bot.main` через
:class:`asyncio.Semaphore` (щоб не прив'язувати його до конкретного event loop
на рівні сервісу).
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable, Deque, Dict, Hashable, Tuple

# Типові ліміти: не більше N важких запитів за вікно часу на одного користувача.
DEFAULT_MAX_REQUESTS = 5
DEFAULT_WINDOW_SECONDS = 60.0


class RateLimiter:
    """Ковзний (sliding-window) ліміт запитів у пам'яті.

    :param max_requests: максимум подій у межах вікна.
    :param window_seconds: довжина вікна у секундах.
    :param clock: функція поточного часу (для тестів; за замовчуванням
        монотонний годинник).
    """

    def __init__(
        self,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests = int(max_requests)
        self.window_seconds = float(window_seconds)
        self._clock = clock
        self._events: Dict[Hashable, Deque[float]] = {}

    def allow(self, key: Hashable) -> Tuple[bool, float]:
        """Дозволити подію для ``key``.

        Повертає ``(True, 0.0)`` якщо запит дозволено (і реєструє його), або
        ``(False, retry_after)`` із орієнтовним часом очікування у секундах.
        """
        now = self._clock()
        bucket = self._events.get(key)
        if bucket is None:
            bucket = deque()
            self._events[key] = bucket

        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self.max_requests:
            retry_after = bucket[0] + self.window_seconds - now
            return False, max(retry_after, 0.0)

        bucket.append(now)
        return True, 0.0

    def reset(self) -> None:
        """Очистити всю історію (використовується в тестах)."""
        self._events.clear()


__all__ = [
    "DEFAULT_MAX_REQUESTS",
    "DEFAULT_WINDOW_SECONDS",
    "RateLimiter",
]
