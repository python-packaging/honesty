import asyncio
import functools
import hashlib
import json
import logging
import os.path
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, IO, List, Optional, Set, Tuple

import aiohttp.client_exceptions

import click
import keke
from packaging.utils import canonicalize_name

from packaging.version import Version

from .api import async_download_many
from .archive import extract_and_get_names
from .cache import Cache
from .checker import guess_license, has_nativemodules, is_pep517, run_checker
from .deps import DepWalker, is_canonical, POOL, print_deps, print_flat_deps
from .releases import async_parse_index, FileType, Package, parse_index
from .requirements import _iter_simple_requirements
from .vcs import CloneAnalyzer, extract2

try:
    from .__version__ import version as __version__
except ImportError:
    __version__ = "dev"


# TODO type
def wrap_async(coro: Any) -> Any:
    @functools.wraps(coro)
    def inner(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(coro(*args, **kwargs))

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


def _stats_thread() -> None:
    prev_ts = None
    prev_process_time = None
    while True:
        ts = time.time()
        process_time = time.process_time()
        if prev_ts is not None:
            keke.kcount(
                "proc_cpu_pct",
                100 * (process_time - prev_process_time) / (ts - prev_ts),
            )

        prev_ts = ts
        prev_process_time = process_time
        time.sleep(0.01)


@click.group()
@click.pass_context
@click.option(
    "--trace", type=click.File("w"), help="Write chrome trace to this filename"
)
@click.option("--stats", is_flag=True, help="Include cpu stats in the trace")
@click.option("--verbose", is_flag=True, help="Verbose logging")
@click.option("-p", "--parallelism", default=24, type=int, help="Parallelism factor")
@click.version_option(__version__)
def cli(
    ctx: click.Context,
    trace: Optional[IO[str]],
    verbose: bool,
    parallelism: int,
    stats: bool,
) -> None:
    if trace:
        ctx.with_resource(keke.TraceOutput(trace))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING)
    if stats:
        threading.Thread(target=_stats_thread, daemon=True).start()

    # Presumably nothing has run on it yet...
    POOL._max_workers = parallelism


@cli.command(help="List available archives")
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.option("--nouse_json", is_flag=True, type=bool)
@click.option("--as_json", is_flag=True, type=bool)
@click.option("--justver", is_flag=True, type=bool)
@click.argument("package_name")
@wrap_async
async def list(
    fresh: bool, nouse_json: bool, as_json: bool, justver: bool, package_name: str
) -> None:
    async with Cache(fresh_index=fresh) as cache:
        package = await async_parse_index(package_name, cache, use_json=not nouse_json)

    if justver:
        selected_versions = select_versions(package, "==", "")
        print(f"{package_name}=={selected_versions[-1]}")
    elif as_json:
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

    rc = 0
    async with Cache(fresh_index=fresh, index_url=index_url) as cache:
        for package_name in package_names:
            package_name, operator, version = package_name.partition("==")
            try:
                package = await async_parse_index(
                    package_name, cache, use_json=not nouse_json
                )
            except aiohttp.client_exceptions.ClientResponseError as e:
                click.secho(f"Error: {package_name} got {e!r}", fg="red")
                rc |= 2
                continue

            selected_versions = select_versions(package, operator, version)

            if verbose:
                click.echo(f"check {package_name} {selected_versions}")

            # any exception here sets the 1 bit
            rc |= await async_download_many(
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
            wheels = [f for f in rel.files if f.file_type == FileType.BDIST_WHEEL]
            if not sdists and not wheels:
                raise click.ClickException(f"{package.name} no sdists or wheels")

            chosen = sdists + wheels
            lp = await cache.async_fetch(pkg=package_name, url=chosen[0].url)

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
                    t = min(
                        x.upload_time
                        for x in package.releases[v].files
                        if x.upload_time is not None
                    )
                else:
                    print(f"{prefix}{v}\t(no files)\t(no files)")
                    continue

                assert t is not None

                diff = base_date - t
                days = diff.days + (diff.seconds / 86400.0)
                tab = "\t"
                print(
                    f"{prefix}{v}\t{t.strftime('%Y-%m-%d')}\t{days:.2f}{tab + '(yanked)' if package.releases[v].yanked else ''}"
                )


@cli.command()
def checkcache() -> None:
    for dirpath, dirnames, filenames in os.walk(
        os.path.expanduser("~/.cache/honesty/pypi")
    ):
        if "json" in filenames:
            archives = [
                f
                for f in filenames
                if not (f == "json" or f.startswith("json.") or f.endswith(".json"))
            ]
            obj = json.loads(Path(dirpath, "json").read_text())

            if "releases" not in obj:
                if tuple(obj.keys()) != ("last_serial",):
                    print(f"{dirpath}/json invalid {obj.keys()}")
                continue

            for lst in obj["releases"].values():
                for i in lst:
                    filename = os.path.basename(i["url"])
                    if filename in archives:
                        h = hashlib.sha256()
                        h.update(Path(dirpath, filename).read_bytes())
                        archives.remove(filename)
                        if i["digests"]["sha256"] != h.hexdigest():
                            click.secho(f"{dirpath}/{filename} bad digest", fg="red")
            if archives:
                print(f"{dirpath} orphans {archives}")


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
    "--python-version",
    default=".".join(map(str, sys.version_info[:3])),
    help="Python version x.y.z, always 3 numbers",
    show_default=True,
)
@click.option("--sys-platform", default="linux", help="linux,darwin,win32")
@click.option("--historical", help="yyyy-mm-dd of a historical date to simulate")
@click.option("--have", help="pkg==ver to assume already installed", multiple=True)
@click.option("--nouse-json", is_flag=True)
@click.option(
    "-r",
    "--requirement_file",
    multiple=True,
    help="Requirements files, specify flag multiple times",
)
@click.argument("reqs", nargs=-1)
def deps(
    include_extras: bool,
    verbose: bool,
    flat: bool,
    pick: bool,
    python_version: str,
    sys_platform: str,
    reqs: List[str],
    historical: str,
    have: List[str],
    nouse_json: bool,
    requirement_file: List[str],
) -> None:
    new_have = []
    for h in have:
        k, _, v = h.partition("==")
        new_have.append(f"{canonicalize_name(k)}=={v}")
    have = new_have

    # Command above is called "list" :(
    reqs = [i for i in reqs]

    if requirement_file:
        reqs.extend(
            [
                str(r)
                for rf in requirement_file
                for r in _iter_simple_requirements(Path(rf))
            ]
        )

    trim_newer: Optional[datetime]
    if historical:
        trim_newer = datetime.strptime(historical, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    else:
        trim_newer = None

    def current_versions_callback(p: str) -> Optional[str]:
        assert is_canonical(p)
        for x in have:
            k, _, v = x.partition("==")
            if canonicalize_name(k) == p:
                # TODO canonicalize earlier
                return v
        return None

    # TODO something that understands pep 517 requirements for building
    # TODO move this out of cmdline into deps.py

    seen: Set[Tuple[str, Optional[Tuple[str, ...]], Version]] = set()
    assert python_version.count(".") == 2
    walker = DepWalker(
        python_version,
        sys_platform,
        only_first=pick,
        trim_newer=trim_newer,
        use_json=not nouse_json,
    )
    walker.enqueue(reqs)
    deptree = walker.walk(
        include_extras,
        current_versions_callback=current_versions_callback,
    )
    with keke.kev("print"):
        if pick:
            # TODO this is completely wrong
            print(f"{deptree.name}=={deptree.version}")
        elif flat:
            print_flat_deps(walker.root, seen)
        else:
            print_deps(walker.root, seen, walker.known_conflicts)


@cli.command(help="Guess what git rev corresponds to a release")
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--url-only", is_flag=True)
@click.option("--try-order", default="likely_tags,tags,branches", show_default=True)
@click.option("--fresh", "-f", is_flag=True)
@click.argument("package_names", nargs=-1)
@wrap_async
async def revs(
    verbose: bool, url_only: bool, fresh: bool, try_order: str, package_names: List[str]
) -> None:
    async with Cache(fresh_index=fresh) as cache:
        for package_name in package_names:
            url = None
            if "@" in package_name:
                package_name, url = package_name.split("@")

            package_name, operator, version = package_name.partition("==")
            try:
                package = await async_parse_index(package_name, cache, use_json=True)
            except Exception as e:
                print(f"{package_name}: error {e}")
                continue

            if not url:
                # We can only do this if we know a vcs url.
                url = extract2(package)
                if not url:
                    click.echo(f"Sorry, {package.name} does not have a known vcs")
                    continue

            if url_only:
                print(f"{package.name}: {url}")
                continue

            ca = CloneAnalyzer(url, verbose=verbose)

            selected_versions = select_versions(package, operator, version)
            for sv in selected_versions:
                # TODO support verssion '*' and such better
                rel = package.releases[sv]
                sdists = [f for f in rel.files if f.file_type == FileType.SDIST]
                type_suffix = "sdist"
                if not sdists:
                    # These are generally ordered by python version, so this
                    # makes us prefer a more current release, no 3to2
                    sdists = [
                        f for f in rel.files if f.file_type == FileType.BDIST_WHEEL
                    ]
                    type_suffix = "wheel"

                lp = await cache.async_fetch(pkg=package_name, url=sdists[0].url)

                # TODO: More than just *.py...
                archive_root, names = extract_and_get_names(
                    lp, strip_top_level=True, patterns=("*.*",)
                )

                # This makes an assumption the repo and tree are set up the same (no
                # subdir)
                click.echo(f"{package.name}=={sv} {type_suffix}:")

                match = ca.find_best_match(
                    archive_root, names, str(sv), try_order=try_order.split(",")
                )
                # TODO attempt a describe on revs, and don't sort alphabetically
                simplified = sorted(set(m[2] for m in match))
                if simplified:
                    print(f"  p={match[0][0]} {simplified}")
                else:
                    print("  no match")


def select_versions(package: Package, operator: str, selector: str) -> List[Version]:
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
        version = [
            x for x in package.releases.keys() if not package.releases[x].yanked
        ][-1]
        return [version]
    elif selector == "*":
        # we have a function called `list`
        return [x for x in package.releases.keys() if not package.releases[x].yanked]
    else:
        pv = Version(selector)
        if pv not in package.releases:
            raise click.ClickException(
                f"The version {selector} does not exist for {package.name}"
            )
        return [pv]


if __name__ == "__main__":
    cli(prog_name="honesty")
