import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from honesty.releases import (
    FileType,
    UnexpectedFilename,
    guess_file_type,
    guess_version,
    parse_index,
)

WOAH_INDEX_CONTENTS = b"""\
<!DOCTYPE html>
<html>
  <head>
    <title>Links for woah</title>
  </head>
  <body>
    <h1>Links for woah</h1>
    <a href="https://files.pythonhosted.org/packages/69/c9/a9951fcb2e706dd14cfc5d57a33eadc38a2b7477c82c12c229de5f6115db/woah-0.1-py3-none-any.whl#sha256=e705573ea8a88ec772174deea6a80c79f1e8b7e96130e27eee14b21d63f4e7f8" data-requires-python="&gt;=3.6">woah-0.1-py3-none-any.whl</a><br/>
    <a href="https://files.pythonhosted.org/packages/8f/3f/cd6d2edb9cf7049788db971fb5359cbde9fb28801d55b1aafa8f0df4813a/woah-0.1.tar.gz#sha256=d0760a3696271db53c361c950d93ceca7a022b5d739c0005e3bfb65785dd9d97" data-requires-python="&gt;=3.6">woah-0.1.tar.gz</a><br/>
    <a href="https://files.pythonhosted.org/packages/5e/95/871090fc9c10630d457b44967c9bb9c544b858cd3a2fe6dd60f9e169d99f/woah-0.2-py3-none-any.whl#sha256=e701a8d020a09fa32199cc74b386a3bf9730910fd46a6301fbb8203f287b27d7" data-requires-python="&gt;=3.6">woah-0.2-py3-none-any.whl</a><br/>
    <a href="https://files.pythonhosted.org/packages/fb/f2/dc6873f2763ffb457d3dbe4224ea59b21a8495fa0ef86d230b78cdba0f22/woah-0.2.tar.gz#sha256=62a886ed5e16506c039216dc0b5f342e72228e2038c750a1a7574321af6d8d68" data-requires-python="&gt;=3.6">woah-0.2.tar.gz</a><br/>
    </body>
</html>
<!--SERIAL 5860225-->
"""

LONG_NAME = "scipy-0.14.1rc1.dev_205726a-cp33-cp33m-macosx_10_6_intel.macosx_10_9_intel.macosx_10_9_x86_64.macosx_10_10_intel.macosx_10_10_x86_64.whl"


class ReleasesTest(unittest.TestCase):
    @mock.patch("honesty.cache.fetch")
    def test_get_entries(self, mock_fetch: Any) -> None:
        with tempfile.NamedTemporaryFile(mode="wb") as f:
            f.write(WOAH_INDEX_CONTENTS)
            f.flush()
            mock_fetch.return_value = Path(f.name)

            pkg = parse_index("woah")

        self.assertEqual("woah", pkg.name)
        self.assertEqual(2, len(pkg.releases))

        v01 = pkg.releases["0.1"]
        self.assertEqual(2, len(v01.files))

        self.assertEqual(
            "https://files.pythonhosted.org/packages/69/c9/a9951fcb2e706dd14cfc5d57a33eadc38a2b7477c82c12c229de5f6115db/woah-0.1-py3-none-any.whl",
            v01.files[0].url,
        )
        self.assertEqual("woah-0.1-py3-none-any.whl", v01.files[0].basename)
        self.assertEqual(
            "sha256=e705573ea8a88ec772174deea6a80c79f1e8b7e96130e27eee14b21d63f4e7f8",
            v01.files[0].checksum,
        )

    def test_guess_version(self) -> None:
        self.assertEqual(("foo", "0.1"), guess_version("foo-0.1.tar.gz"))
        self.assertEqual(("foo", "0.1"), guess_version("foo-0.1-py3-none.whl"))
        self.assertEqual(("foo", "0.1"), guess_version("foo-0.1-any-none.whl"))
        with self.assertRaises(UnexpectedFilename):
            guess_version("foo.tar.gz")

        self.assertEqual(("scipy", "0.14.1rc1.dev_205726a"), guess_version(LONG_NAME))
        self.assertEqual(
            ("javatools", "1.4.0"),
            guess_version("javatools-1.4.0.macosx-10.14-x86_64.tar.gz"),
        )
        self.assertEqual(("pypi", "2"), guess_version("pypi-2.tar.gz"))

    def test_guess_file_type(self) -> None:
        self.assertEqual(FileType.SDIST, guess_file_type("foo-0.1.tar.gz"))
        self.assertEqual(
            FileType.BDIST_WHEEL, guess_file_type("foo-0.1-manylinux1.whl")
        )
        self.assertEqual(FileType.BDIST_EGG, guess_file_type("foo-0.1.egg"))
        self.assertEqual(
            FileType.BDIST_DUMB,
            guess_file_type("javatools-1.4.0.macosx-10.14-x86_64.tar.gz"),
        )
        self.assertEqual(FileType.UNKNOWN, guess_file_type("foo-0.1.exe"))
        self.assertEqual(
            FileType.BDIST_DUMB,
            guess_file_type("pyre-check-0.0.29-macosx_10_11_x86_64.tar.gz"),
        )
        self.assertEqual(FileType.SDIST, guess_file_type("pypi-2.tar.gz"))
        with self.assertRaises(UnexpectedFilename):
            guess_file_type("ibm_db.tar.gz")
