"""
Cache-related stuff.
"""

import asyncio
import os
import posixpath
import urllib.parse
from pathlib import Path
from typing import Any, Optional

import aiohttp
import appdirs


def cache_dir(pkg: str) -> Path:
    a = pkg[:2]
    b = pkg[2:4] or "--"
    return Path(a, b, pkg)


DEFAULT_CACHE_DIR = os.path.join(
    appdirs.user_cache_dir("honesty", "python-packaging"), "pypi",
)
DEFAULT_HONESTY_INDEX_URL = "https://pypi.org/simple/"
BUFFER_SIZE = 4096 * 1024  # 4M


class Cache:
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        index_url: Optional[str] = None,
        json_index_url: Optional[str] = None,
        fresh_index: bool = False,
    ) -> None:
        if not cache_dir:
            cache_dir = os.environ.get("HONESTY_CACHE", DEFAULT_CACHE_DIR)
        assert isinstance(cache_dir, str), cache_dir
        self.cache_path = Path(cache_dir).expanduser()

        if not index_url:
            index_url = os.environ.get("HONESTY_INDEX_URL", DEFAULT_HONESTY_INDEX_URL)
        assert isinstance(index_url, str), index_url
        if not index_url.endswith("/"):
            # in a browser, this would be a redirect; we don't know that here.
            index_url += "/"
        self.index_url = index_url

        if not json_index_url:
            json_index_url = os.environ.get("HONESTY_JSON_INDEX_URL", self.index_url)
        assert isinstance(json_index_url, str), json_index_url
        if not json_index_url.endswith("/"):
            index_url += "/"
        self.json_index_url = index_url

        self.fresh_index = fresh_index
        self.session = aiohttp.ClientSession(trust_env=True, raise_for_status=True)

    def fetch(self, pkg: str, url: Optional[str]) -> Path:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.async_fetch(pkg, url))

    async def async_fetch(self, pkg: str, url: Optional[str]) -> Path:
        """
        When url=None, download the index.
        Otherwise, download (presumably) an archive.  url may be relative, and
        is presumably relative to the package index page.

        When self.fresh_index, never trust the cache for index (but still save).

        Returns a Path for where the cache wanted to save it.  We make effort to
        be concurrent-safe (last one wins).
        """

        # Because parse_index doesn't understand entities, there are some urls
        # that we currently get that we shouldn't bother fetching.
        if "&" in pkg or "#" in pkg:
            raise NotImplementedError("parse_index does not handle entities yet")

        pkg_url = urllib.parse.urljoin(self.index_url, f"{pkg}/")
        if url is None:
            url = pkg_url
        else:
            # pypi simple gives full urls, but if your mirror gives relative ones,
            # it's relative to the package's index page (which has trailing slash)
            url = urllib.parse.urljoin(pkg_url, url)

        filename = posixpath.basename(url)

        output_dir = self.cache_path / cache_dir(pkg)
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / (filename or "index.html")

        if not output_file.exists() or (
            self.fresh_index and self._is_index_filename(filename)
        ):
            async with self.session.get(
                url, raise_for_status=True, timeout=None
            ) as resp:
                tmp = f"{output_file}.{os.getpid()}"
                with open(tmp, "wb") as f:
                    async for chunk in resp.content.iter_any():
                        f.write(chunk)
                # Last-writer-wins semantics
                os.rename(tmp, output_file)

        return output_file

    def _is_index_filename(self, name: Optional[str]) -> bool:
        return name in (None, "json")

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.session.close())

    async def __aenter__(self) -> "Cache":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        await self.session.close()
