# -*- coding: utf-8 -*-
"""Тести запуску PanicIF Bot: асинхронний життєвий цикл для python-telegram-bot 21+."""

import asyncio
import unittest
from unittest import mock

try:
    import telegram  # noqa: F401
    HAVE_TELEGRAM = True
except Exception:  # pragma: no cover
    HAVE_TELEGRAM = False


class _FakeUpdater:
    def __init__(self):
        self.calls = []

    async def start_polling(self, **kwargs):
        self.calls.append(("start_polling", kwargs))

    async def stop(self):
        self.calls.append(("stop", {}))


class _FakeApplication:
    def __init__(self, with_updater=True):
        self.updater = _FakeUpdater() if with_updater else None
        self.calls = []

    async def initialize(self):
        self.calls.append("initialize")

    async def start(self):
        self.calls.append("start")

    async def stop(self):
        self.calls.append("stop")

    async def shutdown(self):
        self.calls.append("shutdown")


@unittest.skipUnless(HAVE_TELEGRAM, "python-telegram-bot не встановлено")
class RunBotLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from bot import main as bot_main

        self.bot_main = bot_main

    async def _wait_until_polling(self, app, task):
        for _ in range(100):
            if app.updater is not None and app.updater.calls:
                return
            if task.done():
                return
            await asyncio.sleep(0)
        self.fail("updater.start_polling не викликано")

    async def test_lifecycle_starts_and_shuts_down_on_cancel(self):
        app = _FakeApplication()
        task = asyncio.create_task(self.bot_main.run_bot(app))
        await self._wait_until_polling(app, task)

        name, kwargs = app.updater.calls[0]
        self.assertEqual(name, "start_polling")
        self.assertIn("allowed_updates", kwargs)

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(app.calls, ["initialize", "start", "stop", "shutdown"])
        self.assertEqual(app.updater.calls[-1], ("stop", {}))

    async def test_missing_updater_raises(self):
        app = _FakeApplication(with_updater=False)
        with self.assertRaises(RuntimeError):
            await self.bot_main.run_bot(app)
        self.assertEqual(app.calls, ["initialize", "start"])

    def test_main_runs_asyncio_with_built_application(self):
        app = _FakeApplication()
        with mock.patch.object(
            self.bot_main, "require_bot_token", return_value="123:token"
        ), mock.patch.object(
            self.bot_main, "build_application", return_value=app
        ) as build, mock.patch.object(self.bot_main.asyncio, "run") as run:
            self.bot_main.main()

        build.assert_called_once_with("123:token")
        self.assertEqual(run.call_count, 1)
        run.call_args.args[0].close()

    def test_main_without_token_exits(self):
        with mock.patch.object(
            self.bot_main,
            "require_bot_token",
            side_effect=self.bot_main.BotConfigError("немає токена"),
        ):
            with self.assertRaises(SystemExit) as ctx:
                self.bot_main.main()
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
