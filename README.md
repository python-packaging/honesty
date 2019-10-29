# Honesty

There's a long tail of people doing interesting/sketchy things to packages on
pypi.  Most aren't malicious, but this project gives you an easy way to check
for some of the obvious ways that packages might be tampered with.

# Usage

```
honesty check <package name>[==version]
```

It will store a package cache by default under `~/.cache/honesty/pypi` but you
can change that with `HONESTY_CACHE` env var.  If you have a local bandersnatch,
specify `HONESTY_MIRROR_BASE` to your `/simple/` url.
