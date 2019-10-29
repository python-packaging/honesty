import difflib
import tarfile
import zipfile
import hashlib

import click

from .releases import Package
from .cache import fetch

from typing import List, Dict, Set

def run_checker(package: Package, version: str, verbose: bool) -> None:
    try:
        rel = package.releases[version]
    except KeyError:
        raise click.ClickException(f"version={version} not available")

    if len(rel.files) == 1:
        raise click.ClickException(f"only one file, can't cross-reference")

    local_paths: List[Path] = []
    for f in rel.files:
        local_paths.append(fetch(pkg=package.name, filename=f.basename, url=f.url))
        # TODO verify checksum

    # [filename][sha] = set(archives)
    paths_present: Dict[str, Dict[str, Set[str]]] = {}
    for lp in local_paths:
        is_sdist = not (str(lp).endswith(".whl") or str(lp).endswith(".egg"))
        if str(lp).endswith(".tar.gz"):
            archive = tarfile.open(str(lp), mode="r:gz")
            for name in archive.getnames():
                # strips prefix of <pkg>-<ver>/
                namekey = name
                if is_sdist and "/" in name:
                    namekey = name.split("/", 1)[1]

                if name.endswith(".py"):
                    buf = archive.extractfile(name)
                    data = buf.read()
                    sha = hashlib.sha1(data).hexdigest()
                    paths_present.setdefault(namekey, {}).setdefault(sha, set()).add(lp.name)
        elif str(lp).endswith(".zip") or str(lp).endswith(".whl"):
            with zipfile.ZipFile(str(lp)) as archive:
                for name in archive.namelist():
                    # strips prefix of <pkg>-<ver>/
                    namekey = name
                    if is_sdist and "/" in name:
                        namekey = name.split("/", 1)[1]
                    if name.endswith(".py"):
                        data = archive.read(name)
                        sha = hashlib.sha1(data).hexdigest()
                        paths_present.setdefault(namekey, {}).setdefault(sha, set()).add(lp.name)
        else:
            click.secho(f"Warning: unknown type {lp}", fg="red")

    for contained_path in sorted(paths_present):
        if len(paths_present[contained_path]) != 1:
            # different hashes
            click.echo(f"{contained_path}: different sha1 {', '.join(paths_present[contained_path].keys())}")
        else:
            sha = next(iter(paths_present[contained_path]))
            if len(paths_present[contained_path][sha]) != len(local_paths):
                click.secho(f"{contained_path}: missing from:", fg="red")
                for l in local_paths:
                    if l.name not in paths_present[contained_path][sha]:
                        click.secho(f"  {l.name}")
            elif verbose:
                click.secho(f"{contained_path}: OK", fg="green")

def show_diff(a: List[str], b: List[str]):
    click.echo(''.join(difflib.unified_diff(a, b)))
