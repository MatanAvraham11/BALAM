"""Regression tests for environment-aware auth cookie security."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

_ROOT = Path(__file__).resolve().parents[2]
_API = _ROOT / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from index import _secure_auth_cookie  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
