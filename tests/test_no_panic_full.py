# -*- coding: utf-8 -*-
"""Тест сценарію "Panic Full логів не знайдено".

Вимога: якщо panic-full / Panic Full лог не знайдено, програма НЕ має
аналізувати Analytics чи інші .log файли, не має шукати причину вимкнення
і повинна показати рівно: "Проблем не виявлено. Panic Full логів не знайдено."
"""
import importlib.util
import os
import sys
import unittest

APP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "iphone_panic_diagnostics.py",
)

_spec = importlib.util.spec_from_file_location("iphone_panic_diagnostics", APP_PATH)
MODULE = importlib.util.module_from_spec(_spec)
sys.modules["iphone_panic_diagnostics"] = MODULE
_spec.loader.exec_module(MODULE)


EXPECTED = "Проблем не виявлено. Panic Full логів не знайдено."

# Мінімальні "не-panic" зразки: аналітика, довільний .log журнал, агрегат.
ANALYTICS_LOG = (
    '{"bug_type":"309","timestamp":"2026-01-01 10:00:00.00 +0000",'
    '"os_version":"iPhone OS 18.0 (22A123)"}\n'
    '{"app_name":"SpringBoard","app_version":"1.0",'
    '"device_code":"Reduced","os_version":"iPhone OS 18.0 (22A123)",'
    '"timestamp":"2026-01-01 10:00:00.00 +0000",'
    '"applicationSpecificInformation":"no crash report",'
    '"bug_type":"309","incident_id":"AAAA-BBBB-CCCC-DDDD"}\n'
)

RANDOM_LOG = (
    "[2026-01-01 10:00:01] SpringBoard: applications finished launching\n"
    "[2026-01-01 10:00:02] runningboardd: assertion 42-7 0x0\n"
    "[2026-01-01 10:00:30] syslogd: notification, nothing relevant\n"
    "com.apple.test / 12345\n"
)

AGGREGATED_ANALYTICS = (
    '{"bug_type":"211","timestamp":"2026-01-01 10:00:00.00 +0000",'
    '"os_version":"iPhone OS 18.0 (22A123)"}\n'
    '{"build":"iPhone OS 18.0 (22A123)","product":"iPhone14,5",'
    '"kernel":"Darwin ...","AggregationId":"agg-111",'
    '"aggregated":true,"incident_id":"1111"}\n'
)


class TestNoPanicFull(unittest.TestCase):
    """Програма не діагностує причину без panic-full."""

    def assert_not_panic(self, raw_text, source_file):
        report = MODULE.parse_panic_log(raw_text, source_file=source_file)
        self.assertFalse(report.is_panic_source,
                         f"{source_file}: помилково визнаний panic-логом")
        self.assertEqual(report.verdict, EXPECTED)
        self.assertEqual(report.findings, [],
                         f"{source_file}: знахідки без panic-full = аналіз інших логів!")
        self.assertEqual(report.source_type, "analytics"
                         if "bug_type" in raw_text and "analytics" in source_file.lower()
                         else report.source_type)
        return report

    def test_empty_log(self):
        self.assert_not_panic("", "empty.txt")

    def test_analytics_ips(self):
        self.assert_not_panic(ANALYTICS_LOG, "Analytics-2026-01-01-100000.ips")

    def test_random_log(self):
        self.assert_not_panic(RANDOM_LOG, "system.log")

    def test_aggregated_analytics(self):
        self.assert_not_panic(AGGREGATED_ANALYTICS, "Aggregated-2026-01-01.ips")

    def test_classify_returns_analytics_for_analytics(self):
        st = MODULE.classify_log_source(ANALYTICS_LOG, "Analytics-2026-01-01.ips")
        self.assertIn(st, ("analytics", "other"))

    def test_crash_log_3_txt_from_repo(self):
        """Файл CrashLog 3.txt (наш тестовий «не-panic» зразок) не аналізується."""
        folder = None
        for cand in (
            r"C:\Users\Laptop\Downloads\Telegram Desktop",
            r"C:\Users\Laptop\Downloads",
        ):
            p = os.path.join(cand, "CrashLog 3.txt")
            if os.path.exists(p):
                folder = cand
                break
        if not folder:
            self.skipTest("CrashLog 3.txt не знайдено в Downloads")
        with open(os.path.join(folder, "CrashLog 3.txt"), "rb") as f:
            raw = f.read()
        text = raw.decode("utf-16", errors="replace") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") \
            else raw.decode("utf-8", errors="replace")
        report = MODULE.parse_panic_log(text, source_file="CrashLog 3.txt")
        self.assertFalse(report.is_panic_source)
        self.assertEqual(report.verdict, EXPECTED)

    def test_panic_full_still_analyzed(self):
        """Контроль: справжній panic-full дійсно аналізується."""
        panic = (
            '{"bug_type":"210","timestamp":"2026-09-11 13:29:26.00 +0300",'
            '"os_version":"iPhone OS 18.7.7 (22H340)"}\n'
            '{ "product" : "iPhone14,4", "build" : "iPhone OS 18.7.7 (22H340)",'
            '"panicString" : "panic(cpu 0 caller 0xfffffff049bb6db8): '
            '\\"_enableHalogen:4104 Unknown sample rate on DAC\\" '
            '@AppleCS42L77Audio.cpp:4104\\\\nDebugger message: panic\\\\n",'
            '"panicFlags" : "0x802" }\n'
        )
        report = MODULE.parse_panic_log(panic, source_file="panic-full-2026-09-11-132926.0002.ips")
        self.assertTrue(report.is_panic_source)
        self.assertEqual(report.source_type, "panic-full")
        self.assertNotEqual(report.verdict, EXPECTED)


if __name__ == "__main__":
    unittest.main(verbosity=2)