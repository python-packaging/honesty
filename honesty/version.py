from typing import Union

from packaging.version import LegacyVersion, Version
from packaging.version import parse as parse_version

LooseVersion = Union[Version, LegacyVersion]

__all__ = ["LooseVersion", "parse_version", "Version", "LegacyVersion"]
