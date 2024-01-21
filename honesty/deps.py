import logging
import os
import tarfile
import zipfile
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from io import StringIO
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from zipfile import ZipFile

import click
from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pkginfo.distribution import parse as distribution_parse
from pkginfo.wheel import Wheel
from seekablehttpfile import SeekableHttpFile

from .cache import Cache
from .releases import FileType, Package, parse_index

LOG = logging.getLogger(__name__)
VersionCallback = Callable[[str], Optional[str]]

# These correlate roughly to the node and edge terminology used by graphviz.


@dataclass
class DepNode:
    name: str
    version: Version
    deps: List["DepEdge"] = field(default_factory=list)
    has_sdist: Optional[bool] = False
    has_bdist: Optional[bool] = False
    dep_extras: Optional[Set[str]] = None
    # TODO has_bdist (set of version/platform)?
    done: bool = False


@dataclass
class DepEdge:
    target: DepNode
    constraints: Optional[str] = None
    markers: Optional[Marker] = None


@dataclass
class EnvironmentMarkers:
    os_name: str = "posix"
    sys_platform: str = "linux"
    platform_machine: str = "x86_64"
    platform_python_implementation: str = "CPython"
    platform_release: Optional[str] = None
    platform_system: str = "Linux"
    platform_version: Optional[str] = None
    python_version: Optional[str] = None
    python_full_version: Optional[str] = None
    implementation_name: str = "cpython"
    extra: Optional[str] = None  # ??

    def __post_init__(self) -> None:
        if self.sys_platform == "linux":
            if self.python_version and self.python_version[:1] == "2":
                self.sys_platform = "linux2"
        elif self.sys_platform == "win32":
            self.platform_system = "Windows"
            self.os_name = "nt"
        elif self.sys_platform == "darwin":
            self.platform_system = "Darwin"
        else:
            raise TypeError(f"Unknown sys_platform: {self.sys_platform!r}")


@dataclass
class Constraint:
    name: str
    extra: str
    specifiers: SpecifierSet
    markers: Optional[str]  # If set, starts with ';'


def _all_current_versions_unknown(cn: str) -> Optional[str]:
    return None


KeyType = Tuple[str, Version, Optional[Tuple[str, ...]]]


class DepWalker:
    def __init__(
        self,
        starting_package: str,
        python_version: str,
        sys_platform: Optional[str] = None,
        only_first: bool = False,
        trim_newer: Optional[datetime] = None,
    ) -> None:
        self.nodes: Dict[KeyType, DepNode] = {}
        self.queue: List[Tuple[Optional[DepNode], str]] = [(None, starting_package)]
        self.root: Optional[DepNode] = None
        # TODO support unusual versions.
        t = ".".join(python_version.split(".")[:2])
        self.markers = EnvironmentMarkers(
            python_version=t,
            python_full_version=python_version,
        )
        if sys_platform is not None:
            self.markers = replace(self.markers, sys_platform=sys_platform)
        self.python_version = Version(python_version)
        self.only_first = only_first
        self.trim_newer = trim_newer

    def walk(
        self,
        include_extras: bool,
        current_versions_callback: Optional[VersionCallback] = None,
        use_json: bool = True,
    ) -> DepNode:
        if current_versions_callback is None:
            current_versions_callback = _all_current_versions_unknown
        already_chosen: Dict[str, Version] = {}

        key: KeyType

        with Cache(fresh_index=True) as cache:
            while self.queue:
                parent, item = self.queue.pop(0)
                if parent is not None:
                    parent_str = parent.name
                else:
                    parent_str = "(root)"
                LOG.info(f"dequeue {item!r} for {parent_str}")

                # This call needs to be serialized on the "main thread" because
                # it will do asyncio behind the scenes.
                req = Requirement(item)
                # The python_version marker is by far the most widely-used.
                if req.marker and not self._do_markers_match(req.marker):
                    LOG.debug(f"Skip {req.name} {req.marker}")
                    continue

                (package, v) = self._pick_a_version(
                    req,
                    cache,
                    already_chosen,
                    current_versions_callback,
                    use_json=use_json,
                )
                LOG.debug(f"Chose {v}")

                if package is not None and v in package.releases:
                    has_sdist = any(
                        fe.file_type == FileType.SDIST
                        for fe in package.releases[v].files
                    )
                    # TODO: consider eggs or bdist_dumb as valid?  Can pip still use them?
                    has_bdist = any(
                        fe.file_type == FileType.BDIST_WHEEL
                        for fe in package.releases[v].files
                    )

                    # TODO: consider canonicalizing name
                    t: Tuple[str, ...] = tuple(sorted(req.extras))
                    key = (package.name, v, t)
                else:
                    # Reuse existing version
                    has_sdist = None
                    has_bdist = None
                    # TODO verify this is canonical
                    key = (req.name, v, None)

                cur = already_chosen.get(key[0])
                if cur is not None and cur != key[1]:
                    LOG.warning(f"Multiple versions for {key[0]}: {cur} and {key[1]}")
                already_chosen[key[0]] = key[1]

                # TODO: This can be parallelized in threads; we can't just do
                # this all as async because the partial http fetches are done
                # through zipfile calls that aren't async-friendly.
                node = self.nodes.get(key)
                # req.extras is Set[Any] for some reason
                req_extras: Set[str] = req.extras
                if node is None:
                    # No edges to it yet
                    node = DepNode(
                        package.name,
                        v,
                        [],
                        has_sdist=has_sdist,
                        has_bdist=has_bdist,
                        dep_extras=req_extras,
                    )
                    self.nodes[key] = node

                if parent is None:
                    self.root = node
                else:
                    parent.deps.append(
                        DepEdge(
                            node,
                            str(req.specifier),
                            req.marker,
                        )
                    )

                if node.done:
                    continue

                if self.only_first:
                    break

                # DO STUFF
                deps = self._fetch_single_deps(package, v, cache)
                LOG.info(f"deps {deps}")
                for d in deps:
                    dep_req = Requirement(d)

                    # This is nuanced, and could use a lot more (any) tests.
                    # This handles extras_require for deps when the current
                    # package (req) specifies e.g. pkg[foo] and now we need to
                    # find pkg's extras_require for foo.  Setuptools only
                    # appears to use == for these, which makes it a little
                    # easier.
                    extra_str = None
                    if dep_req.marker:
                        for t in dep_req.marker._markers:
                            if t[0] == "extra":
                                assert str(t[1]) == "=="
                                extra_str = str(t[2])

                    if include_extras or extra_str is None or extra_str in req.extras:
                        self.queue.append((node, d))
                        LOG.info(f"enqueue {d!r} for {node!r}")
                node.done = True

        assert self.root is not None
        return self.root

    def _do_markers_match(self, marker: Marker, extras: Sequence[str] = ()) -> bool:
        env = dict(**asdict(self.markers), extras=Extras(extras))
        return bool(marker.evaluate(env))

    def _pick_a_version(
        self,
        req: Requirement,
        cache: Cache,
        already_chosen: Dict[str, Version],
        currently_installed_callback: VersionCallback,
        use_json: bool = True,
    ) -> Tuple[Package, Version]:
        """
        Given `attrs (==0.1.0)` returns the corresponding release.

        Supports multiple comparisons, and prefers the most recent version.

        If you provide a `currently_installed_callback`, it should return the
        current version (as a string) or None.  If you return a non-public
        version, honesty will not use it.  (This is expected to change in a
        future release.)
        """
        package = parse_index(req.name, cache, use_json=use_json)
        v = _find_compatible_version(
            package,
            req.specifier,
            self.python_version,
            self.trim_newer,
            already_chosen,
            currently_installed_callback,
        )

        return package, v

    def _fetch_single_deps(
        self, package: Package, v: Version, cache: Cache
    ) -> Sequence[str]:
        # This uses pkginfo same as poetry, but we try to be a lot more efficient at
        # only downloading what we need to.  This is not a solver.

        if v not in package.releases:
            # Current version is non-public
            return []

        tmp = package.releases[v].requires
        if tmp is not None:
            # This makes for convenient testing, but Honesty does not currently
            # populate it.  (The API requires a separate request for each
            # version.)
            return tmp

        # Different wheels can have different deps.  We're choosing one arbitrarily.
        for fe in package.releases[v].files:
            if fe.file_type == FileType.BDIST_WHEEL:
                LOG.info(f"wheel {fe.url} {fe.size}")
                if fe.size is not None and fe.size > 20000000:
                    # Gigantic wheels we'll pay the remote read penalty
                    # the 'or ()' is needed for numpy
                    return read_metadata_remote_wheel(fe.url) or ()
                else:
                    local_path = cache.fetch(package.name, fe.url)
                    return read_metadata_wheel(local_path) or ()

        for fe in package.releases[v].files:
            if fe.file_type == FileType.SDIST:
                LOG.info("sdist")
                local_path = cache.fetch(pkg=package.name, url=fe.url)
                return read_metadata_sdist(local_path)

        raise ValueError(f"No whl/sdist for {package.name}")


# TODO: extra can have multiple -- apache-airflow==1.10.5


def read_metadata_sdist(path: "os.PathLike[str]") -> List[str]:
    # pkginfo.sdist.SDist only parses PKG-INFO, but requirements are stored in
    # *.egg-info/requires.txt instead.  Duplicating some logic here similar to
    # pkginfo.  Avoid testdata deep within the archive, like
    # distlib-0.3.0/tests/fake_dists/banana-0.4.egg/EGG-INFO/requires.txt

    # distutils.setup() doesn't appear to write requires.txt (PyMeeus)

    # TODO: We already have type guessing and extraction logic that improves
    # subsequent runs.  Just use that.
    ext = str(path).split(".")[-1]
    if ext == "zip":
        archive = zipfile.ZipFile(path)
        names = [
            name
            for name in archive.namelist()
            if name.endswith("/requires.txt") and name.count("/") <= 2
        ]
        if not names:
            # print(path, "no requires.txt")
            return []
        names.sort(key=len)
        data = archive.read(names[0])
    elif ext in ("gz", "bz2", "tgz"):
        archive2 = tarfile.TarFile.open(path)
        names = [
            name
            for name in archive2.getnames()
            if name.endswith("/requires.txt") and name.count("/") <= 2
        ]
        if not names:
            # print(path, "no requires.txt")
            return []
        names.sort(key=len)
        data = archive2.extractfile(names[0]).read()  # type: ignore
    else:
        raise ValueError("Unknown extension")

    return convert_sdist_requires(data.decode())


def convert_sdist_requires(data: str) -> List[str]:
    # This is reverse engineered from looking at a couple examples, but there
    # does not appear to be a formal spec.  Mentioned at
    # https://setuptools.readthedocs.io/en/latest/formats.html#requires-txt
    current_markers = None
    lst: List[str] = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        elif line[:1] == "[" and line[-1:] == "]":
            current_markers = line[1:-1]
            if ":" in current_markers:
                # absl-py==0.9.0 and requests==2.22.0 are good examples of this
                extra, markers = current_markers.split(":", 1)
                if extra:
                    current_markers = f"({markers}) and extra == {extra!r}"
                else:
                    current_markers = markers
            else:
                # this is an extras_require
                current_markers = f"extra == {current_markers!r}"
        else:
            if current_markers:
                lst.append(f"{line}; {current_markers}")
            else:
                lst.append(line)
    return lst


def read_metadata_wheel(path: "os.PathLike[str]") -> Sequence[str]:
    tmp: Sequence[str] = Wheel(str(path)).requires_dist
    return tmp


def read_metadata_remote_wheel(url: str) -> Sequence[str]:
    # TODO: Convince mypy that SeekableHttpFile is an IO[Bytes]
    f = SeekableHttpFile(url)
    z = ZipFile(f)  # type: ignore

    # Favors the shortest name; most wheels only have one.
    metadata_names = [name for name in z.namelist() if name.endswith("/METADATA")]
    metadata_names.sort(key=len)

    if len(metadata_names) > 0:
        # TODO: This does not go through the Wheel path from pkginfo because it
        # requires a filename on disk.
        data = z.read(metadata_names[0])
        metadata = distribution_parse(StringIO(data.decode()))
        reqs = metadata.get_all("Requires-Dist")
        assert reqs is not None
        return reqs

    raise ValueError("No metadata")


def _find_compatible_version(
    package: Package,
    specifiers: SpecifierSet,
    python_version: Version,
    trim_newer: Optional[datetime] = None,
    already_chosen: Optional[Dict[str, Version]] = None,
    current_versions_callback: Optional[VersionCallback] = None,
) -> Version:
    # Luckily we can fall back on `packaging` here, because "correct" parsing is a
    # lot of code.  Legacy versions are already likely thrown away in
    # `parse_index`.

    # First filter out by requires_python; this lets us give a more descriptive
    # error when the package is completely incompatible.
    # TODO: Give a better error when there's a release with no artifacts.
    possible: List[Version] = []

    for k, v in package.releases.items():
        if trim_newer:
            oldest_file = None
            for fe in v.files:
                if oldest_file is None or fe.upload_time < oldest_file:
                    oldest_file = fe.upload_time
            # upload_time only available with json, not simple html
            if oldest_file is not None and oldest_file > trim_newer:
                continue

        # requires_python is set on FileEntry, not PackageRelease
        # arbitrarily take the first one.
        requires_python = None
        for fe in v.files:
            if fe.requires_python:
                requires_python = SpecifierSet(fe.requires_python)
                break

        # LOG.debug(f"CHECK {package.name} {python_version} against {requires_python}: {k}")
        if not requires_python or python_version in requires_python:
            LOG.debug("  include %s", k)
            possible.append(k)

    if not possible:
        raise ValueError(f"{package.name} incompatible with {python_version}")

    # Insert the current version if we didn't above.  This uses requires_python
    # filtering logic, unless it's a non-public version.
    cur = current_versions_callback and current_versions_callback(package.name)
    cur_v: Optional[Version] = None
    if cur:
        cur_v = Version(cur)
    if cur_v and cur_v not in package.releases:
        possible.append(cur_v)

    # specifiers.filter returns Union[Version, LegacyVersion, str] but we never
    # pass in a str.
    possible = list(specifiers.filter(possible))
    if not possible:
        raise ValueError(
            f"{package.name} has no {python_version}-compatible release with constraint {specifiers}"
        )
    ac = already_chosen and already_chosen.get(package.name)
    xform_possible: List[Tuple[bool, bool, int, Version]] = sorted(
        (p == ac, p == cur_v, i, p) for (i, p) in enumerate(possible)
    )
    LOG.debug(f"  possible {xform_possible!r}")

    return xform_possible[-1][3]


class Extras:
    """
    This is a tiny class that lets us get 'extra == "foo"' working for
    `packaging.markers`
    """

    def __init__(self, extras: Iterable[str]) -> None:
        self.extras = extras

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, str):
            return False
        return other in self.extras


def print_flat_deps(
    deps: DepNode, seen: Set[Tuple[str, Optional[Tuple[str, ...]], Version]]
) -> None:
    # Simple postorder, assumes no cycles (fixtures/testtools)
    for x in deps.deps:
        key = (
            x.target.name,
            tuple(sorted(x.target.dep_extras)) if x.target.dep_extras else None,
            x.target.version,
        )
        flag = key in seen
        seen.add(key)

        if x.target.deps:
            print_flat_deps(x.target, seen)
        dep_extras = (
            f"[{', '.join(sorted(x.target.dep_extras))}]" if x.target.dep_extras else ""
        )
        if not flag:
            # TODO markers
            click.echo(f"{x.target.name}{dep_extras}=={x.target.version}")


def print_deps(
    deps: DepNode,
    seen: Set[Tuple[str, Optional[Tuple[str, ...]], Version]],
    depth: int = 0,
) -> None:
    prefix = ". " * depth
    for x in deps.deps:
        # TODO display whether install or build dep, and whether pin disallows
        # current version, has compatible bdist, no sdist, etc
        key = (
            x.target.name,
            tuple(sorted(x.target.dep_extras)) if x.target.dep_extras else None,
            x.target.version,
        )
        dep_extras = (
            f"[{', '.join(sorted(x.target.dep_extras))}]" if x.target.dep_extras else ""
        )
        if key in seen:
            print(
                f"{prefix}{x.target.name}{dep_extras} (=={x.target.version}) (already listed){' ; ' + str(x.markers) if x.markers else ''}"
            )
        else:
            seen.add(key)
            color = "red" if not x.target.has_sdist else "green"
            click.echo(
                prefix
                + click.style(
                    x.target.name,
                    fg=color,
                )
                + f"{dep_extras} (=={x.target.version}){' ; ' + str(x.markers) if x.markers else ''} via "
                + click.style(x.constraints or "*", fg="yellow")
                + click.style(" no whl" if not x.target.has_bdist else "", fg="blue")
            )
            if x.target.deps:
                print_deps(x.target, seen, depth + 1)
