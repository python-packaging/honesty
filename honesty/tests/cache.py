import posixpath
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from unittest import mock

from honesty.cache import Cache


class AiohttpStreamMock:
    def __init__(self, content: bytes):
        self._content = content

    # TODO async iterable[bytes]
    async def iter_any(self) -> Any:
        yield self._content


class AiohttpResponseMock:
    def __init__(self, content: bytes):
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

            raise NotImplementedError(url)

        with Cache(index_url="https://pypi.org/simple/", cache_dir=d) as cache:

            with mock.patch.object(cache.session, "get", side_effect=get_side_effect):
                rv = cache.fetch("projectname", url=None)
                self.assertTrue(rv.exists(), rv)
                self.assertEqual(f"{d}/pr/oj/projectname/index.html", str(rv))
                rv = cache.fetch("projectname", url=None)
                self.assertEqual(f"{d}/pr/oj/projectname/index.html", str(rv))
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
