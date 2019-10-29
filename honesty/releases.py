import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .cache import fetch

# Apologies in advance, "parsing" html via regex
ENTRY_RE = re.compile(
    r'href="(?P<url>[^"#]+\/(?P<basename>[^#]+))#(?P<checksum>[^="]+=[a-f0-9]+)"'
)


@dataclass
class FileEntry:
    url: str  # https://files.pythonhosted.../foo-1.0.tgz
    basename: str  # foo-1.0.tgz
    checksum: str  # 'sha256=<foo>'
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


NUMERIC_VERSION = re.compile(r"^(.*?)-([0-9.b]+)(-[^0-9].*)?$")


def guess_version(basename: str) -> Tuple[str, str]:
    """
    Returns (package name, version) or raises.
    """
    # This should use whatever setuptools/pip/etc use, but I spent about 10
    # minutes and couldn't find it tonight.
    suffixes = [".egg", ".whl", ".tar.gz", ".zip"]
    for s in suffixes:
        if basename.endswith(s):
            basename = basename[: -len(s)]

    match = NUMERIC_VERSION.match(basename)
    if not match:
        raise ValueError("Could not parse version", basename)
    return match.group(1), match.group(2)


def parse_index(pkg: str) -> Package:
    package = Package(name=pkg, releases={})
    with open(fetch(pkg)) as f:
        for match in ENTRY_RE.finditer(f.read()):
            fe = FileEntry(**match.groupdict())
            v = guess_version(fe.basename)[1]
            if v not in package.releases:
                package.releases[v] = PackageRelease(version=v, files=[])
            package.releases[v].files.append(fe)

    return package
