# -*- coding: utf-8 -*-
"""Тести документної бази знань PanicIF (``app/core/knowledge_base.json``).

Перевіряють завантаження/валідацію, нормалізацію фраз та — найголовніше —
що документні правила справді працюють через наявний рушій
(:mod:`app.core.diagnostics`), не створюючи дублюючого діагностувача.
"""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import diagnostics as core  # noqa: E402
from app.core import knowledge_base as kb  # noqa: E402

EXPECTED_RECORDS = 45


def _panic_log(panic_string: str) -> str:
    return (
        '{"bug_type":"210","timestamp":"2026-01-01 10:00:00.00 +0000",'
        '"os_version":"iPhone OS 18.0 (22A123)","incident_id":"AAAA-BBBB",'
        '"panicString":"' + panic_string + '","panicFlags":"0x2",'
        '"product":"iPhone14,2","build":"22A123"}\n'
    )


def _kb_ids(report):
    return [f.kb_id for f in report.findings if f.kb_id]


class LoadRecordsTests(unittest.TestCase):
    def test_loads_all_document_records(self):
        records = kb.load_records()
        self.assertEqual(len(records), EXPECTED_RECORDS)
        ids = [r["id"] for r in records]
        self.assertEqual(len(ids), len(set(ids)))
        for record in records:
            self.assertTrue(record["patterns"])
            self.assertIsInstance(record["component"], str)
            self.assertIsInstance(record["notes"], str)
            self.assertIsInstance(record["models"], list)

    def test_kb_path_is_relative_to_module_not_hardcoded(self):
        expected = os.path.join(os.path.dirname(kb.__file__), "knowledge_base.json")
        self.assertEqual(os.path.abspath(kb.kb_path()), os.path.abspath(expected))
        self.assertTrue(os.path.isfile(kb.kb_path()))

    def test_records_include_expected_entries(self):
        by_id = {r["id"]: r for r in kb.load_records()}
        self.assertEqual(by_id["kb-002"]["component"], "NAND")
        self.assertIn("ANS/ANS2", by_id["kb-002"]["patterns"])
        self.assertTrue(by_id["kb-033"]["generic"])
        self.assertTrue(by_id["kb-011"]["ambiguous"])

    def test_invalid_records_raise(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.json")
            with open(bad, "w", encoding="utf-8") as handle:
                json.dump({"records": [{"id": "x", "patterns": []}]}, handle)
            with self.assertRaises(ValueError):
                kb.load_records(bad)


class CompileRulesTests(unittest.TestCase):
    def test_compiles_all_patterns(self):
        rules = kb.compile_rules()
        self.assertEqual(len(rules), EXPECTED_RECORDS)
        for rule in rules:
            self.assertIsInstance(rule["pattern"], str)
            re.compile(rule["pattern"], re.IGNORECASE)  # не має кидати re.error
            self.assertTrue(rule["normalized"])


class NormalizeTextTests(unittest.TestCase):
    def test_collapses_whitespace_and_newlines(self):
        self.assertEqual(kb.normalize_text("  AOP   PANIC \n prox "), "AOP PANIC prox")

    def test_unifies_dashes(self):
        self.assertEqual(kb.normalize_text("L2C–LLC"), "L2C-LLC")


class PhraseToRegexTests(unittest.TestCase):
    def test_matches_separator_variants_and_case(self):
        pattern = kb.phrase_to_regex("ANS/ANS2")
        self.assertIsNotNone(pattern)
        rx = re.compile(pattern, re.IGNORECASE)
        for variant in ("ANS/ANS2", "ans/ans2", "ANS / ANS2", "ANS-ANS2", "ANS\nANS2"):
            self.assertRegex(variant, rx)

    def test_escapes_regex_metacharacters(self):
        pattern = kb.phrase_to_regex("power(1)-failed")
        rx = re.compile(pattern, re.IGNORECASE)
        self.assertRegex("power(1)-failed", rx)
        self.assertNotRegex("power11failed", rx)

    def test_empty_phrase_returns_none(self):
        self.assertIsNone(kb.phrase_to_regex("   "))


class CoreIntegrationTests(unittest.TestCase):
    def test_core_loaded_document_rules(self):
        ids = [e.get("kb_id") for e in core.CORE.KNOWLEDGE_BASE if e.get("kb_id")]
        self.assertEqual(len(ids), EXPECTED_RECORDS)

    def test_exact_document_match(self):
        report = core.parse_panic_log(
            _panic_log("SD: 0 Missing sensor(s): TG0B"), "p.ips"
        )
        self.assertIn("kb-003", _kb_ids(report))
        finding = next(f for f in report.findings if f.kb_id == "kb-003")
        self.assertEqual(finding.component, "АКБ/TIGRIS")

    def test_case_and_separator_insensitive_match(self):
        for variant in ("ans/ans2", "ANS / ANS2", "ANS-ANS2"):
            report = core.parse_panic_log(_panic_log(variant), "p.ips")
            self.assertIn(
                "kb-002",
                _kb_ids(report),
                f"варіант {variant!r} не збігся",
            )

    def test_notes_are_propagated(self):
        report = core.parse_panic_log(_panic_log("AOP PANIC - PressureController"), "p.ips")
        finding = next(f for f in report.findings if f.kb_id == "kb-001")
        self.assertIn("барометр", finding.notes.lower())
        self.assertEqual(finding.severity, "warning")

    def test_generic_does_not_override_specific(self):
        report = core.parse_panic_log(_panic_log("AOP PANIC - SCMto:0 - prox"), "p.ips")
        ids = _kb_ids(report)
        self.assertIn("kb-004", ids)
        self.assertNotIn("kb-033", ids)

    def test_multiple_problems_flagged_ambiguous(self):
        report = core.parse_panic_log(_panic_log("nvme panic; lm3539 backlight"), "p.ips")
        self.assertTrue(len(report.findings) >= 2)
        self.assertTrue(report.ambiguous)

    def test_ambiguous_single_record_is_flagged(self):
        report = core.parse_panic_log(_panic_log("NO pulse on Taptic Engine"), "p.ips")
        self.assertIn("kb-011", _kb_ids(report))
        self.assertTrue(report.ambiguous)

    def test_no_document_match_keeps_findings_without_kb_id(self):
        report = core.parse_panic_log(_panic_log("some totally unrelated panic text"), "p.ips")
        self.assertNotIn("kb-", "".join(_kb_ids(report)))

    def test_ocr_source_uses_same_knowledge_base(self):
        report = core.analyze_ocr_text(
            "power(1)-failed to transition detected", source_file="photo.png"
        )
        self.assertIn("kb-030", _kb_ids(report))
        self.assertEqual(report.source_type, "photo")


class ReportFormatTests(unittest.TestCase):
    def test_full_report_contains_structured_result(self):
        report = core.parse_panic_log(_panic_log("AOP PANIC - PressureController"), "p.ips")
        text = core.build_text_report(report)
        self.assertIn("ЗВІТ ДІАГНОСТИКИ", text)
        self.assertIn("КОРОТКИЙ РЕЗУЛЬТАТ (PanicIF)", text)
        self.assertIn("Знайдена помилка:", text)
        self.assertIn("Ймовірний компонент:", text)
        self.assertIn("Рівень визначеності:", text)

    def test_telegram_report_sections(self):
        report = core.parse_panic_log(_panic_log("nvme panic; lm3539 backlight"), "p.ips")
        text = core.build_telegram_report(report)
        self.assertIn("PanicIF", text)
        self.assertIn("Знайдена помилка:", text)
        self.assertIn("Додаткові збіги:", text)
        self.assertIn("неоднозначний", text)


class DocumentFidelityTests(unittest.TestCase):
    """Звіряє кожен рядок вихідного DOCX з відповідним записом JSON.

    Гарантує, що жодна примітка з ``PanicIF_ukrainian_translation.docx``
    не загубилась під час міграції в структуровану базу знань. Пробіли
    (зокрема після крапок) не вважаються значущими.
    """

    FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "docx_rows.json")

    @staticmethod
    def _squash(text):
        return re.sub(r"\s+", "", text or "")

    def test_every_docx_row_maps_to_record(self):
        import json

        with open(self.FIXTURE, encoding="utf-8") as handle:
            rows = json.load(handle)
        self.assertEqual(rows[0], ["ДАНІ", "РЕЗУЛЬТАТ АНАЛІЗУ", "ПРИМІТКИ"])
        data_rows = rows[1:]
        self.assertEqual(len(data_rows), EXPECTED_RECORDS)

        by_pattern = {}
        for record in kb.load_records():
            for pattern in record["patterns"]:
                by_pattern[pattern.strip().lower()] = record

        for row in data_rows:
            data = (row[0] if len(row) > 0 else "").strip()
            result = (row[1] if len(row) > 1 else "").strip()
            note = row[2] if len(row) > 2 else ""
            record = by_pattern.get(data.lower()) or by_pattern.get(result.lower())
            self.assertIsNotNone(record, f"рядок DOCX без запису в JSON: {data!r}")
            self.assertEqual(
                self._squash(note),
                self._squash(record["notes"]),
                f"примітка розійшлась для {data!r}",
            )


if __name__ == "__main__":
    unittest.main()
