# -*- coding: utf-8 -*-
"""Структурована база знань PanicIF із документа ``PanicIF_ukrainian_translation.docx``.

Модуль НЕ містить окремого рушія діагностики. Він лише:

1. читає ``app/core/knowledge_base.json`` (дані, що входять до Git і доступні
   на Render);
2. нормалізує ключові фрази у безпечні регулярні вирази;
3. віддає записи у форматі, який уже використовує наявний рушій
   ``app/iphone_panic_diagnostics.py`` (``pattern``/``keyword``/``component``/
   ``recommendation``/``severity``/``notes``).

Шлях до JSON обчислюється відносно цього файлу, тому база знань працює після
розгортання на Render без будь-яких абсолютних шляхів з локальної машини.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

KB_FILENAME = "knowledge_base.json"
DEFAULT_SOURCE = "PanicIF_ukrainian_translation.docx"

# Символи-роздільники, які безпечно прирівнювати в межах коду/фрази
# (пробіли, переноси, слеш, зворотний слеш, двокрапка, крапка з комою, дефіси).
_SEPARATOR_CLASS = r"[\s/\\:;\-\u2010\u2011\u2012\u2013\u2014\u2015]"
_SEPARATOR_RUN = _SEPARATOR_CLASS + "+"
_DASH_EQUIVALENTS = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"


def kb_path() -> str:
    """Абсолютний шлях до JSON-бази знань (відносно цього модуля, не CWD)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), KB_FILENAME)


def normalize_text(text: Optional[str]) -> str:
    """Безпечна нормалізація тексту логу перед пошуком.

    * уніфікує переноси рядків (``\\r\\n``/``\\r`` -> ``\\n``);
    * згортає будь-які пробіли/таби/переноси в один пробіл;
    * прирівнює різні типи дефісів/тире до звичайного дефіса.

    Значення кодів (hex, індекси) при цьому не змінюються.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for ch in _DASH_EQUIVALENTS:
        text = text.replace(ch, "-")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def phrase_to_regex(phrase: str) -> Optional[str]:
    """Перетворити ключову фразу на безпечний регулярний вираз.

    Фраза екранується (жодного виконання вмісту документа як regex), а роздільники
    між словами стають гнучкими — щоб збігатись незалежно від пробілів, дефісів,
    слешів і переносів рядків.
    """
    if not phrase:
        return None
    tokens = [tok for tok in re.split(_SEPARATOR_RUN, phrase.strip()) if tok]
    if not tokens:
        return None
    body = _SEPARATOR_CLASS + "*"
    return body.join(re.escape(tok) for tok in tokens)


def load_records(path: Optional[str] = None) -> List[Dict[str, object]]:
    """Прочитати та провалідувати всі записи бази знань із JSON.

    Піднімає :class:`ValueError` з деталями, якщо структура некоректна.
    """
    path = path or kb_path()
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    if isinstance(data, dict):
        records = data.get("records")
        source_default = data.get("source", DEFAULT_SOURCE)
    else:
        records = data
        source_default = DEFAULT_SOURCE

    if not isinstance(records, list):
        raise ValueError("knowledge_base.json: очікується список 'records'")

    validated: List[Dict[str, object]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"knowledge_base.json: запис #{index} не є об'єктом")
        patterns = record.get("patterns")
        if not isinstance(patterns, list) or not patterns or not all(
            isinstance(p, str) and p.strip() for p in patterns
        ):
            raise ValueError(
                f"knowledge_base.json: запис #{index} має некоректне поле 'patterns'"
            )
        entry = {
            "id": str(record.get("id") or f"kb-{index + 1:03d}"),
            "patterns": [p.strip() for p in patterns],
            "component": str(record.get("component") or ""),
            "notes": str(record.get("notes") or ""),
            "models": [str(m) for m in (record.get("models") or [])],
            "source": str(record.get("source") or source_default),
            "severity": str(record.get("severity") or "warning"),
            "ambiguous": bool(record.get("ambiguous", False)),
            "generic": bool(record.get("generic", False)),
        }
        validated.append(entry)
    return validated


def compile_rules(records: Optional[List[Dict[str, object]]] = None) -> List[Dict[str, object]]:
    """Скомпілювати записи у правила, сумісні з рушієм PanicIF.

    Дія не дублює рушій: результат має ті самі поля, що й наявна база
    (``pattern``/``keyword``/``component``/``recommendation``/``severity``/
    ``notes``), плюс метадані (``kb_id``/``source``/``models``/``generic``/
    ``ambiguous``) і маркер ``normalized`` (шукати в нормалізованому тексті).
    """
    records = records if records is not None else load_records()
    rules: List[Dict[str, object]] = []
    for record in records:
        regexes = [r for r in (phrase_to_regex(p) for p in record["patterns"]) if r]
        if not regexes:
            continue
        rules.append(
            {
                "pattern": "|".join(regexes),
                "keyword": record["patterns"][0],
                "component": record["component"],
                "recommendation": "",
                "severity": record["severity"],
                "notes": record["notes"],
                "kb_id": record["id"],
                "source": record["source"],
                "models": record["models"],
                "generic": record["generic"],
                "ambiguous": record["ambiguous"],
                "normalized": True,
            }
        )
    return rules


__all__ = [
    "KB_FILENAME",
    "DEFAULT_SOURCE",
    "kb_path",
    "normalize_text",
    "phrase_to_regex",
    "load_records",
    "compile_rules",
]
