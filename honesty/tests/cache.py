import asyncio
import os.path
import posixpath
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from unittest import mock

from ..cache import Cache


class AiohttpStreamMock:
    def __init__(self, content: bytes) -> None:
        self._content = content

    # TODO async iterable[bytes]
    async def iter_any(self) -> Any:
        yield self._content


class AiohttpResponseMock:
    def __init__(self, content: bytes) -> None:
        self.content = AiohttpStreamMock(content)

    async def __aenter__(self) -> "AiohttpResponseMock":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


class FakeCache:
    def __init__(
        self, path: str, url_to_contents: Dict[Tuple[str, Optional[str]], bytes]
    ) -> None:
        self.path: Path = Path(path)
        self.url_to_contents = url_to_contents
        self.json_index_url = "https://pypi.org/simple/"

    async def async_fetch(self, package_name: str, url: Optional[str] = None) -> Path:
        basename = posixpath.basename(url) if url else f"{package_name}_index.html"
        with open(self.path / basename, "wb") as f:
            f.write(self.url_to_contents[(package_name, url)])

        return self.path / basename


class CacheTest(unittest.TestCase):
    def test_fetch_caches(self) -> None:
        d = tempfile.mkdtemp()

        def get_side_effect(
            url: str, raise_for_status: bool = False, timeout: Any = None
        ) -> AiohttpResponseMock:
            if url == "https://example.com/other":
                return AiohttpResponseMock(b"other")
            elif url == "https://pypi.org/a/relpath":
                return AiohttpResponseMock(b"relpath")
            elif url == "https://pypi.org/simple/projectname/":
                return AiohttpResponseMock(b"foo")

            raise NotImplementedError(url)  # pragma: no cover

        with Cache(index_url="https://pypi.org/simple/", cache_dir=d) as cache:
            with mock.patch.object(cache.session, "get", side_effect=get_side_effect):
                rv = cache.fetch("projectname", url=None)
                self.assertTrue(rv.exists(), rv)
                self.assertEqual(
                    os.path.join(d, "pr", "oj", "projectname", "index.html"), str(rv)
                )
                rv = cache.fetch("projectname", url=None)
                self.assertEqual(
                    os.path.join(d, "pr", "oj", "projectname", "index.html"), str(rv)
                )
                # TODO mock_get.assert_called_once()
                with rv.open() as f:
                    self.assertEqual("foo", f.read())

                # Absolute path url support
                rv = cache.fetch("projectname", url="https://example.com/other")
                with rv.open() as f:
                    self.assertEqual("other", f.read())

                # Relative path support
                rv = cache.fetch("projectname", url="../../a/relpath")
                with rv.open() as f:
                    self.assertEqual("relpath", f.read())

    @mock.patch("honesty.cache.os.environ.get")
    def test_cache_env_vars(self, mock_get: Any) -> None:
        mock_get.side_effect = {
            "HONESTY_CACHE": "/tmp",
            "HONESTY_INDEX_URL": "https://example.com/foo",
        }.get
        with Cache() as cache:
            self.assertEqual(Path("/tmp"), cache.cache_path)
            self.assertEqual("https://example.com/foo/", cache.index_url)

    def test_cache_invalid(self) -> None:
        with Cache() as cache:
            with self.assertRaises(NotImplementedError):
                # I no longer remember which project triggers this; in theory
                # all non-[a-z0-9-] should have been canonicalized away already.
                cache.fetch("pb&amp;j", url=None)

    def test_aenter(self) -> None:
        async def inner() -> None:
            async with Cache() as cache:
                self.assertTrue(cache)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(inner())

    def test_is_index(self) -> None:
        with Cache() as cache:
            self.assertTrue(cache._is_index_filename(""))
            self.assertTrue(cache._is_index_filename("json"))
            self.assertFalse(cache._is_index_filename("foo-0.1.tar.gz"))
