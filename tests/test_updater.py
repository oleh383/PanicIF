# -*- coding: utf-8 -*-
"""Тести системи оновлення PanicIF (module app/updater.py).

Вимоги (з технічного завдання):
  1) current 1.0.0, latest 1.0.0 -> оновлення НЕМАЄ.
  2) current 1.0.0, latest 1.1.0 -> оновлення доступне.
  3) current 1.1.0, latest 1.0.0 -> downgrade НЕ пропонується.
  4) latest tag "v1.1.0" -> визначається як 1.1.0.
  5) release без PanicIF-Setup.exe -> оновлення не запускається.
  6) HTTP timeout -> PanicIF не зависає (помилка, а не блок).
  7) Неправильний JSON -> updater не падає (підняття UpdaterError).
  8) Завантажений файл порожній -> installer не запускається.
  9) SHA-256 не збігається -> installer не запускається.
 10) Відсутній Інтернет -> програма продовжує працювати (помилка catchable).
"""
import importlib.util
import os
import socket
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPDIR = os.path.join(PROJECT_ROOT, "app")

_spec = importlib.util.spec_from_file_location("updater", os.path.join(APPDIR, "updater.py"))
UPD = importlib.util.module_from_spec(_spec)
sys.modules["updater"] = UPD
_spec.loader.exec_module(UPD)


class FakeResp:
    """Мінімальна HTTP-відповідь, сумісна з urllib urlopen."""

    def __init__(self, body=b"", headers=None):
        self._body = body or b""
        self.headers = {"Content-Length": str(len(self._body))}
        if headers:
            self.headers.update(headers)
        self._consumed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args, **kwargs):
        if self._consumed:
            return b""
        self._consumed = True
        return self._body


class VersionComparisonTests(unittest.TestCase):
    def test_equal_versions_no_update(self):
        self.assertFalse(UPD.is_update_available("1.0.0", "1.0.0"))

    def test_new_patch_version_available(self):
        self.assertTrue(UPD.is_update_available("1.0.0", "1.0.1"))

    def test_new_minor_version_available(self):
        self.assertTrue(UPD.is_update_available("1.0.0", "1.1.0"))

    def test_new_major_version_available(self):
        self.assertTrue(UPD.is_update_available("1.1.0", "2.0.0"))

    def test_downgrade_not_offered(self):
        self.assertFalse(UPD.is_update_available("1.1.0", "1.0.0"))

    def test_v_prefix_normalized(self):
        self.assertEqual(UPD.normalize_tag("v1.1.0"), "1.1.0")
        self.assertEqual(UPD.parse_version("v1.1.0"), (1, 1, 0))
        self.assertTrue(UPD.is_update_available("1.0.0", "v1.1.0"))
        self.assertEqual(UPD.compare_versions("v1.1.0", "1.0.0"), 1)

    def test_semver_not_lexicographic(self):
        self.assertEqual(UPD.compare_versions("1.0.9", "1.0.10"), -1)
        self.assertTrue(UPD.is_update_available("1.0.9", "1.0.10"))
        self.assertEqual(UPD.compare_versions("1.0.10", "1.0.9"), 1)

    def test_messy_version_parts_do_not_crash(self):
        self.assertEqual(UPD.parse_version("v"), (0, 0, 0))
        self.assertFalse(UPD.is_update_available("1.0.0", ""))


class ReleaseParsingTests(unittest.TestCase):
    def test_tag_required(self):
        with self.assertRaises(UPD.UpdaterDataError):
            UPD.get_latest_tag({})

    def test_tag_stripped_of_v(self):
        self.assertEqual(UPD.get_latest_tag({"tag_name": "v1.1.0"}), "1.1.0")

    def test_missing_installer_asset(self):
        release = {
            "tag_name": "1.0.0",
            "assets": [
                {"name": "Source code (zip)", "browser_download_url": "https://github.com/a/b/arch.zip"},
                {"name": "Source code (tar.gz)", "browser_download_url": "https://github.com/a/b/arch.tar.gz"},
            ],
        }
        self.assertIsNone(UPD.get_installer_asset(release))

    def test_installer_asset_found_by_exact_name(self):
        release = {
            "tag_name": "1.1.0",
            "assets": [
                {"name": "PanicIF-Setup.exe", "browser_download_url": "https://github.com/x/y/releases/download/v1.1.0/PanicIF-Setup.exe"},
                {"name": "Source code (zip)", "browser_download_url": "https://github.com/a/b/arch.zip"},
            ],
        }
        asset = UPD.get_installer_asset(release)
        self.assertIsNotNone(asset)
        self.assertEqual(asset["name"], "PanicIF-Setup.exe")

    def test_digest_asset_lookup(self):
        release = {"assets": [{"name": "PanicIF-Setup.exe.sha256", "browser_download_url": "https://github.com/x/y"}]}
        self.assertEqual(UPD.get_digest_asset(release)["name"], "PanicIF-Setup.exe.sha256")
        self.assertIsNone(UPD.get_digest_asset({"assets": []}))


class NetworkTests(unittest.TestCase):
    def test_timeout_raises_friendly_error(self):
        with mock.patch("updater.urllib.request.urlopen", side_effect=socket.timeout("timed out")):
            with self.assertRaises(UPD.UpdaterNetworkError):
                UPD.fetch_latest_release(timeout=1)

    def test_no_internet_raises_friendly_error_and_no_crash(self):
        exc = OSError("No route to host")
        with mock.patch("updater.urllib.request.urlopen", side_effect=exc):
            try:
                UPD.fetch_latest_release(timeout=1)
            except UPD.UpdaterNetworkError as err:
                self.assertTrue(str(err))
            else:
                self.fail("Очікував UpdaterNetworkError")

    def test_invalid_json_does_not_crash(self):
        with mock.patch("updater.urllib.request.urlopen", return_value=FakeResp(b"definitely not json")):
            with self.assertRaises(UPD.UpdaterDataError):
                UPD.fetch_latest_release(timeout=1)

    def test_http_404(self):
        with mock.patch("updater.urllib.request.urlopen", side_effect=urllib.error.HTTPError("/", 404, "NF", {}, None)):
            with self.assertRaises(UPD.UpdaterServerError):
                UPD.fetch_latest_release(timeout=1)

    def test_http_403_rate_limit_message(self):
        with mock.patch("updater.urllib.request.urlopen", side_effect=urllib.error.HTTPError("/", 403, "Forbidden", {}, None)):
            with self.assertRaisesRegex(UPD.UpdaterServerError, "обмежив"):
                UPD.fetch_latest_release(timeout=1)

    def test_no_internet_app_keeps_working(self):
        # Основна програма не залежить від GitHub: перевірка викликається ОНОВЛЕННЯМ,
        # а помилка — catchable, без аварійного завершення.
        with mock.patch("updater.urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(UPD.UpdaterNetworkError):
                UPD.fetch_latest_release(timeout=1)


class DownloadTests(unittest.TestCase):
    def test_empty_file_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("updater.urllib.request.urlopen", return_value=FakeResp(b"", {"Content-Length": "0"})):
                with self.assertRaisesRegex(UPD.UpdaterDataError, "порожній"):
                    UPD.download_asset("https://github.com/x/PanicIF-Setup.exe", dest_dir=td)

    def test_non_github_url_rejected_before_open(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("updater.urllib.request.urlopen") as mu:
                with self.assertRaises(UPD.UpdaterDataError):
                    UPD.download_asset("http://evil.example.com/PanicIF-Setup.exe", dest_dir=td)
                mu.assert_not_called()

    def test_successful_download_writes_file_and_progress(self):
        payload = b"x" * 100
        progress = []
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("updater.urllib.request.urlopen", return_value=FakeResp(payload, {"Content-Length": "100"})):
                path = UPD.download_asset(
                    "https://github.com/x/PanicIF-Setup.exe",
                    dest_dir=td,
                    progress_callback=lambda g, t: progress.append((g, t)),
                )
            self.assertEqual(os.path.basename(path), "PanicIF-Setup.exe")
            self.assertEqual(os.path.getsize(path), 100)
        self.assertEqual(progress, [(100, 100)])

    def test_sha256_digest_matches(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "PanicIF-Setup.exe")
            with open(path, "wb") as fh:
                fh.write(b"abc")
            good = UPD.sha256_of_file(path)
            self.assertIsNone(UPD.digest_matches(path, None))
            self.assertIsNone(UPD.digest_matches(path, ""))
            self.assertTrue(UPD.digest_matches(path, good))
            self.assertFalse(UPD.digest_matches(path, "0" * 64))

    def test_fetch_digest_parses_hex(self):
        digest = "d41d8cd98f00b204e9800998ecf8427e" + "0" * 32
        with mock.patch("updater.urllib.request.urlopen", return_value=FakeResp(f"{digest}  PanicIF-Setup.exe\n".encode())):
            self.assertEqual(UPD.fetch_digest("https://github.com/x/PanicIF-Setup.exe.sha256"), digest)

    def test_launch_installer_rejects_missing_file(self):
        with self.assertRaises(UPD.UpdaterError):
            UPD.launch_installer(os.path.join(tempfile.gettempdir(), "no_such_PanicIF-Setup.exe"))


if __name__ == "__main__":
    unittest.main()