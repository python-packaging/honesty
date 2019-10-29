import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests
import requests_mock

import honesty.cache


class CacheTest(unittest.TestCase):
    @mock.patch("honesty.cache.CACHE_PATH")
    @mock.patch("honesty.cache.SESSION")
    @mock.patch("honesty.cache.MIRROR_BASE", "mock://pypi.org/simple/")
    def test_fetch_caches(self, unused_mock_cache_path, unused_mock_session):
        session = requests.Session()
        adapter = requests_mock.Adapter()
        session.mount("mock", adapter)
        honesty.cache.SESSION = session

        adapter.register_uri(
            "GET", "mock://pypi.org/simple/projectname/", content=b"foo"
        )

        d = tempfile.mkdtemp()
        honesty.cache.CACHE_PATH = Path(d)

        rv = honesty.cache.fetch("projectname")
        self.assertTrue(rv.exists(), rv)
        self.assertEqual(f"{d}/pr/oj/projectname/index.html", str(rv))
        rv = honesty.cache.fetch("projectname")
        self.assertEqual(f"{d}/pr/oj/projectname/index.html", str(rv))
        # TODO mock_get.assert_called_once()
        with rv.open() as f:
            self.assertEqual("foo", f.read())
