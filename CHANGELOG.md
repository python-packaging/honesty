honesty
=======

v0.3.0a3
--------

* Feature: Compatible with python 3.8-3.12 now.
* Fix: Work with packaging after the LegacyVersion removal.

v0.3.0a2
--------

* Feature: point-in-time resolution in `honesty deps --historical` (still not a
  solver)
* Fix: actually freshen simple-index (#18)
* Fix: sort releases
* Fix: windows filename parsing improvement
* Fix: more defensive about dep cycles
* Fix: update skel, workflow tests on 3.9 now

v0.3.0a1
--------

* Dev: most config is now static in `setup.cfg`
* Feature: `honesty deps` subcommand
* Feature: `honesty [cmd]` allows multiple package names
* Fix: versions are now sorted once, and better typed
* Fix: windows compat (#7, #13)
* Fix: include py.typed
* Fix: no longer build a "universal" wheel

v0.2.1
------

* Feature: allow overriding `aiohttp.ClientSession` args, say to include a
  proxy connector
* Fix: Use `appdirs` for most cache locations

v0.2.0
------

* Feature: `honesty age` to print how old a release is
* Feature: initial json-index support (on by default in CLI, not API)

v0.1.3
------

* Feature: `honesty extract`
* Feature: `honesty license` to guess a license using `infer-license` lib
* Fix: better filename parsing
* Fix: better html parsing
* Fix: handle `requires_python`
* Fix: License is now MIT
* Fix: tests work better on windows

v0.1.2
------

* Fix: console script works now
* Fix: better tests
* Fix: slimmer deps, drops requests and arlib

v0.1.1
------

* Fix: `honesty ispep517` and `honesty native` bug

v0.1.0
------

* Feature: `honesty download` (to download sdist)
* Feature: async API using aiohttp
* Feature: allow specifying `pkg==ver` in CLI

v0.0.3
------

* Feature: `honesty ispep517` and `honesty native`
* Feature: type checking
* Fix: extraction optimization that streams `.tar`
* Fix: relative paths in simple-index work

v0.0.2
------

* Feature: `honesty check` can work on multiple versions

v0.0.1
------

* Initial release
