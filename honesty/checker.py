import difflib
import hashlib
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple

import arlib
import click

from .cache import fetch
from .releases import SDIST_EXTENSIONS, FileEntry, FileType, Package

ZIP_EXTENSIONS = (".zip", ".egg", ".whl")


# [path] = sha
def archive_hashes(
    archive_filename: Path, strip_top_level: bool = False
) -> Dict[str, str]:
    d: Dict[str, str] = {}
    engine = (
        arlib.ZipArchive if str(archive_filename).endswith(ZIP_EXTENSIONS) else None
    )
    with arlib.open(archive_filename, "r", engine=engine) as archive:
        for name in archive.member_names:
            if not name.endswith(".py"):
                continue  #  skip for now

            namekey = name
            if strip_top_level:
                namekey = name.split("/", 1)[-1]
            if namekey.startswith("src/"):
                namekey = namekey[4:]

            with archive.open_member(name, "rb") as buf:
                data = buf.read().replace(b"\r\n", b"\n")

            sha = hashlib.sha1(data).hexdigest()
            d[namekey] = sha
    return d


def run_checker(package: Package, version: str, verbose: bool) -> int:
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
            local_paths.append(
                (fe, fetch(pkg=package.name, filename=fe.basename, url=fe.url))
            )
            # TODO verify checksum

    sdist_hashes: Dict[str, str] = {}
    for fe, lp in local_paths:
        if fe.file_type == FileType.SDIST:
            # assert not sdist_hashes # multiple sdists?
            t0 = time.time()
            sdist_hashes = archive_hashes(lp, True)
            t1 = time.time()
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
            print(f"{fe.basename} {t1-t0}")

            msg = []
            for k, h in sorted(this_hashes.items()):
                if k not in sdist_hashes:
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


def is_pep517(package: Package, version: str, verbose: bool) -> bool:
    try:
        rel = package.releases[version]
    except KeyError:
        raise click.ClickException(f"version={version} not available")

    # Find *a* sdist
    sdists = [f for f in rel.files if f.file_type == FileType.SDIST]
    if not sdists:
        raise click.ClickException(f"{package.name} no sdists")

    lp = fetch(pkg=package.name, filename=sdists[0].basename, url=sdists[0].url)

    engine = arlib.ZipArchive if str(lp).endswith(ZIP_EXTENSIONS) else None
    with arlib.open(lp, "r", engine=engine) as archive:
        for name in archive.member_names:
            # TODO for a couple of projects this is finding test fixtures, we
            # should only be looking alongside the rootmost setup.py
            if name.endswith("pyproject.toml"):
                with archive.open_member(name, "rb") as buf:
                    data = buf.read().replace(b"\r\n", b"\n")
                if b"[build-system]" in data:
                    click.echo(f"{package.name} build-system {name}")
                    return True
                else:
                    click.echo(f"{package.name} has-toml {name}")
    return False


def has_nativemodules(package: Package, version: str, verbose: bool) -> bool:
    try:
        rel = package.releases[version]
    except KeyError:
        raise click.ClickException(f"version={version} not available")

    # Find *a* sdist
    bdists = [f for f in rel.files if f.file_type == FileType.BDIST_WHEEL]
    if not bdists:
        raise click.ClickException(f"{package.name} no bdists")

    lp = fetch(pkg=package.name, filename=bdists[0].basename, url=bdists[0].url)

    engine = arlib.ZipArchive if str(lp).endswith(ZIP_EXTENSIONS) else None
    with arlib.open(lp, "r", engine=engine) as archive:
        for name in archive.member_names:
            # TODO for a couple of projects this is finding test fixtures, we
            # should only be looking alongside the rootmost setup.py
            if name.endswith(".so") or name.endswith(".dll"):
                click.echo(f"{package.name} has {name}")
                return True

    return False


def shorten(subj: str, n: int = 50) -> str:
    if len(subj) <= n:
        return subj
    return subj[:22] + "..." + subj[-n + 22 + 3 :]


def show_diff(a: List[str], b: List[str]) -> None:
    click.echo("".join(difflib.unified_diff(a, b)))
