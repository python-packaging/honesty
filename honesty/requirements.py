# This is an especially simple version of requirements parsing; we do the simple
# thing here to avoid extra deps or fragile APIs, at the expense of missing some
# deps and false-positives.

from glob import glob
from pathlib import Path
from typing import Iterator

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

# These all have iter- prefixes because I expect a more public api to pick a
# couple and return sets instead.


def _iter_simple_requirements(path: Path) -> Iterator[Requirement]:
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            print("Ignoring", line)
            continue

        # N.b. Requirement does not canonicalize its name
        yield Requirement(line)


def iter_requirement_names(path: Path) -> Iterator[str]:
    """
    Returns the canonical names from the given requirements.txt
    """
    # TODO support, or document non-support, for git references

    for req in _iter_simple_requirements(path):
        yield canonicalize_name(req.name)


def iter_glob_all_requirement_names(comma_separated_patterns: str) -> Iterator[str]:
    for pattern in comma_separated_patterns.split(","):
        if pattern:
            for filename in sorted(glob(pattern)):
                # We can't just use Path.glob because you mgiht pass
                # 'reqs/*.txt' and this is considered a non-relative pattern.
                yield from iter_requirement_names(Path(filename))
