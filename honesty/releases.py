import asyncio
import enum
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .cache import Cache

# Apologies in advance, "parsing" html via regex
ENTRY_RE = re.compile(
    r'href="(?P<url>[^"#]+\/(?P<basename>[^#]+))#(?P<checksum>[^="]+=[a-f0-9]+)"'
)
NUMERIC_VERSION = re.compile(
    r"^(?P<package>.*?)-(?P<version>[0-9][^-]*?)"
    r"(?P<suffix>(?P<platform>\.macosx|\.linux)?-.*)?$"
)


SDIST_EXTENSIONS = (".tar.gz", ".zip", ".tar.bz2")

# TODO IntFlag, or a separate field for platform
class FileType(enum.IntEnum):
    UNKNOWN = 0
    SDIST = 1
    BDIST_WHEEL = 2
    BDIST_EGG = 3
    BDIST_DUMB = 4


class UnexpectedFilename(Exception):
    pass


def guess_file_type(filename: str) -> FileType:
    if filename.endswith(".egg"):
        return FileType.BDIST_EGG
    elif filename.endswith(".whl"):
        return FileType.BDIST_WHEEL
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
    else:  # .exe and .rpm at least
        return FileType.UNKNOWN


@dataclass
class FileEntry:
    url: str  # https://files.pythonhosted.../foo-1.0.tgz
    basename: str  # foo-1.0.tgz
    checksum: str  # 'sha256=<foo>'
    file_type: FileType
    requires_python: Optional[str] = None  # '&gt;=3.6'
    # TODO extract upload date?


@dataclass
class PackageRelease:
    version: str
    files: List[FileEntry]


@dataclass
class Package:
    name: str
    releases: Dict[str, PackageRelease]


def remove_suffix(basename: str) -> str:
    suffixes = [".egg", ".whl", ".zip", ".gz", ".bz2", ".tar"]
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


def parse_index(pkg: str, cache: Cache, strict: bool = False) -> Package:
    loop = asyncio.get_event_loop()
    package: Package = loop.run_until_complete(async_parse_index(pkg, cache, strict))
    return package


async def async_parse_index(pkg: str, cache: Cache, strict: bool = False) -> Package:
    package = Package(name=pkg, releases={})
    with open(await cache.async_fetch(pkg, url=None)) as f:
        for match in ENTRY_RE.finditer(f.read()):
            # TODO guess_version can also raise this, but they currently use the
            # same regex; this should get parsed out once maybe in a method on
            # FileEntry.
            try:
                file_type = guess_file_type(match.group("basename"))
            except UnexpectedFilename:
                if not strict:
                    continue
                raise

            fe = FileEntry(file_type=file_type, **match.groupdict())
            v = guess_version(fe.basename)[1]
            if v not in package.releases:
                package.releases[v] = PackageRelease(version=v, files=[])
            package.releases[v].files.append(fe)

    return package
