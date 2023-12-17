import asyncio
import posixpath
import shutil
from pathlib import Path
from typing import Optional, Sequence, Union

import click
from packaging.version import Version

from .cache import Cache
from .releases import FileEntry, FileType, Package, PackageRelease


def download_many(
    package: Package,
    versions: Sequence[Union[Version, str]],
    dest: Path,
    cache: Cache,
    verbose: bool = False,
) -> int:
    """
    Intended as a convenience method for the CLI.  If you want async duplicate
    this.  Version parsing happens in the layer above in cmdline.py.
    """
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(async_download_many(package, versions, dest, cache))


async def async_download_many(
    package: Package,
    versions: Sequence[Union[Version, str]],
    dest: Optional[Path],
    cache: Cache,
    verbose: bool = False,
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
            if verbose:
                raise
            click.secho(f"Error: {e}", fg="red")
            rc |= 1
    return rc


async def async_download_one(
    package: Package,
    version: Union[Version, str],
    dest: Optional[Path],
    cache: Cache,
) -> Path:
    if isinstance(version, str):
        version = Version(version)
    if not isinstance(version, Version):
        raise TypeError(
            f"version {version!r} comes from {version.__module__}, not packaging.version"
        )
    rel = pick_release(package, version)
    sdist = pick_sdist(package.name, rel)
    url = sdist.url
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


def pick_release(package: Package, version: Version) -> PackageRelease:
    # Only works on conrete versions, no operators
    if version in package.releases:
        return package.releases[version]

    raise Exception(f"No version for {package.name} matching {version}")


def pick_sdist(package_name: str, release: PackageRelease) -> FileEntry:
    pick: Optional[FileEntry] = None

    # Prefer .tar.gz over .zip
    for f in release.files:
        if f.file_type == FileType.SDIST and (
            pick is None or pick.basename.endswith(".zip")
        ):
            pick = f

    if not pick:
        raise Exception(f"{package_name}=={release.parsed_version} no sdist")

    return pick
