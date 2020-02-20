# Honesty

There's a long tail of people doing interesting/sketchy things to packages on
pypi.  Most aren't malicious, but this project gives you an easy way to check
for some of the obvious ways that packages might be tampered with.

# Usage

```
honesty list <package name>
honesty check <package name>[==version|==*] [--verbose]
honesty download <package name>[==version|==*] [--dest=some-path/]
honesty extract <package name>[==version|==*] [--dest=some-path/]
honesty license <package name>[==version|==*]

(provisional)
honesty ispep517 <package name>[==version|==*]
honesty native <package name>[==version|==*]
honesty age <package name>[==version|==*]
```

It will store a package cache, using the normal appdirs package to pick a
location (on Linux, this defaults to `~/.cache/honesty/pypi` but, you can
override with `XDG_CACHE_HOME` or `HONESTY_CACHE` environment variables).

If you have a local bandersnatch, specify `HONESTY_INDEX_URL` to your `/simple/`
url.  It also must support `/pypi/<package>/json` or pass `--nouse-json` to the
commands that support it.


# Exit Status of 'check'

These are bit flags to make sense when there are multiple problems.  If you pass
`*` for version, they are or'd together.

```
0   if only sdist or everything matches
1   if only bdist
2   (reserved for future "extraction error")
4   some .py from bdist not in sdist
8   some .py files present with same name but different hash in sdist (common
    when using versioneer or 2to3)
```


# License

Honesty is copyright [Tim Hatch](http://timhatch.com/), and licensed under
the MIT license.  I am providing code in this repository to you under an open
source license.  This is my personal repository; the license you receive to
my code is from me and not from my employer. See the `LICENSE` file for details.
