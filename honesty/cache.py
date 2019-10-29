"""
Cache-related stuff.
"""

import os
import re
from pathlib import Path
from typing import List, Optional

import requests

CACHE_DIR = os.environ.get("HONESTY_CACHE", "~/.cache/honesty/pypi")
CACHE_PATH = Path(CACHE_DIR).expanduser()

MIRROR_BASE = os.environ.get("HONESTY_MIRROR_BASE", "https://pypi.org/simple/")


def cache_dir(pkg: str) -> Path:
    a = pkg[:2]
    b = pkg[2:4] or "--"
    return Path(a, b, pkg)


SESSION = requests.Session()


def fetch(pkg: str, filename=None, url=None) -> Path:
    """
    Fetch and return filename.

    If it already exists, just leave it alone.  Should be concurrent-safe.
    """
    # There are a couple of packages that have entities in their names; rather
    # than getting a 404 or properly parsing them, let's just error out.
    assert "&" not in pkg
    assert "#" not in pkg

    if url is None:
        url = f"{MIRROR_BASE}{pkg}/{filename or ''}"

    output_dir = CACHE_PATH / cache_dir(pkg)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / (filename or "index.html")

    if not output_file.exists():
        with SESSION.get(url) as resp:
            tmp = f"{output_file}.{os.getpid()}"
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                f.write(resp.content)
            # Last-writer-wins semantics
            os.rename(tmp, output_file)

    return output_file
