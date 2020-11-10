import datetime
import json
import re
import tempfile
import unittest

from ..releases import (
    FileType,
    UnexpectedFilename,
    guess_file_type,
    guess_version,
    parse_index,
    parse_time,
)
from ..version import parse_version
from .cache import FakeCache

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

WOAH_JSON_CONTENTS = b"""\
{"info":{"author":"Tim Hatch","author_email":"tim@timhatch.com","bugtrack_url":n
ull,"classifiers":["Development Status :: 4 - Beta","Environment :: Console","Li
cense :: OSI Approved :: Apache Software License","Programming Language :: Pytho
n","Programming Language :: Python :: 3","Programming Language :: Python :: 3.6"
,"Programming Language :: Python :: 3.7","Programming Language :: Python :: 3 ::
 Only","Topic :: Utilities"],"description":"# Woah\\n\\nWoah is a script that yo
u can wrap commands with, and it will wait until the\\nload average is reasonabl
e before running them.\\n\\n# Usage\\n\\nSimilar to `nice`, you just start your \
command with `woah` and everything after\\nthat will be run unchanged.\\n\\nSay,
 if you have a lot of other things going on, and want your backup to wait\\nfor
 things to settle down...\\n\\n```\\nwoah tar -xvzf /tmp/foo.tar users/tim\\n```\\
n\\nOr you\'re running multiple things with xargs, but some are more expensive
 than\\nothers and you want to keep your machine somewhat responsive...\\n\\n```\\
n(cd /users; ls -d *) | xargs -P32 -n1 --no-run-if-empty woah tar /tmp/{} /user
s/{}\\n```\\n\\n# Bugs and such\\n\\nhttps://github.com/thatch/woah\\n\\n# Licen
se\\n\\nApache 2.0\\n\\n\\n","description_content_type":"text/markdown","docs_ur
l":null,"download_url":"","downloads":{"last_day":-1,"last_month":-1,"last_week"
:-1},"home_page":"https://github.com/thatch/woah","keywords":"","license":"Apach
e 2.0","maintainer":"","maintainer_email":"","name":"woah","package_url":"https:
//pypi.org/project/woah/","platform":"","project_url":"https://pypi.org/project/
woah/","project_urls":{"Homepage":"https://github.com/thatch/woah"},"release_url
":"https://pypi.org/project/woah/0.2/","requires_dist":null,"requires_python":">
=3.6","summary":"Wait for reasonable load average","version":"0.2"},"last_serial
":5860225,"releases":{"0.1":[{"comment_text":"","digests":{"md5":"458804f2290028
8b7078ca1e3f39eb90","sha256":"e705573ea8a88ec772174deea6a80c79f1e8b7e96130e27eee
14b21d63f4e7f8"},"downloads":-1,"filename":"woah-0.1-py3-none-any.whl","has_sig"
:false,"md5_digest":"458804f22900288b7078ca1e3f39eb90","packagetype":"bdist_whee
l","python_version":"py3","requires_python":">=3.6","size":6511,"upload_time":"2
019-09-19T14:32:17","upload_time_iso_8601":"2019-09-19T14:32:17.358350Z","url":"
https://files.pythonhosted.org/packages/69/c9/a9951fcb2e706dd14cfc5d57a33eadc38a
2b7477c82c12c229de5f6115db/woah-0.1-py3-none-any.whl"},{"comment_text":"","diges
ts":{"md5":"8361f4eb6f0b5478540b39f851793b6b","sha256":"d0760a3696271db53c361c95
0d93ceca7a022b5d739c0005e3bfb65785dd9d97"},"downloads":-1,"filename":"woah-0.1.t
ar.gz","has_sig":false,"md5_digest":"8361f4eb6f0b5478540b39f851793b6b","packaget
ype":"sdist","python_version":"source","requires_python":">=3.6","size":1868,"up
load_time":"2019-09-19T14:32:19","upload_time_iso_8601":"2019-09-19T14:32:19.568
441Z","url":"https://files.pythonhosted.org/packages/8f/3f/cd6d2edb9cf7049788db9
71fb5359cbde9fb28801d55b1aafa8f0df4813a/woah-0.1.tar.gz"}],"0.2":[{"comment_text
":"","digests":{"md5":"79e7fd3d30a012b751d66ce881ccdc2a","sha256":"e701a8d020a09
fa32199cc74b386a3bf9730910fd46a6301fbb8203f287b27d7"},"downloads":-1,"filename":
"woah-0.2-py3-none-any.whl","has_sig":false,"md5_digest":"79e7fd3d30a012b751d66c
e881ccdc2a","packagetype":"bdist_wheel","python_version":"py3","requires_python"
:">=3.6","size":8355,"upload_time":"2019-09-20T05:39:40","upload_time_iso_8601":
"2019-09-20T05:39:40.581697Z","url":"https://files.pythonhosted.org/packages/5e/
95/871090fc9c10630d457b44967c9bb9c544b858cd3a2fe6dd60f9e169d99f/woah-0.2-py3-non
e-any.whl"},{"comment_text":"","digests":{"md5":"0b5eecde7203c8ff2260a51825dd1a9
c","sha256":"62a886ed5e16506c039216dc0b5f342e72228e2038c750a1a7574321af6d8d68"},
"downloads":-1,"filename":"woah-0.2.tar.gz","has_sig":false,"md5_digest":"0b5eec
de7203c8ff2260a51825dd1a9c","packagetype":"sdist","python_version":"source","req
uires_python":">=3.6","size":3255,"upload_time":"2019-09-20T05:39:41","upload_ti
me_iso_8601":"2019-09-20T05:39:41.862688Z","url":"https://files.pythonhosted.org
/packages/fb/f2/dc6873f2763ffb457d3dbe4224ea59b21a8495fa0ef86d230b78cdba0f22/woa
h-0.2.tar.gz"}]},"urls":[{"comment_text":"","digests":{"md5":"79e7fd3d30a012b751
d66ce881ccdc2a","sha256":"e701a8d020a09fa32199cc74b386a3bf9730910fd46a6301fbb820
3f287b27d7"},"downloads":-1,"filename":"woah-0.2-py3-none-any.whl","has_sig":fal
se,"md5_digest":"79e7fd3d30a012b751d66ce881ccdc2a","packagetype":"bdist_wheel","
python_version":"py3","requires_python":">=3.6","size":8355,"upload_time":"2019-
09-20T05:39:40","upload_time_iso_8601":"2019-09-20T05:39:40.581697Z","url":"http
s://files.pythonhosted.org/packages/5e/95/871090fc9c10630d457b44967c9bb9c544b858
cd3a2fe6dd60f9e169d99f/woah-0.2-py3-none-any.whl"},{"comment_text":"","digests":
{"md5":"0b5eecde7203c8ff2260a51825dd1a9c","sha256":"62a886ed5e16506c039216dc0b5f
342e72228e2038c750a1a7574321af6d8d68"},"downloads":-1,"filename":"woah-0.2.tar.g
z","has_sig":false,"md5_digest":"0b5eecde7203c8ff2260a51825dd1a9c","packagetype"
:"sdist","python_version":"source","requires_python":">=3.6","size":3255,"upload
_time":"2019-09-20T05:39:41","upload_time_iso_8601":"2019-09-20T05:39:41.862688Z
","url":"https://files.pythonhosted.org/packages/fb/f2/dc6873f2763ffb457d3dbe422
4ea59b21a8495fa0ef86d230b78cdba0f22/woah-0.2.tar.gz"}]}
""".replace(
    b"\n", b""
)

LONG_NAME = "scipy-0.14.1rc1.dev_205726a-cp33-cp33m-macosx_10_6_intel.macosx_10_9_intel.macosx_10_9_x86_64.macosx_10_10_intel.macosx_10_10_x86_64.whl"


class ReleasesTest(unittest.TestCase):
    def test_get_entries(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            c = FakeCache(d, {("woah", None): WOAH_INDEX_CONTENTS})
            pkg = parse_index("woah", c)  # type: ignore

        self.assertEqual("woah", pkg.name)
        self.assertEqual(2, len(pkg.releases))

        v01 = pkg.releases[parse_version("0.1")]
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
        self.assertEqual(">=3.6", v01.files[0].requires_python)
        self.assertEqual(None, v01.files[0].upload_time)

    def test_get_entries_json(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            c = FakeCache(
                d, {("woah", "https://pypi.org/pypi/woah/json"): WOAH_JSON_CONTENTS}
            )
            pkg = parse_index("woah", c, use_json=True)  # type: ignore

        self.assertEqual("woah", pkg.name)
        self.assertEqual(2, len(pkg.releases))

        v01 = pkg.releases[parse_version("0.1")]
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
        self.assertEqual(">=3.6", v01.files[0].requires_python)
        self.assertEqual(
            datetime.datetime(
                2019, 9, 19, 14, 32, 17, 358350, tzinfo=datetime.timezone.utc
            ),
            v01.files[0].upload_time,
        )

    def test_get_entries_json_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            t = json.loads(WOAH_JSON_CONTENTS)
            x = {
                "0.20": t["releases"]["0.1"],
                "0.9": t["releases"]["0.2"],
            }
            t["releases"] = x
            c = FakeCache(
                d,
                {
                    ("woah", "https://pypi.org/pypi/woah/json"): json.dumps(t).encode(
                        "utf-8"
                    )
                },
            )
            pkg = parse_index("woah", c, use_json=True)  # type: ignore

        self.assertEqual(
            [parse_version("0.9"), parse_version("0.20")], list(pkg.releases.keys())
        )

    def test_error_on_unexpected_filename_regex(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            c = FakeCache(
                d, {("woah", None): re.sub(rb'#.*?"', b'"', WOAH_INDEX_CONTENTS)}
            )
            with self.assertRaises(UnexpectedFilename):
                parse_index("woah", c, strict=True)  # type: ignore

    def test_strict(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            c = FakeCache(
                d, {("woah", None): WOAH_INDEX_CONTENTS.replace(b"woah-0.1", b"woah")}
            )
            with self.assertRaises(UnexpectedFilename):
                parse_index("woah", c, strict=True)  # type: ignore

    def test_non_strict(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            c = FakeCache(
                d, {("woah", None): WOAH_INDEX_CONTENTS.replace(b"woah-0.1", b"woah")}
            )
            pkg = parse_index("woah", c, strict=False)  # type: ignore

        self.assertEqual(1, len(pkg.releases))

        v02 = pkg.releases[parse_version("0.2")]
        self.assertEqual(2, len(v02.files))

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
        self.assertEqual(
            ("psutil", "5.3.0"), guess_version("psutil-5.3.0.win-amd64-py3.6.exe"),
        )
        self.assertEqual(
            ("psutil", "5.3.0"), guess_version("psutil-5.3.0.win32-py3.6.exe"),
        )
        self.assertEqual(
            ("simplejson", "3.12.0"), guess_version("simplejson-3.12.0.win32.exe")
        )

    def test_guess_file_type(self) -> None:
        expected = [
            ("foo-0.1", FileType.UNKNOWN),
            ("foo-0.1.tar.gz", FileType.SDIST),
            ("pypi-2.tar.gz", FileType.SDIST),
            ("foo-0.1.dmg", FileType.BDIST_DMG),
            # These two are real examples, and yes there's a dot vs dash
            # discrepancy
            ("javatools-1.4.0.macosx-10.14-x86_64.tar.gz", FileType.BDIST_DUMB),
            ("pyre-check-0.0.29-macosx_10_11_x86_64.tar.gz", FileType.BDIST_DUMB),
            ("foo-0.1.egg", FileType.BDIST_EGG),
            ("foo-0.1.msi", FileType.BDIST_MSI),
            ("foo-0.1.rpm", FileType.BDIST_RPM),
            ("foo-0.1-manylinux.whl", FileType.BDIST_WHEEL),
            ("foo-0.1.exe", FileType.BDIST_WININST),
        ]

        for a, b in expected:
            with self.subTest(a):
                self.assertEqual(b, guess_file_type(a))

        with self.assertRaises(UnexpectedFilename):
            guess_file_type("ibm_db.tar.gz")

    def test_parse_time(self) -> None:
        v = parse_time("2019-09-19T14:32:17.358350")
        self.assertEqual(
            datetime.datetime(
                2019, 9, 19, 14, 32, 17, 358350, tzinfo=datetime.timezone.utc
            ),
            v,
        )

        v = parse_time("2019-09-19T14:32:17")
        self.assertEqual(
            datetime.datetime(2019, 9, 19, 14, 32, 17, 0, tzinfo=datetime.timezone.utc),
            v,
        )

        v = parse_time("2019-09-19T14:32:17.123")
        self.assertEqual(
            datetime.datetime(
                2019, 9, 19, 14, 32, 17, 123000, tzinfo=datetime.timezone.utc
            ),
            v,
        )
