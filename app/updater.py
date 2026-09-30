#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка та встановлення оновлень PanicIF через GitHub Releases.

Модуль навмисно використовує ЛИШЕ стандартну бібліотеку Python:
  * логіку можна тестувати без Qt (чисті функції);
  * програма повністю працює офлайн — мережеві виклики робляться
    поза UI-потоком (див. UpdateCheckWorker / UpdateDownloadWorker
    у app/iphone_panic_diagnostics.py);
  * жодних токенів/паролів/секретів у коді немає — GitHub REST API
    використовується анонімно.

Джерело оновлень:
  https://api.github.com/repos/oleh383/PanicIF/releases/latest
"""

import hashlib
import hmac
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

GITHUB_API_LATEST = "https://api.github.com/repos/oleh383/PanicIF/releases/latest"
INSTALLER_ASSET_NAME = "PanicIF-Setup.exe"
DIGEST_ASSET_NAMES = ("PanicIF-Setup.exe.sha256", "SHA256SUMS")
USER_AGENT = "PanicIF-Updater"
DOWNLOAD_CHUNK = 64 * 1024


class UpdaterError(Exception):
    """Батьківський клас дружніх помилок модуля оновлення."""


class UpdaterNetworkError(UpdaterError):
    """Немає Інтернету або таймаут."""


class UpdaterServerError(UpdaterError):
    """GitHub/сервер недоступний, HTTP-помилка, rate limit."""


class UpdaterDataError(UpdaterError):
    """Неочікувані/пошкоджені дані (bad JSON, бракує tag_name/asset...)."""


class UpdaterIntegrityError(UpdaterError):
    """Порушення цілісності завантаженого файлу (SHA-256 не збігся)."""


# ---------------------------------------------------------------------------
# Семантичне порівняння версій
# ---------------------------------------------------------------------------
def normalize_tag(tag):
    """Прибирає початкову 'v'/'V' із tag (напр. 'v1.1.0' -> '1.1.0')."""
    s = (tag or "").strip()
    if len(s) > 1 and s[0].lower() == "v":
        s = s[1:].strip()
    return s


def parse_version(version):
    """'1.0.0' / 'v1.1.0' -> кортеж (1, 0, 0). Криві частини -> 0."""
    v = normalize_tag(version)
    nums = []
    for part in v.split("."):
        m = re.match(r"(\d+)", part.strip())
        nums.append(int(m.group(1)) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def compare_versions(a, b):
    """Порівнює версії семантично: 1.0.0 < 1.1.0, 1.0.9 < 1.0.10."""
    ta, tb = parse_version(a), parse_version(b)
    if ta > tb:
        return 1
    if ta < tb:
        return -1
    return 0


def is_update_available(current_version, latest_tag):
    """True, якщо latest НОВІША за встановлену. Downgrade/рівність -> False."""
    return compare_versions(latest_tag, current_version) > 0


# ---------------------------------------------------------------------------
# Робота зі структурою GitHub release
# ---------------------------------------------------------------------------
def get_latest_tag(release):
    """Дістає tag_name з release та нормалізує його (без 'v')."""
    if not isinstance(release, dict):
        raise UpdaterDataError("Випуск оновлення має неочікуваний формат.")
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise UpdaterDataError("У випуску оновлення немає tag_name.")
    return normalize_tag(tag)


def find_asset(release, asset_name):
    """Шукає asset з ТОЧНИМ ім'ям, повертає dict або None."""
    assets = release.get("assets") if isinstance(release, dict) else None
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if asset.get("name") == asset_name:
            url = asset.get("browser_download_url")
            if isinstance(url, str) and url.strip():
                return asset
    return None


def get_installer_asset(release):
    """Повертає asset 'PanicIF-Setup.exe' або None (не чіпаємо source zip)."""
    return find_asset(release, INSTALLER_ASSET_NAME)


def get_digest_asset(release):
    """Шукає asset з SHA-256 (PanicIF-Setup.exe.sha256 або SHA256SUMS)."""
    for name in DIGEST_ASSET_NAMES:
        asset = find_asset(release, name)
        if asset:
            return asset
    return None


def _is_github_download_url(url):
    """Безпека: дозволяємо ТІЛЬКИ GitHub-джерела завантаження."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return False
    return (
        host == "github.com"
        or host.endswith(".github.com")
        or host.endswith("githubusercontent.com")
    )


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _http_get_json(url, timeout):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        code = exc.code
        if code in (403, 429):
            raise UpdaterServerError(
                "GitHub обмежив кількість запитів (rate limit). Спробуйте пізніше."
            ) from exc
        if code == 404:
            raise UpdaterServerError("Випуск оновлення не знайдено.") from exc
        raise UpdaterServerError(f"Сервер оновлень повернув помилку HTTP {code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdaterNetworkError("Немає Інтернету або таймаут.") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise UpdaterDataError("Сервер оновлень повернув неочікувані дані.") from exc
    if not isinstance(data, dict):
        raise UpdaterDataError("Сервер оновлень повернув неочікувані дані.")
    return data


def fetch_latest_release(timeout=10, url=GITHUB_API_LATEST):
    """HTTP GET до GitHub REST API latest release."""
    return _http_get_json(url, timeout)


def fetch_digest(url, timeout=30):
    """Спроба дістати SHA-256 з .sha256/SHA256SUMS asset (best-effort).

    Якщо витягти не вдалося — повертає None (перевірку пропускаємо,
    жодного фіктивного значення не підставляємо).
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    for line in text.splitlines():
        m = re.search(r"([0-9a-fA-F]{64})", line)
        if m:
            return m.group(1).lower()
    return None


def download_asset(url, dest_dir=None, timeout=60, progress_callback=None):
    """Завантажує інсталятор у тимчасову директорію Windows.

    Перевіряє джерело (тільки GitHub), записує файл, перевіряє, що файл
    реально створено і не порожній. Прогрес: progress_callback(bytes, total|None).
    """
    if not url or not _is_github_download_url(url):
        raise UpdaterDataError("Некоректне джерело завантаження оновлення.")
    dest_dir = dest_dir or tempfile.gettempdir()
    dest_path = os.path.join(dest_dir, INSTALLER_ASSET_NAME)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            try:
                total = int(resp.headers.get("Content-Length", "") or 0)
            except (TypeError, ValueError):
                total = None
            with open(dest_path, "wb") as fh:
                while True:
                    buf = resp.read(DOWNLOAD_CHUNK)
                    if not buf:
                        break
                    fh.write(buf)
                    got += len(buf)
                    if progress_callback:
                        progress_callback(got, total)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdaterNetworkError("Не вдалося завантажити оновлення.") from exc
    if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0 or got == 0:
        raise UpdaterDataError("Завантажений файл порожній або пошкоджений.")
    return dest_path


# ---------------------------------------------------------------------------
# Цілісність (SHA-256)
# ---------------------------------------------------------------------------
def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            buf = fh.read(DOWNLOAD_CHUNK)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def digest_matches(path, expected_digest):
    """Порівнює SHA-256 файлу з digest.

    Якщо expected_digest відсутній (None/пустий) — повертає None
    (перевірка не проводилась, нічого не вигадуємо).
    """
    if not expected_digest:
        return None
    return hmac.compare_digest(
        sha256_of_file(path).lower(),
        str(expected_digest).strip().lower(),
    )


# ---------------------------------------------------------------------------
# Запуск інсталятора
# ---------------------------------------------------------------------------
def launch_installer(installer_path):
    """Безпечно запускає інсталятор через subprocess (без shell)."""
    if not installer_path or not os.path.isfile(installer_path):
        raise UpdaterError("Файл інсталятора не знайдено.")
    try:
        subprocess.Popen([str(installer_path)], shell=False)
    except Exception as exc:  # noqa: BLE001
        raise UpdaterError("Не вдалося запустити інсталятор оновлення.") from exc
    return True