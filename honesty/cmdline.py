import asyncio
import functools
import json
import logging
import os.path
import shutil
import sys
from datetime import datetime, timezone
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

import click

from .api import async_download_many
from .archive import extract_and_get_names
from .cache import Cache
from .checker import guess_license, has_nativemodules, is_pep517, run_checker
from .deps import DepEdge, DepNode, DepWalker, print_deps, print_flat_deps
from .releases import FileType, Package, async_parse_index, parse_index
from .version import LooseVersion, Version, parse_version

try:
    from .__version__ import __version__  # type: ignore
except ImportError:
    __version__ = "dev"


# TODO type
def wrap_async(coro: Any) -> Any:
    @functools.wraps(coro)
    def inner(*args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro(*args, **kwargs))

    return inner


def dataclass_default(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return obj.__dict__
    elif isinstance(obj, (Enum, IntEnum)):
        return obj.name
    elif isinstance(obj, datetime):
        return str(obj)
    else:
        raise TypeError(obj)


@click.group()
@click.version_option(__version__)
def cli() -> None:
    pass


@cli.command(help="List available archives")
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.option("--nouse_json", is_flag=True, type=bool)
@click.option("--as_json", is_flag=True, type=bool)
@click.argument("package_name")
@wrap_async
async def list(fresh: bool, nouse_json: bool, as_json: bool, package_name: str) -> None:
    async with Cache(fresh_index=fresh) as cache:
        package = await async_parse_index(package_name, cache, use_json=not nouse_json)

    if as_json:
        for k, v in package.releases.items():
            print(json.dumps(v, default=dataclass_default, sort_keys=True))
    else:
        print(f"package {package.name}")
        print("releases:")
        for k, v in package.releases.items():
            print(f"  {k}:")
            for f in v.files:
                if f.requires_python:
                    print(f"    {f.basename} (requires_python {f.requires_python})")
                else:
                    print(f"    {f.basename}")


@cli.command(help="Check for consistency among archives")
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.option("--nouse_json", is_flag=True, type=bool)
@click.argument("package_names", nargs=-1)
def check(
    verbose: bool, fresh: bool, nouse_json: bool, package_names: List[str]
) -> None:
    rc = 0
    with Cache(fresh_index=fresh) as cache:
        for package_name in package_names:
            package_name, operator, version = package_name.partition("==")
            package = parse_index(package_name, cache, use_json=not nouse_json)
            selected_versions = select_versions(package, operator, version)

            if verbose:
                click.echo(f"check {package_name} {selected_versions}")

            for v in selected_versions:
                rc |= run_checker(package, v, verbose=verbose, cache=cache)

    if rc != 0:
        sys.exit(rc)


@cli.command(help="Check for presence of pep517 markers")
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.option("--nouse_json", is_flag=True, type=bool)
@click.argument("package_names", nargs=-1)
def ispep517(
    verbose: bool, fresh: bool, nouse_json: bool, package_names: List[str]
) -> None:
    rc = 0
    with Cache(fresh_index=fresh) as cache:
        for package_name in package_names:
            package_name, operator, version = package_name.partition("==")
            package = parse_index(package_name, cache, use_json=not nouse_json)
            selected_versions = select_versions(package, operator, version)

            if verbose:
                click.echo(f"check {package_name} {selected_versions}")

            for v in selected_versions:
                rc |= is_pep517(package, v, verbose=verbose, cache=cache)

    if rc != 0:
        sys.exit(rc)


@cli.command(help="Check for native modules in bdist")
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.option("--nouse_json", is_flag=True, type=bool)
@click.argument("package_names", nargs=-1)
def native(
    verbose: bool, fresh: bool, nouse_json: bool, package_names: List[str]
) -> None:
    rc = 0
    with Cache(fresh_index=fresh) as cache:
        for package_name in package_names:
            package_name, operator, version = package_name.partition("==")
            package = parse_index(package_name, cache, use_json=not nouse_json)
            selected_versions = select_versions(package, operator, version)

            if verbose:
                click.echo(f"check {package_name} {selected_versions}")

            for v in selected_versions:
                rc |= has_nativemodules(package, v, verbose=verbose, cache=cache)

    if rc != 0:
        sys.exit(rc)


@cli.command(help="Guess license of a package")
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.option("--nouse_json", is_flag=True, type=bool)
@click.argument("package_names", nargs=-1)
def license(
    verbose: bool, fresh: bool, nouse_json: bool, package_names: List[str]
) -> None:
    with Cache(fresh_index=fresh) as cache:
        for package_name in package_names:
            package_name, operator, version = package_name.partition("==")
            package = parse_index(package_name, cache, use_json=not nouse_json)
            selected_versions = select_versions(package, operator, version)

            if verbose:
                click.echo(f"check {package_name} {selected_versions}")

            rc = 0
            for v in selected_versions:
                license = guess_license(package, v, verbose=verbose, cache=cache)
                if license is not None and not isinstance(license, str):
                    license = license.shortname
                if license is None:
                    rc |= 1
                print(f"{package_name}=={v}: {license or 'Unknown'}")

    if rc != 0:
        sys.exit(rc)


@cli.command(help="Download an sdist, print path on stdout")
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.option("--nouse_json", is_flag=True, type=bool)
@click.option("--dest", help="Directory to store in", default="")
@click.option(
    "--index-url",
    help="Alternate index url (uses HONESTY_INDEX_URL or pypi by default)",
)
@click.argument("package_names", nargs=-1)
@wrap_async
async def download(
    verbose: bool,
    fresh: bool,
    nouse_json: bool,
    dest: str,
    index_url: Optional[str],
    package_names: List[str],
) -> None:
    if dest and len(package_names) > 1:
        # select_versions() may also result in more than one, but that seems
        # less common.  If you specify multiple, it still just outputs a path,
        # but at least they're in the same order.
        raise click.ClickException("Cannot specify dest if more than one package")

    dest_path: Optional[Path]
    if dest:
        dest_path = Path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)
    else:
        dest_path = None

    async with Cache(fresh_index=fresh, index_url=index_url) as cache:
        for package_name in package_names:
            package_name, operator, version = package_name.partition("==")
            package = await async_parse_index(
                package_name, cache, use_json=not nouse_json
            )
            selected_versions = select_versions(package, operator, version)

            if verbose:
                click.echo(f"check {package_name} {selected_versions}")

            rc = await async_download_many(
                package,
                versions=selected_versions,
                dest=dest_path,
                cache=cache,
                verbose=verbose,
            )

    sys.exit(rc)


@cli.command(help="Download/extract an sdist, print path on stdout")
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.option("--nouse_json", is_flag=True, type=bool)
@click.option("--dest", help="Directory to store in", default="")
@click.option(
    "--index-url", help="Alternate index url (uses HONESTY_INDEX_URL or pypi by default"
)
@click.argument("package_names", nargs=-1)
@wrap_async
async def extract(
    verbose: bool,
    fresh: bool,
    nouse_json: bool,
    dest: str,
    index_url: Optional[str],
    package_names: List[str],
) -> None:
    if dest and len(package_names) > 1:
        # select_versions() may also result in more than one, but that seems
        # less common.  If you specify multiple, it still just outputs a path,
        # but at least they're in the same order.
        raise click.ClickException("Cannot specify dest if more than one package")

    async with Cache(fresh_index=fresh, index_url=index_url) as cache:
        for package_name in package_names:
            package_name, operator, version = package_name.partition("==")
            package = await async_parse_index(
                package_name, cache, use_json=not nouse_json
            )
            selected_versions = select_versions(package, operator, version)
            if len(selected_versions) != 1:
                raise click.ClickException(
                    f"Wrong number of versions: {selected_versions}"
                )

            if verbose:
                click.echo(f"check {package_name} {selected_versions}")

            rel = package.releases[selected_versions[0]]
            sdists = [f for f in rel.files if f.file_type == FileType.SDIST]
            if not sdists:
                raise click.ClickException(f"{package.name} no sdists")

            lp = await cache.async_fetch(pkg=package_name, url=sdists[0].url)

            archive_root, _ = extract_and_get_names(
                lp, strip_top_level=True, patterns=("*.*",)
            )

            subdirs = tuple(Path(archive_root).iterdir())
            if dest:
                for subdir in subdirs:
                    shutil.copytree(subdir, Path(dest, subdir.name))
                inner_dest = dest
            else:
                inner_dest = archive_root

            # Try to be helpful in the common case that there's a top-level
            # directory by itself.  Specifying a non-empty dest makes the fallback
            # less useful.
            if len(subdirs) == 1:
                print(os.path.join(inner_dest, subdirs[0].name))
            else:
                print(inner_dest)


@cli.command(help="Print age in days for a given release")
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.option("--base", help="yyyy-mm-dd of when to subtract from")
@click.argument("package_names", nargs=-1)
@wrap_async
async def age(verbose: bool, fresh: bool, base: str, package_names: List[str]) -> None:

    if base:
        base_date = datetime.strptime(base, "%Y-%m-%d")
    else:
        base_date = datetime.utcnow()
    base_date = base_date.replace(tzinfo=timezone.utc)

    async with Cache(fresh_index=fresh) as cache:
        for package_name in package_names:
            package_name, operator, version = package_name.partition("==")
            package = await async_parse_index(package_name, cache, use_json=True)
            selected_versions = select_versions(package, operator, version)
            if len(package_names) > 1:
                prefix = f"{package_name}=="
            else:
                prefix = ""

            for v in selected_versions:
                if package.releases[v].files:
                    t = min(x.upload_time for x in package.releases[v].files)
                else:
                    print(f"{prefix}{v}\t(no files)\t(no files)")
                    continue

                assert t is not None

                diff = base_date - t
                days = diff.days + (diff.seconds / 86400.0)
                print(f"{prefix}{v}\t{t.strftime('%Y-%m-%d')}\t{days:.2f}")


@cli.command(
    help="""
Show a package's dep tree.

The default output is a tree with red meaning there is no sdist.  If you want a
flat output with a sample depth-first install order, use `--flat`.

Does not currently understand pep 517 requirements, setup_requires, and
trusts the first wheel it finds to contain deps applicable to your version and
platform (which is wrong for many packages).

This is not a solver and doesn't pretend to be.  A package can be listed
multiple times (with different versions).
"""
)
@click.option("--include-extras", is_flag=True, help="Whether to incude *any* extras")
@click.option("--verbose", is_flag=True, help="Show verbose output")
@click.option("--flat", is_flag=True, help="Show (an) install order rather than tree")
@click.option(
    "--pick",
    is_flag=True,
    help="Just pick the newest version of the package instead of showing deps",
)
@click.option(
    "--python-version", default="3.7.5", help="Python version x.y.z, always 3 numbers"
)
@click.option("--sys-platform", default="linux", help="linux,darwin,win32")
@click.argument("package_name")
def deps(
    include_extras: bool,
    verbose: bool,
    flat: bool,
    pick: bool,
    python_version: str,
    sys_platform: str,
    package_name: str,
) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING)

    # TODO platform option
    # TODO something that understands pep 517 requirements for building
    # TODO move this out of cmdline into deps.py
    # TODO a way to specify that you already have certain versions of packages,
    # to prefer them.

    seen: Set[Tuple[str, Optional[Tuple[str, ...]], LooseVersion]] = set()
    assert python_version.count(".") == 2
    deptree = DepWalker(
        package_name, python_version, sys_platform, only_first=pick
    ).walk(include_extras)
    # TODO record constraints on DepEdge, or put in lib to avoid this nonsense
    fake_root = DepNode("", version=Version("0"), deps=[DepEdge(target=deptree)])
    if pick:
        print(f"{deptree.name}=={deptree.version}")
    elif flat:
        print_flat_deps(fake_root, seen)
    else:
        print_deps(fake_root, seen)


def select_versions(
    package: Package, operator: str, selector: str
) -> List[LooseVersion]:
    """
    Given operator='==' and selector='*' or '2.0', return a list of the matching
    versions, in increasing order.
    """
    if not package.releases:
        raise click.ClickException(f"No releases at all for {package.name}")

    if operator not in ("", "=="):
        raise click.ClickException("Only '==' is supported")

    if selector == "":
        # latest; we have a function called `list`
        version = [x for x in package.releases.keys()][-1]
        return [version]
    elif selector == "*":
        # we have a function called `list`
        return [x for x in package.releases.keys()]
    else:
        pv = parse_version(selector)
        if pv not in package.releases:
            raise click.ClickException(
                f"The version {selector} does not exist for {package.name}"
            )
        return [pv]


if __name__ == "__main__":
    cli(prog_name="honesty")
