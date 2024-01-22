import unittest
from unittest import mock

import click
from infer_license.types import License

from packaging.version import Version

from ..cache import Cache
from ..checker import _version_helper, guess_license, has_nativemodules, is_pep517
from ..releases import FileType, parse_index


class CheckerTest(unittest.TestCase):
    def test_version_helper_live(self) -> None:
        # N.b. does not specify fresh_index, so this can reuse downloads
        c = Cache()
        pkg = parse_index("honesty", c)
        archive_root, names = _version_helper(
            pkg, Version("0.2.1"), c, FileType.BDIST_WHEEL, ("LICENSE",)
        )
        self.assertEqual([("honesty-0.2.1.dist-info/LICENSE", "LICENSE")], names)

        with self.assertRaisesRegex(click.ClickException, "honesty no BDIST_DMG"):
            _version_helper(pkg, Version("0.2.1"), c, FileType.BDIST_DMG, ("LICENSE",))

    def test_has_nativemodules(self) -> None:
        with mock.patch(
            "honesty.checker._version_helper",
            return_value=("/foo", [("foo/x.bin", "x.bin")]),
        ):
            self.assertFalse(has_nativemodules(mock.Mock(), None, False, None))  # type: ignore[arg-type]

        with mock.patch(
            "honesty.checker._version_helper",
            return_value=("/foo", [("foo/x.so", "x.so")]),
        ):
            self.assertTrue(has_nativemodules(mock.Mock(), None, False, None))  # type: ignore[arg-type]

    def test_has_nativemodules_live(self) -> None:
        # N.b. does not specify fresh_index, so this can reuse downloads
        c = Cache()
        pkg = parse_index("honesty", c)
        self.assertFalse(has_nativemodules(pkg, Version("0.2.1"), False, c))
        pkg = parse_index("black", c)
        self.assertTrue(has_nativemodules(pkg, Version("23.9.1"), False, c))
        with self.assertRaisesRegex(
            click.ClickException, "version=0.0.99 not available"
        ):
            has_nativemodules(pkg, Version("0.0.99"), False, c)

    def test_guess_license_live(self) -> None:
        # N.b. does not specify fresh_index, so this can reuse downloads
        c = Cache()
        pkg = parse_index("honesty", c)
        lic = guess_license(pkg, Version("0.2.1"), False, c)
        assert isinstance(lic, License)
        self.assertEqual("MIT License", lic.name)
        # with self.assertRaisesRegex(click.ClickException, "version=0.0.99 not available"):
        #    has_nativemodules(pkg, Version("0.0.99"), False, c)

    def test_ispep517_live(self) -> None:
        # N.b. does not specify fresh_index, so this can reuse downloads
        c = Cache()
        pkg = parse_index("honesty", c)
        self.assertFalse(is_pep517(pkg, Version("0.2.1"), False, c))
        pkg = parse_index("black", c)
        self.assertTrue(is_pep517(pkg, Version("23.9.1"), False, c))
