# -*- coding: utf-8 -*-
"""Конфігурація PanicIF Bot.

Токен читається ТІЛЬКИ зі змінної середовища ``TELEGRAM_BOT_TOKEN``.
Реальний токен ніколи не зберігається у коді, файлах репозиторію чи логах.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

TOKEN_ENV_VAR = "TELEGRAM_BOT_TOKEN"


class BotConfigError(RuntimeError):
    """Помилка конфігурації бота (наприклад, відсутній токен)."""


def get_bot_token() -> str | None:
    """Повернути токен зі змінної середовища або ``None``, якщо він не заданий."""
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    return token or None


def require_bot_token() -> str:
    """Повернути токен або підняти :class:`BotConfigError` із зрозумілим текстом.

    Важливо: у повідомленнях про помилку НІКОЛИ не виводиться значення токена.
    """
    token = get_bot_token()
    if not token:
        raise BotConfigError(
            "Не задано токен бота. Встановіть змінну середовища "
            f"{TOKEN_ENV_VAR} (наприклад, у файлі .env або через "
            "$env:TELEGRAM_BOT_TOKEN=\"...\" у PowerShell)."
        )
    return token
