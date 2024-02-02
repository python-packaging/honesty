import hashlib
import unittest
from pathlib import Path

from click.testing import CliRunner

from ..cmdline import download, extract, license


class DownloadTest(unittest.TestCase):
    def test_honesty_download(self) -> None:
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(download, ["honesty==0.2.1"])
        hasher = hashlib.sha1()
        hasher.update(Path(result.output.strip()).read_bytes())
        self.assertEqual("4c7f15d7f1c291ada81fe333d3672283bc7437f9", hasher.hexdigest())
        self.assertEqual(0, result.exit_code)

        result = runner.invoke(download, ["honesty==0.2.2"])
        self.assertEqual(
            "Error: The version 0.2.2 does not exist for honesty\n", result.stderr
        )
        self.assertEqual(1, result.exit_code)


class ExtractTest(unittest.TestCase):
    def test_honesty_extract(self) -> None:
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(extract, ["honesty==0.2.1"])
        self.assertTrue(Path(result.output.strip(), "MANIFEST.in").exists())


class LicenseTest(unittest.TestCase):
    def test_honesty_license(self) -> None:
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(license, ["honesty==0.2.1"])
        self.assertEqual("honesty==0.2.1: MIT\n", result.output)
        self.assertEqual(0, result.exit_code)
