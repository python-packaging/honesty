from setuptools import setup

setup(
    use_scm_version={"write_to": "honesty/__version__.py"},
    entry_points={"console_scripts": ["honesty = honesty.cmdline:cli"]},
)
