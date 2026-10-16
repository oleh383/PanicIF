# -*- coding: utf-8 -*-
"""Точка входу PanicIF Bot.

Команди: /start, /help. Окрім цього бот приймає:
    * документи з panic-логами (.ips/.panic/.txt/.log);
    * фотографії та зображення JPG/JPEG/PNG (як фото або як документ),
      текст із яких розпізнається наявним OCR-рушієм PanicIF.

Усе аналізується наявним діагностичним ядром PanicIF. Завантажені файли та
розпізнаний текст не зберігаються. PDF/оплата не використовуються.

Обмеження навантаження:
    * одночасні важкі операції обмежено (:data:`MAX_CONCURRENT_ANALYSES`);
    * є ліміт частоти запитів на користувача (:class:`bot.services.limits.RateLimiter`);
    * важкі операції виконуються у службовому потоці з таймаутом.

Запуск (Windows PowerShell)::

    python -m bot.main

Токен задається лише через змінну середовища ``TELEGRAM_BOT_TOKEN``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import threading
import weakref
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import HELP_MESSAGE, START_MESSAGE, UNKNOWN_MESSAGE
from bot.config import BotConfigError, require_bot_token
from bot.services import analyzer
from bot.services.limits import RateLimiter

logger = logging.getLogger(__name__)

# Максимум одночасних важких операцій (аналіз логів / OCR) та ліміт їх часу.
MAX_CONCURRENT_ANALYSES = 2
ANALYSIS_TIMEOUT_SECONDS = 120.0

# Мінімальний HTTP health-сервер для Render: Web Service вважається живим лише
# коли відкрито мережевий порт. Порт береться зі змінної середовища PORT.
PORT_ENV_VAR = "PORT"
DEFAULT_HTTP_PORT = 10000
HTTP_HOST = "0.0.0.0"

# Ковзний ліміт частоти важких запитів на користувача (у пам'яті, без БД).
_rate_limiter = RateLimiter()

# Семафор створюється окремо для кожного event loop (щоб не ламати тести, які
# використовують новий loop на кожен тест).
_semaphores: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def configure_logging() -> None:
    """Налаштувати логування без токенів і приватного вмісту повідомлень."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    # Менш "балакучі" сторонні логери.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.INFO)


def _load_dotenv_if_available() -> None:
    """Необов'язково підтягнути локальний .env, якщо встановлено python-dotenv."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _resolve_http_port(default: int = DEFAULT_HTTP_PORT) -> int:
    """Порт для health-сервера зі змінної середовища ``PORT``.

    Якщо ``PORT`` не задано або має некоректне значення — повертається
    ``default`` (типово :data:`DEFAULT_HTTP_PORT`).
    """
    raw = os.environ.get(PORT_ENV_VAR, "").strip()
    if not raw:
        return default
    try:
        port = int(raw)
    except ValueError:
        logger.warning("%s=«%s» некоректний — використовую %s", PORT_ENV_VAR, raw, default)
        return default
    if not 0 <= port <= 65535:
        logger.warning("%s=%s поза діапазоном — використовую %s", PORT_ENV_VAR, port, default)
        return default
    return port


class _HealthHandler(BaseHTTPRequestHandler):
    """Мінімальний обробник: 200 OK на будь-який GET/HEAD (перевірка порту)."""

    def do_GET(self) -> None:  # noqa: N802 — ім'я вимагає BaseHTTPRequestHandler
        body = b"PanicIF Bot is running."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:  # noqa: N802 — ім'я вимагає BaseHTTPRequestHandler
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        logger.debug("HTTP health-check %s", format % args)


def start_http_server(port: int | None = None) -> ThreadingHTTPServer:
    """Запустити HTTP health-сервер у daemon-потоці (для Render).

    Render надає порт через змінну середовища ``PORT`` і вважає Web Service
    живим лише коли цей порт відкрито. Сервер не виконує жодної логіки бота —
    лише відповідає ``200 OK``. Повертає запущений сервер (потрібно для
    коректного завершення/тестів).
    """
    if port is None:
        port = _resolve_http_port()
    server = ThreadingHTTPServer((HTTP_HOST, port), _HealthHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="panicif-health-http",
        daemon=True,
    )
    thread.start()
    logger.info("HTTP health-сервер слухає http://%s:%s", HTTP_HOST, server.server_address[1])
    return server


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відповідь на команду /start."""
    if update.message is None:
        return
    await update.message.reply_text(START_MESSAGE)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відповідь на команду /help."""
    if update.message is None:
        return
    await update.message.reply_text(HELP_MESSAGE)


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відповідь на будь-який невідомий текст."""
    if update.message is None:
        return
    await update.message.reply_text(UNKNOWN_MESSAGE)


async def on_error(update, context) -> None:
    """Глобальний обробник помилок: лог без секретів + безпечна відповідь.

    Технічні подробиці (traceback) пишуться ЛИШЕ в журнал. Користувачу
    надсилається узагальнене повідомлення без внутрішніх деталей.
    """
    logger.error(
        "Необроблена помилка під час обробки оновлення",
        exc_info=context.error,
    )
    message = getattr(update, "effective_message", None) if update is not None else None
    if message is None and update is not None:
        message = getattr(update, "message", None)
    if message is None:
        return
    with contextlib.suppress(Exception):
        await message.reply_text(analyzer.GENERIC_ERROR_MESSAGE)


def _user_key(message):
    """Ідентифікатор користувача для ліміту частоти (або ``None``)."""
    user = getattr(message, "from_user", None)
    if user is not None and getattr(user, "id", None) is not None:
        return user.id
    return getattr(message, "chat_id", None)


def _rate_limit_ok(message) -> bool:
    """Чи не перевищено ліміт запитів для користувача.

    Якщо користувача неможливо визначити — запит не обмежується.
    """
    key = _user_key(message)
    if key is None:
        return True
    allowed, _retry_after = _rate_limiter.allow(key)
    return allowed


def _get_analysis_semaphore() -> asyncio.Semaphore:
    """Повернути семафор обмеження одночасних операцій для поточного loop."""
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSES)
        _semaphores[loop] = semaphore
    return semaphore


async def _run_blocking(func, *args):
    """Виконати важку синхронну функцію у потоці з обмеженням часу.

    Зауваження: ``asyncio.wait_for`` не може безпечно перервати вже запущений
    потік — після таймауту потік догодить у фоні, але event loop не блокується.
    """
    return await asyncio.wait_for(
        asyncio.to_thread(func, *args),
        timeout=ANALYSIS_TIMEOUT_SECONDS,
    )


async def _send_report(message, summary: str, report_text: str) -> None:
    """Надіслати звіт: повідомленням, або TXT-файлом, якщо завеликий."""
    payload = f"{summary}\n\n{report_text}"
    if len(payload) <= analyzer.MAX_MESSAGE_LENGTH:
        await message.reply_text(payload)
        return

    buffer = BytesIO(report_text.encode("utf-8"))
    await message.reply_document(
        document=buffer,
        filename=analyzer.REPORT_FILENAME,
        caption=summary[: analyzer.MAX_CAPTION_LENGTH],
    )


async def _download_telegram_file(telegram_file) -> bytes:
    """Завантажити вміст файлу Telegram у байти (у службовому потоці не потрібно)."""
    return bytes(await telegram_file.download_as_bytearray())


async def _process_image(message, data: bytes, file_name: str) -> None:
    """Спільна обробка зображення: OCR наявним рушієм PanicIF + аналіз.

    OCR виконується у службовому потоці, щоб не блокувати event loop бота.
    """
    try:
        analysis = await _run_blocking(
            analyzer.analyze_image_bytes, data, file_name
        )
    except (asyncio.TimeoutError, TimeoutError):
        await message.reply_text(analyzer.TIMEOUT_MESSAGE)
        return
    except analyzer.OcrUnavailableError as exc:
        await message.reply_text(str(exc))
        return
    except analyzer.UnsupportedImageError as exc:
        await message.reply_text(str(exc))
        return
    except analyzer.AnalyzerError as exc:
        await message.reply_text(str(exc))
        return
    except Exception:  # noqa: BLE001 — жодна помилка OCR не валить бот
        logger.exception("Помилка OCR/аналізу зображення")
        await message.reply_text(analyzer.ANALYSIS_ERROR_MESSAGE)
        return

    if not analysis.text:
        await message.reply_text(analyzer.OCR_NO_TEXT_MESSAGE)
        return

    if analysis.report is None or not analysis.report.findings:
        await message.reply_text(analyzer.summarize_photo(analysis))
        return

    try:
        summary = analyzer.summarize_photo(analysis)
        report_text = analyzer.build_report_text(analysis.report)
    except Exception:  # noqa: BLE001 — помилка формування звіту не валить бот
        logger.exception("Помилка формування звіту для зображення")
        await message.reply_text(analyzer.ANALYSIS_ERROR_MESSAGE)
        return
    await _send_report(message, summary, report_text)


async def _process_log(message, data: bytes, file_name: str) -> None:
    """Спільна обробка panic-логу: аналіз у потоці + надсилання звіту."""
    try:
        report = await _run_blocking(analyzer.analyze_log_bytes, data, file_name)
    except (asyncio.TimeoutError, TimeoutError):
        await message.reply_text(analyzer.TIMEOUT_MESSAGE)
        return
    except analyzer.AnalyzerError as exc:
        await message.reply_text(str(exc))
        return
    except Exception:  # noqa: BLE001 — будь-яка помилка аналізу не валить бот
        logger.exception("Помилка під час аналізу документа")
        await message.reply_text(analyzer.ANALYSIS_ERROR_MESSAGE)
        return

    if report is None:
        await message.reply_text(analyzer.NON_PANIC_MESSAGE)
        return

    try:
        summary = analyzer.summarize(report)
        report_text = analyzer.build_report_text(report)
    except Exception:  # noqa: BLE001 — помилка формування звіту не валить бот
        logger.exception("Помилка формування звіту для логу")
        await message.reply_text(analyzer.ANALYSIS_ERROR_MESSAGE)
        return
    await _send_report(message, summary, report_text)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробити надісланий документ: panic-лог або зображення.

    Приймає .ips/.panic/.txt/.log та зображення JPG/JPEG/PNG. Тип перевіряється
    і за розширенням, і за вмістом (сигнатура/парсинг). Файли не зберігаються.
    """
    message = update.message
    if message is None or message.document is None:
        return

    document = message.document
    file_name = document.file_name or ""

    is_image = analyzer.is_supported_image_extension(file_name)
    is_log = analyzer.is_supported_extension(file_name)

    if not is_image and not is_log:
        await message.reply_text(analyzer.UNSUPPORTED_EXTENSION_MESSAGE)
        return

    if not _rate_limit_ok(message):
        await message.reply_text(analyzer.RATE_LIMIT_MESSAGE)
        return

    limit = analyzer.MAX_IMAGE_UPLOAD_BYTES if is_image else analyzer.MAX_UPLOAD_BYTES
    too_large = (
        analyzer.TOO_LARGE_IMAGE_MESSAGE if is_image else analyzer.TOO_LARGE_MESSAGE
    )

    if document.file_size is not None and document.file_size > limit:
        await message.reply_text(too_large)
        return

    logger.info("Отримано документ для аналізу")
    try:
        telegram_file = await document.get_file()
        data = await _download_telegram_file(telegram_file)
    except Exception:  # noqa: BLE001 — не валимо бот через помилку завантаження
        logger.warning("Не вдалося завантажити документ із Telegram")
        await message.reply_text(analyzer.READ_ERROR_MESSAGE)
        return

    if len(data) > limit:
        await message.reply_text(too_large)
        return

    semaphore = _get_analysis_semaphore()
    if semaphore.locked():
        await message.reply_text(analyzer.BUSY_MESSAGE)
        return
    await semaphore.acquire()
    try:
        if is_image:
            await _process_image(message, data, file_name)
        else:
            await _process_log(message, data, file_name)
    finally:
        semaphore.release()


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробити фотографію, надіслану як фото.

    Обирається найбільша версія, перевіряється розмір, файл завантажується у
    тимчасову директорію й розпізнається наявним OCR-рушієм PanicIF.
    """
    message = update.message
    if message is None or not message.photo:
        return

    if not _rate_limit_ok(message):
        await message.reply_text(analyzer.RATE_LIMIT_MESSAGE)
        return

    photo = max(message.photo, key=lambda item: item.file_size or 0)

    if photo.file_size is not None and photo.file_size > analyzer.MAX_IMAGE_UPLOAD_BYTES:
        await message.reply_text(analyzer.TOO_LARGE_IMAGE_MESSAGE)
        return

    logger.info("Отримано фото для OCR-аналізу")
    try:
        telegram_file = await photo.get_file()
        data = await _download_telegram_file(telegram_file)
    except Exception:  # noqa: BLE001 — не валимо бот через помилку завантаження
        logger.warning("Не вдалося завантажити фото з Telegram")
        await message.reply_text(analyzer.READ_ERROR_MESSAGE)
        return

    semaphore = _get_analysis_semaphore()
    if semaphore.locked():
        await message.reply_text(analyzer.BUSY_MESSAGE)
        return
    await semaphore.acquire()
    try:
        await _process_image(message, data, "telegram_photo.jpg")
    finally:
        semaphore.release()


def build_application(token: str) -> Application:
    """Створити застосунок із зареєстрованими обробниками."""
    application = ApplicationBuilder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))
    application.add_error_handler(on_error)

    return application


async def run_bot(application: Application) -> None:
    """Асинхронно запустити бот (python-telegram-bot 21+) до сигналу зупинки.

    Явний життєвий цикл ``initialize`` → ``start`` → ``start_polling``
    використовується, коли головна функція вже виконується всередині циклу
    подій (через :func:`asyncio.run`). Updater і застосунок коректно
    зупиняються за SIGINT/SIGTERM — це важливо на сервері, де Render надсилає
    SIGTERM під час перезапуску.
    """
    await application.initialize()
    await application.start()

    updater = application.updater
    if updater is None:
        raise RuntimeError("Застосунок без Updater: polling недоступний.")
    await updater.start_polling(allowed_updates=Update.ALL_TYPES)

    stop_signal = asyncio.Event()
    loop = asyncio.get_running_loop()
    handled_signals = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_signal.set)
            handled_signals.append(sig)
        except (NotImplementedError, RuntimeError, ValueError):
            continue

    try:
        await stop_signal.wait()
    finally:
        for sig in handled_signals:
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.remove_signal_handler(sig)
        await updater.stop()
        await application.stop()
        await application.shutdown()


def main() -> None:
    """Точка входу: налаштувати логування, перевірити токен і запустити бот."""
    configure_logging()
    _load_dotenv_if_available()

    try:
        token = require_bot_token()
    except BotConfigError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    logger.info("Запуск PanicIF Bot…")
    start_http_server()
    application = build_application(token)
    asyncio.run(run_bot(application))


if __name__ == "__main__":
    main()
