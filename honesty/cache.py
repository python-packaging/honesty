"""
Cache-related stuff.
"""

import json
import logging
import os
import posixpath
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkstemp
from typing import Any, Dict, Optional

import aiohttp
import appdirs
from indexurl import get_index_url
from keke import kev, ktrace
from requests.adapters import HTTPAdapter
from requests.sessions import Session


def cache_dir(pkg: str) -> Path:
    a = pkg[:2]
    b = pkg[2:4] or "--"
    return Path(a, b, pkg)


DEFAULT_CACHE_DIR = os.path.join(
    appdirs.user_cache_dir("honesty", "python-packaging"),
    "pypi",
)
BUFFER_SIZE = 4096 * 1024  # 4M

LOG = logging.getLogger(__name__)


@dataclass
class _Prefetch:
    url: str
    local_path: Path
    headers: Optional[Dict[str, str]]
    needs_recheck: bool


class Cache:
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        index_url: Optional[str] = None,
        json_index_url: Optional[str] = None,
        fresh_index: bool = False,
        aiohttp_client_session_kwargs: Optional[Dict[str, Any]] = None,
        sync_session: Optional[Session] = None,
    ) -> None:
        if not cache_dir:
            cache_dir = os.environ.get("HONESTY_CACHE", DEFAULT_CACHE_DIR)
        assert isinstance(cache_dir, str), cache_dir
        self.cache_path = Path(cache_dir).expanduser()

        if not index_url:
            index_url = os.environ.get("HONESTY_INDEX_URL", get_index_url())
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
        cskwargs: Dict[str, Any] = {
            "trust_env": True,
            "raise_for_status": True,
        }
        if aiohttp_client_session_kwargs is not None:
            cskwargs.update(aiohttp_client_session_kwargs)

        self._cskwargs = cskwargs
        if sync_session is None:
            sync_session = Session()
            sync_session.mount("http://", HTTPAdapter(pool_maxsize=100))
            sync_session.mount("https://", HTTPAdapter(pool_maxsize=100))
        self.sync_session = sync_session

    def _fetch_common(
        self, pkg: str, url: Optional[str], filename: Optional[str] = None
    ) -> _Prefetch:
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

        if not filename:
            filename = posixpath.basename(url)

        output_dir = self.cache_path / cache_dir(pkg)
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / (filename or "index.html")

        # Don't bother cache-freshening if a file exists under its final name.
        # If client cares about checking size and hash then it can do so.
        if output_file.exists() and not self._is_index_filename(filename or ""):
            return _Prefetch(
                url=url, local_path=output_file, headers=None, needs_recheck=False
            )

        headers = {}
        hdrs_file = output_dir / ((filename or "index.html") + ".hdrs")
        if output_file.exists():
            # If things got out of sync, we don't want to return a nonexisting
            # output_file...
            if hdrs_file.exists():
                hdrs = json.loads(hdrs_file.read_text())
                if "etag" in hdrs:
                    headers = {"If-None-Match": hdrs["etag"]}
                elif "last-modified" in hdrs:
                    headers = {"If-Modified-Since": hdrs["last-modified"]}
                # pydepot doesn't provide this yet
                # else:
                #    raise Exception(f"Unknown headers {hdrs!r}")

        # TODO what does True mean here?
        return _Prefetch(
            url=url, local_path=output_file, headers=headers, needs_recheck=True
        )

    @ktrace("pkg", "url")
    def fetch(
        self, pkg: str, url: Optional[str], filename: Optional[str] = None
    ) -> Path:
        # This duplicates the async_fetch code but using requests, for better
        # non-async support.

        pre = self._fetch_common(pkg, url, filename)
        if not pre.needs_recheck:
            LOG.debug("%s already downloaded to %s", url, pre.local_path)
            return pre.local_path

        # TODO reconsider timeout
        with kev("get", have_headers=bool(pre.headers), url=pre.url):
            resp = self.sync_session.get(
                pre.url, stream=True, headers=pre.headers, timeout=None
            )

        resp.raise_for_status()
        if resp.status_code == 304:
            assert pre.local_path.exists()
            LOG.debug("%s got 304, using %s", url, pre.local_path)
            return pre.local_path

        # TODO rethink how we write/cleanup these temp files
        (fd, name) = mkstemp(
            f".{os.getpid()}",
            prefix=pre.local_path.name,
            dir=pre.local_path.parent,
        )
        f = os.fdopen(fd, "wb")
        with kev("stream_body"):
            for chunk in resp.iter_content(1024 * 1024):
                f.write(chunk)

        f.close()

        # Last-writer-wins semantics, even on Windows
        with kev("replace"):
            os.replace(name, pre.local_path)

        headers = {}
        if "etag" in resp.headers:
            headers["etag"] = resp.headers["etag"]
        elif "last-modified" in resp.headers:
            headers["last-modified"] = resp.headers["last-modified"]
        # Don't bother with replace here, although this should happen after the
        # main file gets replaced.
        hdrs_file = Path(pre.local_path.parent, pre.local_path.name + ".hdrs")
        hdrs_file.write_text(json.dumps(headers))
        LOG.debug(
            "%s newly downloaded to %s, resp headers %s", url, pre.local_path, headers
        )

        return pre.local_path

    async def async_fetch(self, pkg: str, url: Optional[str]) -> Path:
        """
        When url=None, download the index.
        Otherwise, download (presumably) an archive.  url may be relative, and
        is presumably relative to the package index page.

        When self.fresh_index, never trust the cache for index (but still save).

        Returns a Path for where the cache wanted to save it.  We make effort to
        be concurrent-safe (last one wins).
        """

        pre = self._fetch_common(pkg, url, filename=None)
        if not pre.needs_recheck:
            LOG.debug("%s already downloaded to %s", url, pre.local_path)
            return pre.local_path

        assert pre.url
        async with self.session.get(
            pre.url, raise_for_status=True, timeout=None, headers=pre.headers
        ) as resp:
            if resp.status == 304:
                assert pre.local_path.exists()
                LOG.debug("%s got 304, using %s", url, pre.local_path)
                return pre.local_path

            (fd, name) = mkstemp(
                f".{os.getpid()}",
                prefix=pre.local_path.name,
                dir=pre.local_path.parent,
            )
            f = os.fdopen(fd, "wb")
            with kev("stream_body"):
                async for chunk in resp.content.iter_any():
                    f.write(chunk)

            f.close()

            # Last-writer-wins semantics, even on Windows
            with kev("replace"):
                os.replace(name, pre.local_path)

            headers = {}
            if "etag" in resp.headers:
                headers["etag"] = resp.headers["etag"]
            elif "last-modified" in resp.headers:
                headers["last-modified"] = resp.headers["last-modified"]
            # Don't bother with replace here, although this should happen after the
            # main file gets replaced.
            hdrs_file = Path(pre.local_path.parent, pre.local_path.name + ".hdrs")
            hdrs_file.write_text(json.dumps(headers))
            LOG.debug(
                "%s newly downloaded to %s, resp headers %s",
                url,
                pre.local_path,
                headers,
            )

        return pre.local_path

    def _is_index_filename(self, name: str) -> bool:
        return name in ("", "json", "691json")

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        # TODO what is the right return value?
        return

    async def __aenter__(self) -> "Cache":
        self.session = aiohttp.ClientSession(**self._cskwargs)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        await self.session.close()
