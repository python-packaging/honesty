import io
import sys
import unittest
import urllib.error
from typing import Any
from unittest.mock import patch

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from ..deps import (
    _find_compatible_version,
    convert_sdist_requires,
    DepEdge,
    DepNode,
    DepWalker,
    EnvironmentMarkers,
    print_deps,
    print_flat_deps,
    SeekableHttpFile,
)
from ..releases import FileEntry, FileType, Package, PackageRelease


class ConvertSdistRequiresTest(unittest.TestCase):
    def test_all(self) -> None:
        self.assertEqual(
            ["a"],
            convert_sdist_requires("a\n"),
        )
        self.assertEqual(
            ["a; python_version < '3.4'"],
            convert_sdist_requires("[:python_version < '3.4']\na\n"),
        )


v1 = Version("1.0")
v1_1 = Version("1.1")
v2 = Version("2.0")

FOO_PACKAGE = Package(
    name="foo",
    releases={
        v1: PackageRelease(version="1.0", parsed_version=v1, files=[]),
        v2: PackageRelease(
            version="2.0",
            parsed_version=v2,
            files=[
                FileEntry(
                    url="url",
                    basename="basename",
                    checksum="x",
                    file_type=FileType.UNKNOWN,
                    version="2.0",
                    requires_python="<4",
                )
            ],
        ),
    },
)

BAR_PACKAGE = Package(
    name="bar",
    releases={
        v1: PackageRelease("1.0", v1, [], requires=["foo"]),
    },
)


class EnvironmentMarkersTest(unittest.TestCase):
    def test_platforms(self) -> None:
        e = EnvironmentMarkers(sys_platform="win32")
        self.assertEqual("nt", e.os_name)
        e = EnvironmentMarkers(sys_platform="darwin")
        self.assertEqual("posix", e.os_name)
        e = EnvironmentMarkers(python_version="2.7.5")
        self.assertEqual("linux2", e.sys_platform)
        with self.assertRaises(TypeError):
            e = EnvironmentMarkers(sys_platform="x")


class FindCompatibleVersionTest(unittest.TestCase):
    def test_basic(self) -> None:
        three = Version("3.7.5")
        four = Version("4.0.0")
        v = _find_compatible_version(FOO_PACKAGE, SpecifierSet("==1.0"), three)
        self.assertEqual(v1, v)
        v = _find_compatible_version(FOO_PACKAGE, SpecifierSet("==2.0"), three)
        self.assertEqual(v2, v)
        v = _find_compatible_version(FOO_PACKAGE, SpecifierSet(">=2.0"), three)
        self.assertEqual(v2, v)
        v = _find_compatible_version(FOO_PACKAGE, SpecifierSet("<=2.0"), three)
        self.assertEqual(v2, v)
        v = _find_compatible_version(FOO_PACKAGE, SpecifierSet("<=1.0"), three)
        self.assertEqual(v1, v)
        v = _find_compatible_version(FOO_PACKAGE, SpecifierSet("!=2.0"), three)
        self.assertEqual(v1, v)

        with self.assertRaises(ValueError):
            _find_compatible_version(FOO_PACKAGE, SpecifierSet("<1.0"), three)
        with self.assertRaises(InvalidSpecifier):
            _find_compatible_version(FOO_PACKAGE, SpecifierSet("$1.0"), three)

        v = _find_compatible_version(FOO_PACKAGE, SpecifierSet(""), four)
        self.assertEqual(v1, v)

    def test_respect_already_chosen(self) -> None:
        three = Version("3.7.5")
        # This returns v1 with no already_chosen
        v = _find_compatible_version(
            FOO_PACKAGE, SpecifierSet(""), three, already_chosen={"foo": Version("2.0")}
        )
        self.assertEqual(v2, v)

    def test_current_version_callback(self) -> None:
        three = Version("3.7.5")

        def current_version(p: str) -> str:
            return "2.0"

        # This would normally find v1 ("1.0") on its own
        v = _find_compatible_version(
            FOO_PACKAGE,
            SpecifierSet(""),
            three,
            current_versions_callback=current_version,
        )
        self.assertEqual(Version("2.0"), v)

    def test_current_version_callback_nonpublic(self) -> None:
        three = Version("3.7.5")

        def current_version(p: str) -> str:
            return "2.99"

        # This would normally find v1 ("1.0") on its own
        v = _find_compatible_version(
            FOO_PACKAGE,
            SpecifierSet(""),
            three,
            current_versions_callback=current_version,
        )
        self.assertEqual(Version("2.99"), v)


class TestSeekableHttpFile(unittest.TestCase):
    def test_live(self) -> None:
        # This test requires internet access.
        f = SeekableHttpFile("http://timhatch.com/projects/http-tests/sequence_100.txt")
        self.assertEqual(0, f.pos)
        self.assertEqual(292, f.length)
        self.assertEqual(b"1\n", f.read(2))
        f.seek(-4, 2)
        self.assertEqual(b"100\n", f.read(4))
        f.seek(-4, 2)
        self.assertEqual(b"100\n", f.read())
        self.assertEqual(292, f.tell())
        self.assertTrue(f.seekable())
        self.assertEqual(b"", f.read(0))
        f.seek(1, 0)
        self.assertEqual(1, f.pos)
        f.seek(2, 1)
        self.assertEqual(3, f.pos)

        # tests the read doing a fetch
        f.seek(-4, 2)
        f.end_cache_start = f.length
        self.assertEqual(b"100\n", f.read(4))

        # errors
        with self.assertRaises(ValueError):
            f.seek(0, 99)

    def test_live_404(self) -> None:
        # This test requires internet access.
        with self.assertRaises(urllib.error.HTTPError):
            SeekableHttpFile(
                "http://timhatch.com/projects/http-tests/response/?code=404"
            )


A_PACKAGE = Package(
    name="a",
    releases={
        v1: PackageRelease("1.0", v1, [], ["b (==1.0)"]),
    },
)
B_PACKAGE = Package(
    name="b",
    releases={
        v1: PackageRelease("1.0", v1, [], ["c"]),
        v2: PackageRelease("2.0", v2, [], []),
    },
)
C_PACKAGE = Package(
    name="c",
    releases={
        v1_1: PackageRelease("1.1", v1_1, [], []),
    },
)


def get_abc_walked() -> DepWalker:
    def parse(pkg: str, cache: Any, use_json: bool = False) -> Package:
        if pkg == "a":
            return A_PACKAGE
        elif pkg == "b":
            return B_PACKAGE
        elif pkg == "c":
            return C_PACKAGE
        else:
            raise NotImplementedError(f"Unknown package {pkg}")

    with patch("honesty.deps.parse_index") as parse_mock:
        parse_mock.side_effect = parse

        d = DepWalker("a", "3.6.0")
        d.walk(include_extras=False)

    return d


class DepWalkerTest(unittest.TestCase):
    def test_walk(self) -> None:
        d = get_abc_walked()

        print(d.root)
        assert d.root is not None
        self.assertEqual("a", d.root.name)
        self.assertEqual(Version("1.0"), d.root.version)
        self.assertEqual(True, d.root.done)

        self.assertEqual(1, len(d.root.deps))
        self.assertEqual("b", d.root.deps[0].target.name)
        self.assertEqual(1, len(d.root.deps[0].target.deps))
        self.assertEqual("c", d.root.deps[0].target.deps[0].target.name)
        self.assertEqual(0, len(d.root.deps[0].target.deps[0].target.deps))

    @patch("honesty.deps.read_metadata_sdist")
    @patch("honesty.deps.read_metadata_remote_wheel")
    @patch("honesty.deps.read_metadata_wheel")
    def test_fetch_single_deps(
        self, r_wheel: Any, r_remote_wheel: Any, r_sdist: Any
    ) -> None:
        _ = DepWalker("a", "3.6.0")


class PrintDepsTest(unittest.TestCase):
    @patch("sys.stdout", io.StringIO())
    def test_basic(self) -> None:
        d = get_abc_walked()
        tree = d.root
        assert tree
        fake_root = DepNode("", version=v1, deps=[DepEdge(target=tree)])
        print_deps(fake_root, set())
        self.assertEqual(
            """\
a (==1.0) via * no whl
. b (==1.0) via ==1.0 no whl
. . c (==1.1) via * no whl
""",
            sys.stdout.getvalue(),  # type: ignore
        )


class PrintFlatDepsTest(unittest.TestCase):
    @patch("sys.stdout", io.StringIO())
    def test_basic(self) -> None:
        d = get_abc_walked()
        tree = d.root
        assert tree
        fake_root = DepNode("", version=v1, deps=[DepEdge(target=tree)])
        print_flat_deps(fake_root, set())
        self.assertEqual(
            """\
c==1.1
b==1.0
a==1.0
""",
            sys.stdout.getvalue(),  # type: ignore
        )
