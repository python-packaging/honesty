import asyncio
import os
import posixpath
import shutil
from pathlib import Path
from typing import List, Optional

import click

from honesty.cache import Cache
from honesty.releases import FileType, Package, parse_index


def download_many(
    package: Package, versions: List[str], dest: Path, cache: Cache
) -> int:
    """
    Intended as a convenience method for the CLI.  If you want async duplicate
    this.  Version parsing happens in the layer above in cmdline.py.
    """
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(async_download_many(package, versions, dest, cache))


async def async_download_many(
    package: Package, versions: List[str], dest: Optional[Path], cache: Cache
) -> int:
    # Once aioitertools has a new release, this can use concurency-limited
    # gather
    rc = 0
    coros = [async_download_one(package, v, dest, cache) for v in versions]
    for coro in asyncio.as_completed(coros):
        try:
            result = await coro
            print(result.as_posix())
        except Exception as e:
            click.secho(f"Error: {e}", fg="red")
            rc |= 1
    return rc


async def async_download_one(
    package: Package, version: str, dest: Optional[Path], cache: Cache
) -> Path:
    sdists = [
        f for f in package.releases[version].files if f.file_type == FileType.SDIST
    ]
    url = sdists[0].url
    cache_path = await cache.async_fetch(package.name, url)
    # TODO: check hash
    if dest:
        # So that cache can make arbitrary names, we get the basename portion
        # from the url.
        dest_filename = dest / posixpath.basename(url)
        # In the future, can reflink for additional speedup (pypi:reflink)
        # try:
        #     reflink.reflink(cache_path, dest_filename)
        # except (NotImplementedError, ReflinkImpossibleError) as e:
        shutil.copyfile(cache_path, dest_filename)
        return dest_filename
    return cache_path
