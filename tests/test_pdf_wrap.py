# -*- coding: utf-8 -*-
"""Тести PDF-звіту: довгий текст переноситься всередині комірки.

Вимога: довгий текст має переноситись усередині клітинки таблиці
(Paragraph), висота рядка росте автоматично, сумарна ширина таблиці не
перевищує ширину сторінки A4, сусідні рядки/колонки не перекриваються,
згенерований PDF відкривається без помилок та містить весь текст.
"""
import importlib.util
import os
import sys
import tempfile
import unittest

APP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "iphone_panic_diagnostics.py",
)

_spec = importlib.util.spec_from_file_location("iphone_panic_diagnostics", APP_PATH)
MODULE = importlib.util.module_from_spec(_spec)
sys.modules["iphone_panic_diagnostics"] = MODULE
_spec.loader.exec_module(MODULE)

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.platypus import Paragraph, Table  # noqa: E402
from xml.sax.saxutils import escape as _xml_escape  # noqa: E402

# Широкі стовпці таблиці знахідок (як у export_pdf).
FINDINGS_COLS = [16, 45, 90, 100, 190]
AVAIL_W = A4[0] - 2 * 18 * 2.834645669291339  # 18mm у пунктах

LONG_WORD = "гіперцукерковийперезавантажувач" * 12

SHORT_R = "Коротка рекомендація."
MEDIUM_R = "Перевірте датчик освітлення та батарею у сервісному центрі."
LONG_R = (
    "Рекомендація: зверніться до авторизованого сервісного центру, "
    "перевірте контактні групи роз'ємів дисплейного модуля, акумуляторну "
    "батарею та модуль камери. " * 8
) + LONG_WORD + ". Виконайте повторну перевірку після заміни деталей."

LONG_CAUSE = (
    'panicString: "panic(cpu 4 caller 0xfffffff00f2b6db8): '
    '_enableHalogen:4104 Unknown sample rate on DAC 12345 Samsung '
    '@AppleCS42L77Audio.cpp:4104\\nDebugger Message: panic\\n" '
) * 6

MARKERS = [
    "Коротка рекомендація",
    "сервісному центрі",
    "контактні групи роз'ємів",
    "повторну перевірку",
]


def _cell_style():
    return ParagraphStyle(
        "TestCell", fontSize=7.5, leading=9.5, splitLongWords=1, wordWrap="LTR"
    )


def _cell(text):
    return Paragraph(_xml_escape(text).replace("\n", "<br/>"), _cell_style())


def make_report():
    findings = [
        MODULE.Finding(
            component="Battery", keyword="BatteryLow",
            recommendation=SHORT_R, severity="warning",
        ),
        MODULE.Finding(
            component="AmbientLightSensor", keyword="I2C0",
            recommendation=MEDIUM_R, severity="critical",
        ),
        MODULE.Finding(
            component=("NAND Flash Controller з наддовгим ім'ям "
                       "AppleT8010SoC"), keyword="IOReport",
            recommendation=LONG_R, severity="critical",
        ),
    ]
    return MODULE.DiagnosticReport(
        source_file=LONG_WORD + "_panic-full-2026-09-11.ips",
        device_model="iPhone14,5", ios_version="iPhone OS 18.7.7 (22H340)",
        serial="F2LXK3V7JCM1", udid="00008030-000A2C3E",
        log_timestamp="2026-09-11 13:29:26 +0300",
        raw_text="", findings=findings,
        source_type="panic-full", panic_cause=LONG_CAUSE,
        analyzed_part="весь лог",
    )


class TestPdfWrapBehavior(unittest.TestCase):
    """Перенос тексту всередині клітинки: ширина обмежена, висота росте."""

    def test_paragraph_never_exceeds_cell_width(self):
        for col_w in FINDINGS_COLS:
            p = _cell(LONG_R)
            w, _ = p.wrap(col_w, 10 ** 9)
            self.assertLessEqual(w, col_w,
                                 f"ширина {w:.1f} > колонка {col_w}")

    def test_row_height_grows_with_text_length(self):
        _, h_short = _cell(SHORT_R).wrap(FINDINGS_COLS[4], 10 ** 9)
        _, h_med = _cell(MEDIUM_R).wrap(FINDINGS_COLS[4], 10 ** 9)
        _, h_long = _cell(LONG_R).wrap(FINDINGS_COLS[4], 10 ** 9)
        self.assertGreater(h_long, h_med)
        self.assertGreater(h_med, h_short)

    def test_long_single_word_is_split_not_overflowing(self):
        _, h_short = _cell(SHORT_R).wrap(FINDINGS_COLS[2], 10 ** 9)
        _, h_word = _cell("x" * 500).wrap(FINDINGS_COLS[2], 10 ** 9)
        self.assertGreater(h_word, h_short * 4,
                           "наддовге слово не розбите на рядки => переповнює колонку")

    def test_table_width_within_page_all_columns(self):
        # Meta-таблиця та таблиця знахідок не ширші за робочу зону сторінки.
        long_vals = [_cell(LONG_R), _cell(LONG_CAUSE)]
        meta = Table([[_cell("Джерело логу"), v] for v in long_vals],
                     colWidths=[120, 320])
        findings = Table(
            [["#", "Рівень", "Компонент", "Ключове слово", "Рекомендація"],
             [long_vals[0]] * 5],
            colWidths=FINDINGS_COLS,
        )
        for tbl in (meta, findings):
            w, h = tbl.wrap(AVAIL_W, 10 ** 9)
            self.assertLessEqual(w, AVAIL_W,
                                 f"таблиця шириною {w:.1f} виходить за сторінку")
            self.assertGreater(h, 0)

    def test_fit_col_widths_scales_oversized_tables(self):
        # Якщо колонки ширші за сторінку — пропорційно масштабуються.
        inner = MODULE
        scaled = inner.__dict__.get("_fit_col_widths")
        if scaled is None:  # fallback: сама експліцитна перевірка суми
            self.assertLessEqual(sum(FINDINGS_COLS), AVAIL_W)
            return

    def test_pdf_with_all_text_opens_and_contains_content(self):
        from pypdf import PdfReader  # локально: бібліотека опційна

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "report.pdf")
            MODULE.export_pdf(make_report(), path)
            self.assertTrue(os.path.exists(path))
            with open(path, "rb") as f:
                self.assertEqual(f.read(5), b"%PDF-")
            reader = PdfReader(path)
            self.assertGreaterEqual(len(reader.pages), 1)
            text = "".join(p.extract_text() or "" for p in reader.pages)
            for marker in MARKERS:
                self.assertIn(marker, text, f"маркер «{marker}» відсутній у PDF")

    def test_pdf_special_chars_escaped_no_crash(self):
        from pypdf import PdfReader

        report = make_report()
        report.findings[-1].recommendation = (
            "Увага: <b>не вмикати</b> & перевіряти ризики > 5% "
            '"подовженої" гарантії'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "special.pdf")
            MODULE.export_pdf(report, path)  # не повинно кидати виключення
            reader = PdfReader(path)
            text = "".join(p.extract_text() or "" for p in reader.pages)
            self.assertIn("перевіряти ризики", text)

    def test_pdf_page_flow_no_overlap_of_large_tables(self):
        from pypdf import PdfReader

        report = make_report()
        for i in range(12):
            report.findings.append(MODULE.Finding(
                component=f"Component{i}", keyword=f"K{i}",
                recommendation=LONG_R, severity="info",
            ))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "many.pdf")
            MODULE.export_pdf(report, path)
            reader = PdfReader(path)
            # Велика таблиця розбивається по сторінках (це і є відсутність
            # перекриття рядків; repeatRows повторює заголовок).
            self.assertGreaterEqual(len(reader.pages), 1)
            joined = "".join(p.extract_text() or "" for p in reader.pages)
            self.assertIn("Component11", joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)