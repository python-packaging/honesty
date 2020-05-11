import os
import os.path
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Dict
from unittest import mock

from ..archive import archive_hashes, extract_and_get_names


def create_test_archive(
    path_contents: Dict[str, str], extension: str, format: str
) -> Path:
    """
    Create an archive with the specified characteristics.

    Caller is responsible for deleting.
    """
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        for path, contents in path_contents.items():
            (p / path).parent.mkdir(parents=True, exist_ok=True)
            with (p / path).open("w") as f:
                f.write(contents)

        name = tempfile.mktemp(suffix=f".{extension}")
        short_name = name.rsplit(".", 1)[0]
        tmp = shutil.make_archive(short_name, format, d)
        os.rename(tmp, name)
        return Path(name)


class ArchiveTest(unittest.TestCase):
    def test_extract(self) -> None:
        archive = create_test_archive(
            {
                "foo-0.1/setup.py": "setup()\n",
                "foo-0.1/src/proj/__init__.py": "",
                "foo-0.1/pyproject.toml": "[section]\n",
            },
            "whl",
            "zip",
        )
        try:
            with tempfile.TemporaryDirectory() as d:
                with mock.patch("honesty.archive.os.environ.get", return_value=d):
                    archive_root, names = extract_and_get_names(archive)
                    self.assertEqual(2, len(names))
                    # We didn't specify strip_top_level so these are both as in
                    # archive.
                    self.assertEqual(
                        {
                            os.path.join("foo-0.1", "setup.py"),
                            os.path.join("foo-0.1", "src", "proj", "__init__.py"),
                        },
                        {n[1] for n in names},
                    )
                    self.assertEqual(
                        {
                            os.path.join("foo-0.1", "setup.py"),
                            os.path.join("foo-0.1", "src", "proj", "__init__.py"),
                        },
                        {n[0] for n in names},
                    )

                    # We can call it a second time  with different args, and it
                    # doesn't actually extract again.
                    archive_root, names = extract_and_get_names(
                        archive, strip_top_level=True
                    )
                    self.assertEqual(2, len(names))
                    self.assertEqual(
                        {"setup.py", os.path.join("proj", "__init__.py")},
                        {n[1] for n in names},
                    )
                    self.assertEqual(
                        {
                            os.path.join("foo-0.1", "setup.py"),
                            os.path.join("foo-0.1", "src", "proj", "__init__.py"),
                        },
                        {n[0] for n in names},
                    )

                    # Another potential edge case, when patterns change
                    # (currently we extract everything the first time)
                    archive_root, names = extract_and_get_names(
                        archive, patterns=("*.toml",)
                    )
                    self.assertEqual(1, len(names))
                    self.assertEqual(
                        (
                            os.path.join("foo-0.1", "pyproject.toml"),
                            os.path.join("foo-0.1", "pyproject.toml"),
                        ),
                        names[0],
                    )
        finally:
            os.remove(archive)

    def test_hashes(self) -> None:
        archive = create_test_archive(
            {
                "foo-0.1/setup.py": "setup()\n",
                "foo-0.1/src/proj/__init__.py": "",
                "foo-0.1/pyproject.toml": "[section]\n",
            },
            "whl",
            "zip",
        )
        try:
            with tempfile.TemporaryDirectory() as d:
                with mock.patch("honesty.archive.os.environ.get", return_value=d):
                    hashes = archive_hashes(archive)
                    self.assertEqual(
                        {
                            os.path.join(
                                "foo-0.1", "setup.py"
                            ): "f568932ab271783a0234a22ed902131b7dfef0a9",
                            os.path.join(
                                "foo-0.1", "src", "proj", "__init__.py"
                            ): "da39a3ee5e6b4b0d3255bfef95601890afd80709",
                        },
                        hashes,
                    )

        finally:
            os.remove(archive)
