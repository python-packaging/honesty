"""
If it works right, tells you what git tag corresponds to a given release by
examinining contents.

On git, this is pretty efficient:

1. Exclude files which never existed in the repo.
2. For verifying tags, it's just set operations against all hashes in the
tag's commit.
3. For branches, imagine pointers at the first and last commit for that branch's
history, that ratchet inward based on revs each hash existed.

I haven't implemented Mercurial support yet, because the hashes are not just
contents but also history position.  This trick doesn't work then, and will need
to have a heuristic for possible filenames to hash ourselves.  See
https://www.mercurial-scm.org/wiki/Manifest and
https://www.mercurial-scm.org/wiki/Nodeid
"""
import functools
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .releases import Package

GITHUB_URL = re.compile(r"^https?://github.com/[^/]+/[^/]+")
GITLAB_URL = re.compile(r"^https?://gitlab.com/[^/]+/[^/]+")

ONELINE_RE = re.compile(r"^([0-9a-f]+) (?:\((.+?)\) )?(.*)", re.M)


def extract_vcs_url(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.strip()
    if not s or s == "UNKNOWN":
        return None

    m = GITHUB_URL.match(s)
    if m:
        # TODO repack to make https, transform ssh to https
        return m.group(0) + "/"
    else:
        # TODO right now these go in the same cache dir as a github project of
        # the same name.
        m = GITLAB_URL.match(s)
        if m:
            return m.group(0) + "/"

    # It's a string, but not a known hosting provider
    # print(f"Unknown host {s}")
    return None


def extract2(p: Package) -> Optional[str]:
    url = extract_vcs_url(p.home_page)
    if url:
        return url
    # .project_urls is only from the json api
    if p.project_urls:
        for i in p.project_urls.values():
            url = extract_vcs_url(i)
            if url:
                return url
    return None


class CloneAnalyzer:
    def __init__(self, url: str, verbose: bool = False) -> None:
        assert url.endswith("/")
        parts = url.split("/")
        self.key = "__".join(parts[-3:-1])
        # TODO appdirs/customizable
        self.dir = Path("~/.cache/honesty/git").expanduser() / self.key
        if not self.dir.exists():
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
            subprocess.check_call(
                ["git", "clone", url, self.dir],
                env=env,
            )
        else:
            subprocess.check_call(["git", "fetch", "origin", "--tags"], cwd=self.dir)

        self.verbose = verbose

    def _tree_log(self, ref: str) -> List[List[str]]:
        return [
            line.split()
            for line in subprocess.check_output(
                ["git", "log", "--no-renames", "--format=%h %T", ref],
                cwd=self.dir,
                encoding="utf-8",
            ).splitlines()
            if line.strip()
        ]

    @functools.lru_cache(maxsize=4096)
    def _ls_tree(self, tree: str) -> List[str]:
        return subprocess.check_output(
            ["git", "ls-tree", "-r", tree], encoding="utf-8", cwd=self.dir
        ).splitlines()

    def _hash_object_path(self, path: str) -> str:
        return subprocess.check_output(
            ["git", "hash-object", path], encoding="utf-8"
        ).strip()

    # def _tag_in_branch(self, branch: str, commits: Iterable[str]) -> List[str]:
    #     tags = []
    #     for a, b, c in self._log(branch):
    #         if a in commits:
    #             assert b is not None
    #             for dec in b.split(", "):
    #                 if dec.startswith("tag: "):
    #                     tags.append(dec[5:])
    #     return tags

    # def _log(
    #     self, ref: str, filename: Optional[str] = None
    # ) -> List[Tuple[str, Optional[str], str]]:
    #     # if filename is None and ref in self._log_cache:
    #     #     return self._log_cache[ref]

    #     args = ["git", "log", "--no-renames", "--oneline", "--decorate", ref]
    #     if filename:
    #         args.extend(["--", filename])

    #     data = subprocess.check_output(args, cwd=self.dir, encoding="utf-8")
    #     # print(data)
    #     rv = ONELINE_RE.findall(data)
    #     # if filename is None:
    #     #    self._log_cache[ref] = rv
    #     return rv

    def _branch_names(self) -> List[str]:
        names = []
        for line in subprocess.check_output(
            ["git", "branch", "-r"], cwd=self.dir, encoding="utf-8"
        ).splitlines():
            parts = line.strip().split()
            if len(parts) == 3 and parts[1] == "->":
                # HEAD
                continue
            elif len(parts) == 1:
                names.append(parts[0])
            else:
                raise ValueError(f"Unknown branch format {line!r}")
        return names

    def _tag_names(self) -> List[str]:
        return subprocess.check_output(
            ["git", "tag"], cwd=self.dir, encoding="utf-8"
        ).splitlines()

    def _cat(self, filename: str, rev: str) -> str:
        return subprocess.check_output(
            ["git", "show", f"{rev}:{filename}"], cwd=self.dir, encoding="utf-8"
        )

    @functools.lru_cache(maxsize=None)
    def _exists(self, hash: str) -> bool:
        try:
            subprocess.check_call(["git", "cat-file", "-e", hash], cwd=self.dir)
            return True
        except subprocess.CalledProcessError:
            return False

    def _try_tags(
        self, known: Dict[str, str], likely_tags: Iterable[str]
    ) -> List[Tuple[float, int, str]]:
        scores = []
        for tag in likely_tags:
            if self.verbose:
                print(f"Try tag {tag}")
            leftover = self._calc_leftover(tag, known)
            # print(f"{tag} is close, missing {', '.join(known[x] for x in leftover)}")
            scores.append((1 - (len(leftover) / float(len(known))), 0, f"tags/{tag}"))
        return scores

    def _try_branches(self, known: Dict[str, str]) -> List[Tuple[float, int, str]]:
        rev_on_branch: Dict[str, Set[str]] = {}
        checked = set()
        scores = []

        checked_results = set()

        for branch in self._branch_names():
            if self.verbose:
                print(f"Try branch {branch}")
            # TODO: Index
            branch_revs = subprocess.check_output(
                ["git", "log", "--no-renames", "--pretty=%h", branch],
                cwd=self.dir,
                encoding="utf-8",
            ).split()

            a, b = 0, len(branch_revs)
            # print(branch)
            if branch_revs[0] in checked:
                # print("done")
                continue

            checked.update(branch_revs)
            bad_branch = False

            for h, fn in known.items():
                # print(f"top {a} {b}")
                changed_revs = subprocess.check_output(
                    [
                        "git",
                        "log",
                        "--no-renames",
                        "--pretty=%h",
                        "--find-object",
                        h,
                        branch,
                    ],
                    cwd=self.dir,
                    encoding="utf-8",
                ).split()
                # Because multiple files can have the same contents (thus
                # hash), check whether the newest listed still contains such
                # an object.  The oldest listed will always be a creation.
                # For simplicity, we want the range that encloses the
                # (potentially disjoint) existence of such a file.

                # TODO: Structured output of _ls_tree
                if len(changed_revs) == 0:
                    # It's not on this branch (but exists somewhere else);
                    # this can probably become 'break' after testing.
                    # print("  bad")
                    bad_branch = True
                    break
                elif len(changed_revs) == 1 or h in self._ls_tree(changed_revs[0]):
                    # It still has this state.
                    bh = branch_revs.index(changed_revs[-1])
                    if bh < b:
                        b = bh
                    # print(f"  1: {a} {b} ({bh}) for {fn}")
                    # print(changed_revs)
                else:
                    # len(changed_revs) > 1, and it is deleted in changed_revs[0]

                    # It only had this state for a period of time, and does
                    # not any longer.
                    ah = branch_revs.index(changed_revs[0])
                    if ah > a:
                        a = ah
                    bh = branch_revs.index(changed_revs[-1])
                    if bh < b:
                        b = bh
                    # print(f"  2: {a} {b} ({ah} {bh}) for {fn}")
                    # print(changed_revs)

                if a >= b:
                    bad_branch = True

                if a <= b:
                    break

            if bad_branch:
                continue

            if b >= a:
                # If we already saw this solution, don't report it again.
                key = (branch_revs[a], branch_revs[b])
                if key in checked_results:
                    continue
                checked_results.add(key)

                for rev in branch_revs[a : b + 1]:
                    if rev in rev_on_branch:
                        rev_on_branch[rev].add(branch)
                        continue
                    rev_on_branch[rev] = set((branch,))

                    leftover = self._calc_leftover(rev, known)
                    # if leftover:
                    #    print(f"{rev} is close, missing {', '.join(known[x] for x in leftover) or None}")
                    scores.append((1 - (len(leftover) / float(len(known))), 1, rev))

        return scores

    def _calc_leftover(self, rev: str, known: Dict[str, str]) -> List[str]:
        matching_hashes = set()
        # TODO this could probably be optimized by looking at log
        # --stat; many fewer forks.
        for line in self._ls_tree(rev):
            parts = line.split(" ", 2)
            if parts[1] == "blob":
                blob_hash, filename = parts[2].split("\t", 1)
                if blob_hash in known:
                    matching_hashes.add(blob_hash)
        leftover = [k for k in known if k not in matching_hashes]
        return leftover

    def find_best_match(
        self,
        archive_root: str,
        names: List[Tuple[str, str]],
        version: str,
        try_order: List[str],
    ) -> List[Tuple[float, int, str]]:
        known: Dict[str, str] = {}

        # N.b. names is a list-of-tuple because of strip_top_level
        for a, b in names:
            if "egg-info" in a:
                continue
            hash = self._hash_object_path(os.path.join(archive_root, a))
            if hash in (
                "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",  # empty
                "8b137891791fe96927ad78e64b0aad7bded08bdc",  # single newline
            ):
                continue
            if self._exists(hash):
                known[hash] = b
            else:
                # print(f"{b} does not exist in this repo with {hash}")
                pass

        if not known:
            # nothing passed in exists at all in this repo :/
            return []

        scores: List[Tuple[float, int, str]] = []
        for t in try_order:
            if t == "likely_tags":
                likely_tags = [t for t in self._tag_names() if t.endswith(str(version))]
                scores.extend(self._try_tags(known, likely_tags))
            elif t == "tags":
                scores.extend(self._try_tags(known, self._tag_names()))
            elif t == "branches":
                scores.extend(self._try_branches(known))
            else:
                raise Exception(f"Unknown try_order {t!r}")

            scores.sort(reverse=True)
            # Stop on the first perfect match
            if scores and scores[0][0] == 1.0:
                break

        prev = None
        last = 0
        for i in range(len(scores)):
            if prev is None:
                prev = scores[i][:2]
                last = 0
            if scores[i][:2] != prev:
                break
            last = i
            if i > 100:
                break

        return scores[: last + 1]

    def describe(self, rev: str) -> str:
        return subprocess.check_output(
            ["git", "describe", "--tags", rev], cwd=self.dir, encoding="utf-8"
        )
