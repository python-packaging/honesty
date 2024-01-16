from setuptools import setup

setup(
    use_scm_version=True,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Utilities",
    ],
    entry_points={"console_scripts": ["honesty = honesty.cmdline:cli"]},
    install_requires=[
        "aiohttp >= 3.6",
        "appdirs >= 1.4",
        "click >= 7.0",
        "infer-license >= 0.0.6",
        "setuptools",  # for pkg_resources
    ],
)
