import difflib
import hashlib
from typing import Dict, List, Set

import arlib
import click

from .cache import fetch
from .releases import Package

SDIST_EXTENSIONS = (".tar.gz", ".zip")
ZIP_EXTENSIONS = (".zip", ".egg", ".whl")


def run_checker(package: Package, version: str, verbose: bool) -> None:
    try:
        rel = package.releases[version]
    except KeyError:
        raise click.ClickException(f"version={version} not available")

    if len(rel.files) == 1:
        if rel.files[0].basename.endswith(SDIST_EXTENSIONS):
            click.secho(f"{package.name} {version} only sdist", fg="green")
            return 0
        else:
            click.secho(
                f"{package.name} {version} only bdist {rel.files[0].basename}", fg="red"
            )
            return 1

    local_paths: List[Path] = []
    with click.progressbar(rel.files) as bar:
        for f in bar:
            local_paths.append(fetch(pkg=package.name, filename=f.basename, url=f.url))
            # TODO verify checksum

    # [filename][sha] = set(archives)
    paths_present: Dict[str, Dict[str, Set[str]]] = {}
    # [sha] = last path
    sdist_paths_present: Dict[str, str] = {}
    for lp in local_paths:
        is_sdist = str(lp).endswith(SDIST_EXTENSIONS)
        engine = arlib.ZipArchive if str(lp).endswith(ZIP_EXTENSIONS) else None
        with arlib.open(lp, "r", engine=engine) as archive:
            for name in archive.member_names:
                if not archive.member_is_file(name):
                    continue

                # strips prefix of <pkg>-<ver>/
                namekey = name
                if is_sdist and "/" in name:
                    namekey = name.split("/", 1)[1]
                    if namekey.startswith("src/"):
                        namekey = namekey[4:]

                if name.endswith(".py"):
                    with archive.open_member(name, "rb") as buf:
                        data = buf.read().replace(b"\r\n", b"\n")
                    sha = hashlib.sha1(data).hexdigest()
                    paths_present.setdefault(namekey, {}).setdefault(sha, set()).add(
                        lp.name
                    )
                    if is_sdist:
                        sdist_paths_present[sha] = namekey

    rc = 0
    if not sdist_paths_present:
        click.secho(f"{package.name} {version} No sdist present", fg="red")
        return 1

    for contained_path in sorted(paths_present):
        if len(paths_present[contained_path]) != 1:
            # different hashes
            click.secho(f"  {contained_path} different hashes", fg="red")
            if verbose:
                for k, v in paths_present[contained_path].items():
                    if k in sdist_paths_present:
                        for f in v:
                            click.secho(f"    {shorten(f)}: {k}", fg="yellow")
                    else:
                        for f in v:
                            click.secho(f"    {shorten(f)}: {k}", fg="red")
            rc |= 8
        elif next(iter(paths_present[contained_path])) not in sdist_paths_present:
            click.secho(f"  {contained_path} not in sdist", fg="red")
            if verbose:
                for k, v in paths_present[contained_path].items():
                    for f in v:
                        click.secho(f"    {shorten(f)}: {k}", fg="yellow")
            rc |= 4
        elif verbose:
            click.secho(f"  {contained_path}: OK", fg="green")

    if rc == 0:
        click.secho(f"{package.name} {version} OK", fg="green")
    else:
        # It's a little unusual to print this at the end, but otherwise we need
        # to buffer messages.  Open to other ideas.
        click.secho(f"{package.name} {version} problems", fg="yellow")

    return rc


def is_pep517(package, version, verbose):
    try:
        rel = package.releases[version]
    except KeyError:
        raise click.ClickException(f"version={version} not available")

    # Find *a* sdist
    sdists = [f for f in rel.files if f.basename.endswith(SDIST_EXTENSIONS)]
    if not sdists:
        raise click.ClickException(f"{package.name} no sdists")

    lp = fetch(pkg=package.name, filename=sdists[0].basename, url=sdists[0].url)

    if str(lp).endswith(".tar.gz"):
        archive = tarfile.open(str(lp), mode="r:gz")
        for name in archive.getnames():
            if name.endswith("pyproject.toml"):
                click.echo(name)
                return True
    elif str(lp).endswith(ZIP_EXTENSIONS):
        with zipfile.ZipFile(str(lp)) as archive:
            for name in archive.namelist():
                if name.endswith("pyproject.toml"):
                    click.echo(name)
                    return True
    else:
        raise click.ClickException("unknown sdist type")


def shorten(subj: str, n=50):
    if len(subj) <= n:
        return subj
    return subj[:22] + "..." + subj[-n + 22 + 3 :]


def show_diff(a: List[str], b: List[str]):
    click.echo("".join(difflib.unified_diff(a, b)))
