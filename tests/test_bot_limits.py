# -*- coding: utf-8 -*-
"""Тести ліміту частоти запитів (без потреби у telegram-бібліотеці)."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot.services.limits import RateLimiter  # noqa: E402


class _Clock:
    """Керований годинник для детермінованих тестів."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class RateLimiterTests(unittest.TestCase):
    def test_allows_up_to_limit(self):
        clock = _Clock()
        limiter = RateLimiter(max_requests=3, window_seconds=60.0, clock=clock)
        for _ in range(3):
            allowed, retry_after = limiter.allow("user")
            self.assertTrue(allowed)
            self.assertEqual(retry_after, 0.0)

    def test_blocks_over_limit(self):
        clock = _Clock()
        limiter = RateLimiter(max_requests=2, window_seconds=60.0, clock=clock)
        limiter.allow("user")
        limiter.allow("user")
        allowed, retry_after = limiter.allow("user")
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0.0)
        self.assertLessEqual(retry_after, 60.0)

    def test_window_slides(self):
        clock = _Clock()
        limiter = RateLimiter(max_requests=1, window_seconds=30.0, clock=clock)
        self.assertTrue(limiter.allow("user")[0])
        self.assertFalse(limiter.allow("user")[0])
        clock.advance(31.0)
        self.assertTrue(limiter.allow("user")[0])

    def test_keys_are_independent(self):
        clock = _Clock()
        limiter = RateLimiter(max_requests=1, window_seconds=60.0, clock=clock)
        self.assertTrue(limiter.allow("a")[0])
        self.assertFalse(limiter.allow("a")[0])
        self.assertTrue(limiter.allow("b")[0])

    def test_reset_clears_history(self):
        clock = _Clock()
        limiter = RateLimiter(max_requests=1, window_seconds=60.0, clock=clock)
        limiter.allow("user")
        self.assertFalse(limiter.allow("user")[0])
        limiter.reset()
        self.assertTrue(limiter.allow("user")[0])

    def test_retry_after_counts_down(self):
        clock = _Clock()
        limiter = RateLimiter(max_requests=1, window_seconds=60.0, clock=clock)
        limiter.allow("user")
        first = limiter.allow("user")[1]
        clock.advance(10.0)
        second = limiter.allow("user")[1]
        self.assertLess(second, first)


if __name__ == "__main__":
    unittest.main()
