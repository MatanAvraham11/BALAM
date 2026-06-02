"""Regression tests for environment-aware auth cookie security."""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from starlette.requests import Request

_ROOT = Path(__file__).resolve().parents[2]
_API = _ROOT / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from index import _global_exc_handler, _read_upload_bytes, _secure_auth_cookie  # noqa: E402


def _request(*, scheme: str = "http", forwarded_proto: str | None = None) -> Request:
    headers = []
    if forwarded_proto is not None:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode("ascii")))
    return Request({
        "type": "http",
        "method": "GET",
        "scheme": scheme,
        "path": "/",
        "query_string": b"",
        "headers": headers,
        "server": ("testserver", 80),
    })


class SecureAuthCookieTests(unittest.TestCase):
    def test_local_http_cookie_is_not_secure(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(_secure_auth_cookie(_request()))

    def test_direct_https_cookie_is_secure(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(_secure_auth_cookie(_request(scheme="https")))

    def test_forwarded_https_cookie_is_secure(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(_secure_auth_cookie(_request(forwarded_proto="https")))

    def test_forwarded_http_does_not_downgrade_direct_https(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(
                _secure_auth_cookie(
                    _request(scheme="https", forwarded_proto="http"),
                )
            )

    def test_vercel_cookie_is_secure(self):
        with patch.dict("os.environ", {"VERCEL": "1"}, clear=True):
            self.assertTrue(_secure_auth_cookie(_request()))


class ApiBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_reader_accepts_file_at_limit(self):
        upload = UploadFile(file=io.BytesIO(b"abc"), filename="sample.pdf")
        with patch("index._MAX_UPLOAD_BYTES", 3):
            self.assertEqual(
                await _read_upload_bytes(upload, kind="PDF"),
                b"abc",
            )

    async def test_upload_reader_rejects_file_over_limit(self):
        upload = UploadFile(file=io.BytesIO(b"abcd"), filename="sample.pdf")
        with patch("index._MAX_UPLOAD_BYTES", 3):
            with self.assertRaises(HTTPException) as cm:
                await _read_upload_bytes(upload, kind="PDF")

        self.assertEqual(cm.exception.status_code, 413)

    async def test_upload_reader_rejects_empty_file(self):
        upload = UploadFile(file=io.BytesIO(), filename="sample.zip")
        with self.assertRaises(HTTPException) as cm:
            await _read_upload_bytes(upload, kind="ZIP")

        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(cm.exception.detail, "קובץ ZIP ריק.")

    async def test_global_exception_handler_does_not_leak_internal_error(self):
        with patch("sys.stderr", new_callable=io.StringIO):
            response = await _global_exc_handler(_request(), RuntimeError("secret"))

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            json.loads(response.body),
            {"error": "Internal server error"},
        )


if __name__ == "__main__":
    unittest.main()
