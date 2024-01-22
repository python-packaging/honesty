import unittest

from click.testing import CliRunner

from ..cmdline import revs


class RevsTest(unittest.TestCase):
    def test_revs_of_honesty_defaults(self) -> None:
        runner = CliRunner()
        # first one primes checkout, producing more output
        result = runner.invoke(revs, ["honesty==0.2.1"])
        # second one actually tests behavior
        result = runner.invoke(revs, ["honesty==0.2.1"])
        self.assertEqual(
            """\
honesty==0.2.1 sdist:
  p=1.0 ['tags/v0.2.1']
""",
            result.output,
        )

    def test_revs_of_honesty_short_circuit(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            revs, ["--try-order=likely_tags,branches", "--verbose", "honesty==0.2.1"]
        )
        self.assertEqual(
            """\
honesty==0.2.1 sdist:
Try tag v0.2.1
  p=1.0 ['tags/v0.2.1']
""",
            result.output,
        )

    def test_revs_of_honesty_branches(self) -> None:
        # This is mainly for coverage, we're not being nearly picky enough about
        # the output here...
        runner = CliRunner()
        result = runner.invoke(
            revs, ["--try-order=branches", "--verbose", "honesty==0.2.1"]
        )
        self.assertIn("Try branch origin/main", result.output)
        self.assertIn("p=1.0", result.output)
        self.assertIn("'21d4c02'", result.output)
