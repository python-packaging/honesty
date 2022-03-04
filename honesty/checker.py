import difflib
import os.path
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple, Union
import toml

import click
from infer_license.api import guess_file
from infer_license.types import License

from .archive import archive_hashes, extract_and_get_names
from .cache import Cache
from .releases import FileEntry, FileType, Package
from .version import LooseVersion


def run_checker(
    package: Package, version: LooseVersion, verbose: bool, cache: Cache
) -> int:
    try:
        rel = package.releases[version]
    except KeyError:
        raise click.ClickException(f"version={version} not available")

    sdists = [f for f in rel.files if f.file_type == FileType.SDIST]

    if not sdists:
        click.secho(f"{package.name} {version} no sdist", fg="red")
        return 1
    elif len(sdists) == len(rel.files):
        click.secho(f"{package.name} {version} only sdist", fg="green")
        return 0

    local_paths: List[Tuple[FileEntry, Path]] = []
    with click.progressbar(rel.files) as bar:
        for fe in bar:
            local_paths.append((fe, cache.fetch(pkg=package.name, url=fe.url)))
            # TODO verify checksum

    sdist_hashes: Dict[str, str] = {}
    for fe, lp in local_paths:
        if fe.file_type == FileType.SDIST:
            # assert not sdist_hashes # multiple sdists?
            t0 = time.time()
            sdist_hashes = archive_hashes(lp, True)
            t1 = time.time()
            if verbose:
                print(f"{fe.basename} {t1-t0}")

    if verbose:
        for k, v in sdist_hashes.items():
            print(f"{k} {v}")

    # [message] = set(filenames)
    messages: Dict[str, Set[str]] = {}
    rc = 0
    for fe, lp in local_paths:
        if fe.file_type in (FileType.BDIST_WHEEL, FileType.BDIST_EGG):
            t0 = time.time()
            this_hashes = archive_hashes(lp)
            t1 = time.time()
            if verbose:
                print(f"{fe.basename} {t1-t0}")

            msg = []
            for k, h in sorted(this_hashes.items()):
                if k not in sdist_hashes:
                    # Intentionally not including has here, because
                    # scipy/__config__.py has a different hash in each one and
                    # I want them to coalesce
                    msg.append(f"    {k} not in sdist")
                    rc |= 4
                elif h != sdist_hashes[k]:
                    msg.append(f"    {k} differs from sdist {h}")
                    rc |= 8

            if msg:
                messages.setdefault("\n".join(msg), set()).add(fe.basename)

    if rc == 0:
        click.secho(f"{package.name} {version} OK", fg="green")
    else:
        click.secho(f"{package.name} {version} problems", fg="yellow")
        for k, vm in messages.items():
            for i in vm:
                click.secho(f"  {i}", fg="red")
            click.secho(k, fg="yellow")

    return rc


def is_pep517(
    package: Package, version: LooseVersion, verbose: bool, cache: Cache
) -> bool:
    try:
        rel = package.releases[version]
    except KeyError:
        raise click.ClickException(f"version={version} not available")

    # Find *a* sdist
    sdists = [f for f in rel.files if f.file_type == FileType.SDIST]
    if not sdists:
        raise click.ClickException(f"{package.name} no sdists")

    lp = cache.fetch(pkg=package.name, url=sdists[0].url)

    archive_root, names = extract_and_get_names(
        lp, strip_top_level=True, patterns=("pyproject.toml",)
    )
    for relname, srcname in names:
        # TODO for a couple of projects this is finding test fixtures, we
        # should only be looking alongside the rootmost setup.py
        if srcname.endswith("pyproject.toml"):
            with open(os.path.join(archive_root, relname), "rb") as buf:
                data = buf.read().replace(b"\r\n", b"\n")

            t = toml.loads(data.decode("utf-8"))
            bb = t.get("build-system", {}).get("build-backend", "?")
            click.echo(f"{package.name} {bb}")
            break
    else:
        click.echo(f"{package.name} no-pyproject-toml")
    return False


def guess_license(
    package: Package, version: LooseVersion, verbose: bool, cache: Cache
) -> Union[License, str, None]:
    try:
        rel = package.releases[version]
    except KeyError:
        raise click.ClickException(f"version={version} not available")

    # Find *a* sdist
    sdists = [f for f in rel.files if f.file_type == FileType.SDIST]
    if not sdists:
        raise click.ClickException(f"{package.name} no sdists")

    lp = cache.fetch(pkg=package.name, url=sdists[0].url)

    archive_root, names = extract_and_get_names(
        lp, strip_top_level=True, patterns=("LICENSE*", "COPY*")
    )
    result_path = None
    result: Union[License, str, None] = None
    for relname, srcname in names:
        # TODO for a couple of projects this is finding test fixtures, we
        # should only be looking alongside the rootmost setup.py
        guess = guess_file(os.path.join(archive_root, relname))
        if result_path is None or len(relname) < len(result_path):
            result_path = relname
            result = guess

    if result is None and result_path:
        result = "Present but unknown"
    return result


def has_nativemodules(
    package: Package, version: LooseVersion, verbose: bool, cache: Cache
) -> bool:
    try:
        rel = package.releases[version]
    except KeyError:
        raise click.ClickException(f"version={version} not available")

    # Find *a* sdist
    bdists = [f for f in rel.files if f.file_type == FileType.BDIST_WHEEL]
    if not bdists:
        raise click.ClickException(f"{package.name} no bdists")

    if verbose:
        click.echo(f"{package.name} {version} {bdists[0].basename}")

    lp = cache.fetch(pkg=package.name, url=bdists[0].url)

    archive_root, names = extract_and_get_names(
        lp, strip_top_level=False, patterns=("*.so", "*.dll")
    )
    for relname, srcname in names:
        # TODO for a couple of projects this is finding test fixtures, we
        # should only be looking alongside the rootmost setup.py
        if srcname.endswith(".so") or srcname.endswith(".dll"):
            click.echo(f"{package.name} has {srcname}")
            return True

    return False


def shorten(subj: str, n: int = 50) -> str:
    if len(subj) <= n:
        return subj
    return subj[:22] + "..." + subj[-n + 22 + 3 :]


def show_diff(a: List[str], b: List[str]) -> None:
    click.echo("".join(difflib.unified_diff(a, b)))
