import asyncio
import functools
import sys
from pathlib import Path
from typing import Any, List, Optional

import click
import pkg_resources

from honesty.api import async_download_many
from honesty.cache import Cache
from honesty.checker import has_nativemodules, is_pep517, run_checker
from honesty.releases import Package, async_parse_index, parse_index


# TODO type
def wrap_async(coro: Any) -> Any:
    @functools.wraps(coro)
    def inner(*args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro(*args, **kwargs))

    return inner


@click.group()
def cli() -> None:
    pass


@cli.command(help="List available archives")
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.argument("package_name")
@wrap_async
async def list(fresh: bool, package_name: str) -> None:
    async with Cache(fresh_index=fresh) as cache:
        package = await async_parse_index(package_name, cache)

    print(f"package {package.name}")
    print("releases:")
    for k, v in package.releases.items():
        print(f"  {k}:")
        for f in v.files:
            print(f"    {f.basename}")


@cli.command(help="Check for consistency among archives")
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.argument("package_name")
def check(verbose: bool, fresh: bool, package_name: str) -> None:
    with Cache(fresh_index=fresh) as cache:
        package_name, operator, version = package_name.partition("==")
        package = parse_index(package_name, cache)
        selected_versions = select_versions(package, operator, version)

        if verbose:
            click.echo(f"check {package_name} {selected_versions}")

        rc = 0
        for v in selected_versions:
            rc |= run_checker(package, v, verbose=verbose, cache=cache)

    if rc != 0:
        sys.exit(rc)


@cli.command(help="Check for presence of pep517 markers")
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.argument("package_name")
def ispep517(verbose: bool, fresh: bool, package_name: str) -> None:
    with Cache(fresh_index=fresh) as cache:
        package_name, operator, version = package_name.partition("==")
        package = parse_index(package_name, cache)
        selected_versions = select_versions(package, operator, version)

        if verbose:
            click.echo(f"check {package_name} {selected_versions}")

        rc = 0
        for v in selected_versions:
            rc |= is_pep517(package, v, verbose=verbose, cache=cache)

    if rc != 0:
        sys.exit(rc)


@cli.command(help="Check for native modules in bdist")
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.argument("package_name")
def native(verbose: bool, fresh: bool, package_name: str) -> None:
    with Cache(fresh_index=fresh) as cache:
        package_name, operator, version = package_name.partition("==")
        package = parse_index(package_name, cache)
        selected_versions = select_versions(package, operator, version)

        if verbose:
            click.echo(f"check {package_name} {selected_versions}")

        rc = 0
        for v in selected_versions:
            rc |= has_nativemodules(package, v, verbose=verbose, cache=cache)

    if rc != 0:
        sys.exit(rc)


@cli.command(help="Download an sdist, print path on stdout")
@click.option("--verbose", "-v", is_flag=True, type=bool)
@click.option("--fresh", "-f", is_flag=True, type=bool)
@click.option("--dest", help="Directory to store in", default="")
@click.option(
    "--index-url", help="Alternate index url (uses HONESTY_INDEX_URL or pypi by default"
)
@click.argument("package_name")
@wrap_async
async def download(
    verbose: bool, fresh: bool, dest: str, index_url: Optional[str], package_name: str
) -> None:
    dest_path: Optional[Path]
    if dest:
        dest_path = Path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)
    else:
        dest_path = None

    async with Cache(fresh_index=fresh, index_url=index_url) as cache:
        package_name, operator, version = package_name.partition("==")
        package = await async_parse_index(package_name, cache)
        selected_versions = select_versions(package, operator, version)

        if verbose:
            click.echo(f"check {package_name} {selected_versions}")

        rc = await async_download_many(
            package, versions=selected_versions, dest=dest_path, cache=cache
        )

    sys.exit(rc)


def select_versions(package: Package, operator: str, selector: str) -> List[str]:
    """
    Given operator='==' and selector='*' or '2.0', return a list of the matching
    versions, in increasing order.
    """
    if not package.releases:
        raise click.ClickException(f"No releases at all for {package.name}")

    if operator not in ("", "=="):
        raise click.ClickException("Only '==' is supported")

    if selector == "":
        # latest
        version = sorted(package.releases, key=pkg_resources.parse_version)[-1]
        return [version]
    elif selector == "*":
        versions: List[str] = sorted(package.releases, key=pkg_resources.parse_version)
        return versions
    else:
        if selector not in package.releases:
            raise click.ClickException(
                f"The version {selector} does not exist for {package.name}"
            )
        return [selector]


if __name__ == "__main__":
    cli()
