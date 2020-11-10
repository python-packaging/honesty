import asyncio
import enum
import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .cache import Cache
from .version import LooseVersion, parse_version

# Apologies in advance, "parsing" html via regex
CHECKSUM_RE = re.compile(
    r'\A(?P<url>[^"#]+\/(?P<basename>[^#]+))#(?P<checksum>[^="]+=[a-f0-9]+)\Z'
)
NUMERIC_VERSION = re.compile(
    r"^(?P<package>.*?)-(?P<version>[0-9][^-]*?)"
    r"(?P<suffix>(?P<platform>\.macosx|\.linux|\.cygwin|\.win(?:xp)?(?:32)?)?"
    r"(?:|-.*))?$"
)

ISO8601_FORMAT = "%Y-%m-%dT%H:%M:%S"


SDIST_EXTENSIONS = (".tgz", ".tar.gz", ".zip", ".tar.bz2")


# This list matches warehouse/packaging/models.py with the addition of UNKNOWN.
#
# Platform (in the case of bdist_dumb) is not currently stored anywhere but
# doesn't belong in this enum.

# Some rough popularity numbers at the time of writing (top 5k packages, with
# some double counts for the current release of each):
#
#     31 "bdist_dmg"
#     41 "bdist_rpm"
#    176 "bdist_msi"
#    309 "bdist_dumb"
#   6909 "bdist_wininst"
#  18201 "bdist_egg"
# 138984 "sdist"
# 155904 "bdist_wheel"


class FileType(enum.IntEnum):
    UNKNOWN = 0
    SDIST = (
        1  # .tar.gz or .zip (or for packages like Twisted, .tar.bz2, or amqplib, .tgz)
    )
    BDIST_DMG = 2  # .dmg
    BDIST_DUMB = 3  # -(platform).tar.gz
    BDIST_EGG = 4  # .egg
    BDIST_MSI = 5  # .msi
    BDIST_RPM = 6  # .rpm
    BDIST_WHEEL = 7  # .whl
    BDIST_WININST = 8  # .exe


class UnexpectedFilename(Exception):
    pass


def guess_file_type(filename: str) -> FileType:
    if filename.endswith(".egg"):
        return FileType.BDIST_EGG
    elif filename.endswith(".whl"):
        return FileType.BDIST_WHEEL
    elif filename.endswith(".exe"):
        return FileType.BDIST_WININST
    elif filename.endswith(".msi"):
        return FileType.BDIST_MSI
    elif filename.endswith(".rpm"):
        return FileType.BDIST_RPM
    elif filename.endswith(".dmg"):
        return FileType.BDIST_DMG
    elif filename.endswith(SDIST_EXTENSIONS):
        filename = remove_suffix(filename)
        match = NUMERIC_VERSION.match(filename)
        # Some oddly-named files are not likely to be loaded by pip either.
        if match is None:
            raise UnexpectedFilename(filename)
        # bdist_dumb can't be easily discerned
        if match.group("platform"):
            return FileType.BDIST_DUMB
        elif match.group("suffix") and match.group("suffix").startswith("-macosx"):
            return FileType.BDIST_DUMB
        return FileType.SDIST
    else:
        return FileType.UNKNOWN


@dataclass(order=True)
class FileEntry:
    url: str  # https://files.pythonhosted.../foo-1.0.tgz
    basename: str  # foo-1.0.tgz
    checksum: str  # 'sha256=<foo>'
    file_type: FileType
    version: str  # TODO: better type
    requires_python: Optional[str] = None  # '>=3.6'
    size: Optional[int] = None
    python_version: Optional[str] = None  # 'py2.py3' or 'source'
    upload_time: Optional[datetime] = None
    # TODO extract upload date?

    @classmethod
    def from_attrs(cls, attrs: List[Tuple[str, Optional[str]]]) -> "FileEntry":
        """
        Given the <a> element's attrs from parsing the simple html index,
        returns a new FileEntry.
        """
        d = dict(attrs)
        if d["href"] is None:  # pragma: no cover
            raise KeyError("Empty href")
        m = CHECKSUM_RE.match(d["href"])
        if m is None:
            raise UnexpectedFilename(d["href"])
        url = m.group("url")
        basename = m.group("basename")
        checksum = m.group("checksum")

        return cls(
            url=url,
            basename=basename,
            checksum=checksum,
            file_type=guess_file_type(basename),
            version=guess_version(basename)[1],
            requires_python=d.get("data-requires-python"),
        )

    @classmethod
    def from_json(cls, version: str, obj: Dict[str, Any]) -> "FileEntry":
        # We still guess file_type here because warehouse gets it wrong for
        # bsdist_dumb and reports them as sdist.
        return cls(
            url=obj["url"],
            basename=obj["filename"],
            checksum=f"sha256={obj['digests']['sha256']}",
            file_type=guess_file_type(obj["filename"]),
            version=version,
            requires_python=obj["requires_python"],
            size=obj["size"],
            upload_time=parse_time(obj["upload_time_iso_8601"]),
        )


def parse_time(t: str) -> datetime:
    """Returns a parsed time with optional fractional seconds."""
    # Timestamps before ~2009-02-16 do not have fractional seconds.
    t = t.rstrip("Z")
    fmt, _, fractional = t.partition(".")

    # This makes it microseconds
    fractional = fractional[:6].ljust(6, "0")

    return datetime.strptime(t.split(".")[0], ISO8601_FORMAT).replace(
        microsecond=int(fractional), tzinfo=timezone.utc
    )


@dataclass
class PackageRelease:
    version: str  # This is the original version, exactly as provided
    parsed_version: LooseVersion
    files: List[FileEntry]
    requires: Optional[List[str]] = None


@dataclass
class Package:
    name: str
    releases: Dict[LooseVersion, PackageRelease]
    requires: Optional[Sequence[str]] = None


def remove_suffix(basename: str) -> str:
    suffixes = [
        ".egg",
        ".whl",
        ".zip",
        ".gz",
        ".bz2",
        ".tar",
        ".exe",
        ".msi",
        ".rpm",
        ".dmg",
        ".tgz",
    ]
    for s in suffixes:
        if basename.endswith(s):
            basename = basename[: -len(s)]
    return basename


# TODO itu-r-468-weighting-1.0.3.tar.gz
# TODO uttt-0.3-1.tar.gz
def guess_version(basename: str) -> Tuple[str, str]:
    """
    Returns (package name, version) or raises.
    """
    # This should use whatever setuptools/pip/etc use, but I spent about 10
    # minutes and couldn't find it tonight.
    basename = remove_suffix(basename)

    match = NUMERIC_VERSION.match(basename)
    if not match:
        raise UnexpectedFilename(basename)
    return match.group(1), match.group(2)


class LinkGatherer(HTMLParser):
    def __init__(self, strict: bool = False):
        super().__init__()
        self.entries: List[FileEntry] = []
        self.strict = strict

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag == "a":
            try:
                fe = FileEntry.from_attrs(attrs)
            except UnexpectedFilename:
                if not self.strict:
                    return
                raise

            self.entries.append(fe)


def parse_index(
    pkg: str, cache: Cache, strict: bool = False, use_json: bool = False
) -> Package:
    loop = asyncio.get_event_loop()
    package: Package = loop.run_until_complete(
        async_parse_index(pkg, cache, strict, use_json)
    )
    return package


async def async_parse_index(
    pkg: str, cache: Cache, strict: bool = False, use_json: bool = False
) -> Package:
    package = Package(name=pkg, releases={})
    releases: Dict[LooseVersion, PackageRelease] = {}

    # The input order of releases in both cases is not correct; so we sort at
    # the end before adding to the Package.
    if not use_json:
        with open(await cache.async_fetch(pkg, url=None)) as f:
            gatherer = LinkGatherer(strict)
            gatherer.feed(f.read())

        for fe in gatherer.entries:
            v = fe.version
            pv = parse_version(v)
            if pv not in releases:
                releases[pv] = PackageRelease(version=v, parsed_version=pv, files=[])
            releases[pv].files.append(fe)
    else:
        # This will redirect away from canonical name if they differ
        url = urllib.parse.urljoin(cache.json_index_url, f"../pypi/{pkg}/json")
        with open(await cache.async_fetch(pkg, url=url)) as f:
            obj = json.loads(f.read())

        if obj.get("requires_dist") is not None:
            package.requires = obj["requires_dist"]

        for k, release in obj["releases"].items():
            if not release:
                # Some pre-warehouse projects have releases with no files; don't
                # bother because there's nothing to install, and they don't show
                # up in the simple index either.
                continue
            pv = parse_version(k)
            releases[pv] = PackageRelease(version=k, parsed_version=pv, files=[])
            for release_file in release:
                try:
                    releases[pv].files.append(FileEntry.from_json(k, release_file))
                except UnexpectedFilename:
                    if strict:
                        raise

    package.releases = dict(sorted(releases.items()))
    for rel in package.releases.values():
        rel.files.sort()

    return package
