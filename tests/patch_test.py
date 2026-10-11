#!/usr/bin/env python3
"""spark tests/patch_test.py -- the fence of the patch lane.

main holds a patch release when docs/CHANGELOG.md's top heading has three
parts, `## vX.Y.Z` (CLAUDE.md, Releasing; AGENTS.md, The patch lane).
Between the tag it patches (`vX.Y` for Z = 1, else `vX.Y.Z-1`) and this
tree, only a patch's shape may differ:

  - no protected path changes: the workflows, the hooks, the release keys,
    get, the landing and tagging scripts, this file, the model table, the
    distro tables, the completion files (PROTECTED)
  - `spark help` is byte for byte the same: a help row is prompt text
  - the check row count is the same: a row is a promise, not a fix
  - the diff outside tests/ and the CHANGELOG is at most PATCH_MAX_LINES
  - every bullet of the section is `- S<n>: what was wrong ... (#N)`

Under a two-part heading (a major) it prints one `na` line and exits 0.
The gate runs it, fast and full. `--selftest` proves it on a scratch
repository built from this tree. `--protected` prints the protected
paths, one a line: tests/tag.sh asks for them and refuses a patch tag
on its own, whatever CI said. Exit 0 ok or na, 1 a finding (one line
each), 2 it could not judge.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROTECTED = (".github/", ".githooks/", "allowed-signers", "get", "tests/land.sh", "tests/tag.sh",
             "tests/gate.sh", "tests/patch_test.py", "models.env", "distro/",
             "home/.config/spark/completion.bash", "home/.config/spark/completion.zsh")
FREE = ("tests/", "docs/CHANGELOG.md")       # not counted against the size cap
PATCH_MAX_LINES = 400
HEADING = re.compile(r"^## v(\d+)\.(\d+)(?:\.(\d+))?$", re.M)
BULLET = re.compile(r"^- S[1-4]: \S.* \(#\d+\)$")


def git(root, *args):
    p = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), p.stderr.strip()))
    return p.stdout


def top(changelog):
    """(major, minor, patch or None, the heading line) of the top section."""
    m = HEADING.search(changelog)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), (int(m.group(3)) if m.group(3) else None), m.group(0)


def section(changelog, heading):
    """The lines under `heading`, up to the next `## `."""
    out, on = [], False
    for ln in changelog.split("\n"):
        if ln == heading:
            on = True
            continue
        if on and ln.startswith("## "):
            break
        if on:
            out.append(ln)
    return out


def bullets(lines):
    """Each bullet as one line: a `- ` line and its indented continuation
    lines, joined by single spaces."""
    out, cur = [], None
    for ln in lines:
        if ln.startswith("- "):
            if cur is not None:
                out.append(cur)
            cur = ln.rstrip()
        elif cur is not None and ln.startswith("  ") and ln.strip():
            cur += " " + ln.strip()
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    return out


def base_tag(major, minor, patch):
    return "v%d.%d" % (major, minor) if patch == 1 else "v%d.%d.%d" % (major, minor, patch - 1)


def protected(path):
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in PROTECTED)


def free(path):
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in FREE)


def row_count(text):
    return sum(1 for ln in text.split("\n") if ln.startswith("@row"))


def scratch_env(home):
    """An environment whose spark state lives under `home`: the real
    state (the version cache) stays untouched."""
    env = dict(os.environ)
    env["HOME"] = home
    for k in ("CONFIG", "DATA", "STATE", "CACHE"):
        env["XDG_%s_HOME" % k] = os.path.join(home, "." + k.lower())
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    env.pop("GIT_INDEX_FILE", None)
    return env


VERSION_LINE = re.compile(r"^version \S+$", re.M)


def help_at(tree, env):
    """`spark help` at `tree`, its `version X` line normalised: the tag's
    tree is an archive without git, so its version reads `dev`."""
    p = subprocess.run([sys.executable, os.path.join(tree, "bin", "spark"), "help"],
                       capture_output=True, text=True, env=env, timeout=120)
    return p.returncode, VERSION_LINE.sub("version VERSION", p.stdout, count=1)


def judge(root):
    """The findings for the working tree at `root`: [] when it is a patch
    in shape, or when the top heading is a major. Raises on a tree it
    cannot judge."""
    with open(os.path.join(root, "docs", "CHANGELOG.md"), encoding="utf-8") as f:
        changelog = f.read()
    t = top(changelog)
    if t is None:
        raise RuntimeError("docs/CHANGELOG.md has no '## vX.Y' heading")
    major, minor, patch, heading = t
    if patch is None:
        return None
    base = base_tag(major, minor, patch)
    if subprocess.run(["git", "-C", root, "rev-parse", "-q", "--verify", base + "^{commit}"],
                      capture_output=True).returncode != 0:
        subprocess.run(["git", "-C", root, "fetch", "-q", "--tags", "origin"], capture_output=True)
    if subprocess.run(["git", "-C", root, "rev-parse", "-q", "--verify", base + "^{commit}"],
                      capture_output=True).returncode != 0:
        return ["%s patches %s, and no such tag exists" % (heading, base)]
    findings = []
    # the paths a patch never touches
    changed = [ln for ln in git(root, "diff", "--name-only", base, "--").split("\n") if ln]
    for path in changed:
        if protected(path):
            findings.append("%s: a patch never changes %s" % (heading, path))
    # the size, outside the tests and the CHANGELOG
    total = 0
    for ln in git(root, "diff", "--numstat", base, "--").split("\n"):
        parts = ln.split("\t")
        if len(parts) != 3 or free(parts[2]):
            continue
        for n in parts[:2]:
            if n.isdigit():
                total += int(n)
    if total > PATCH_MAX_LINES:
        findings.append("%s: %d lines changed outside tests/ and the CHANGELOG, a patch stays under %d"
                        % (heading, total, PATCH_MAX_LINES))
    # the help and the row count, this tree against the tag's
    tmp = tempfile.mkdtemp(prefix="patch_test.")
    try:
        before = os.path.join(tmp, "before")
        os.makedirs(before)
        archive = subprocess.run(["git", "-C", root, "archive", base], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", before], input=archive.stdout, check=True)
        env = scratch_env(os.path.join(tmp, "home"))
        rc0, help0 = help_at(before, env)
        rc1, help1 = help_at(root, env)
        if rc0 != 0 or rc1 != 0:
            findings.append("%s: `spark help` failed (exit %d at %s, %d here)" % (heading, rc0, base, rc1))
        elif help0 != help1:
            findings.append("%s: `spark help` differs from %s's: a help row is prompt text, not a patch" % (heading, base))
        with open(os.path.join(before, "lib", "spark", "check.py"), encoding="utf-8") as f:
            rows0 = row_count(f.read())
        with open(os.path.join(root, "lib", "spark", "check.py"), encoding="utf-8") as f:
            rows1 = row_count(f.read())
        if rows0 != rows1:
            findings.append("%s: %d check rows, %s has %d: a row is a promise, not a patch" % (heading, rows1, base, rows0))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # the bullets name a severity and an issue
    bs = bullets(section(changelog, heading))
    if not bs:
        findings.append("%s: the section has no bullet" % heading)
    for b in bs:
        if not BULLET.match(b):
            findings.append("%s: a bullet is not '- S<n>: ... (#N)': %s" % (heading, b[:60]))
    return findings


def selftest():
    """A scratch repository from this tree: a tag v9.9, then a `## v9.9.1`
    section with one good bullet and one harmless change passes; a change
    under .github/, a help row changed, a bullet without a severity, a
    diff over the cap and a missing base tag are each one finding."""
    fails = []

    def ok(cond, what):
        print("  %s %s" % ("ok  " if cond else "FAIL", what))
        if not cond:
            fails.append(what)

    ok(bullets(["- S2: one line (#1)", "", "- S3: two", "  lines (#2)", "prose", "- S4: three (#3)"])
       == ["- S2: one line (#1)", "- S3: two lines (#2)", "- S4: three (#3)"], "bullets: continuation lines join")
    ok(base_tag(1, 88, 1) == "v1.88" and base_tag(1, 88, 3) == "v1.88.2", "base_tag: the release, then the patch before")
    ok(protected(".github/workflows/ci.yml") and protected("distro/void.env") and not protected("lib/spark/cli.py"),
       "protected: a directory covers its files")
    T = tempfile.mkdtemp(prefix="patch_selftest.")
    try:
        clone = os.path.join(T, "clone")
        os.makedirs(clone)
        archive = subprocess.run(["git", "-C", ROOT, "archive", "HEAD"], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", clone], input=archive.stdout, check=True)
        env = scratch_env(os.path.join(T, "home"))
        env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                    "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1"})

        def g(*args):
            subprocess.run(["git", "-C", clone] + list(args), check=True, capture_output=True, env=env)

        # the scratch CHANGELOG is its own: the tree's top heading may be a
        # patch's, and this test must not read it
        log = os.path.join(clone, "docs", "CHANGELOG.md")
        base_log = "# Changelog\n\n## v9.9\n\n- the release.\n"
        with open(log, "w", encoding="utf-8") as f:
            f.write(base_log)
        g("init", "-q", "-b", "main")
        g("add", "-A")
        g("commit", "-q", "-m", "v9.9")
        g("tag", "-a", "-m", "v9.9", "v9.9")

        def write_log(heading, bullet):
            with open(log, "w", encoding="utf-8") as f:
                f.write("# Changelog\n\n%s\n\n%s\n\n" % (heading, bullet) + base_log.split("\n", 2)[2])

        ok(judge(clone) is None, "a two-part top heading is a major: na")
        write_log("## v9.9.1", "- S3: the version line read a patch tag as\n  nothing; it reads it now (#7)")
        ver = os.path.join(clone, "lib", "spark", "version.py")
        with open(ver, "a", encoding="utf-8") as f:
            f.write("\n# the fix\n")
        g("add", "-A")
        g("commit", "-q", "-m", "v9.9.1")
        found = judge(clone)
        ok(found == [], "a lib change with a well-formed bullet passes: %s" % found)
        ci = os.path.join(clone, ".github", "workflows", "ci.yml")
        with open(ci, "a", encoding="utf-8") as f:
            f.write("# touched\n")
        found = judge(clone)
        ok(any("never changes .github/workflows/ci.yml" in x for x in found), "a workflow change is a finding: %s" % found)
        g("checkout", "--", ".github")
        spark_bin = os.path.join(clone, "bin", "spark")
        with open(spark_bin, encoding="utf-8") as f:
            src = f.read()
        ok("is spark ok: every check" in src, "the selftest finds the help row it changes")
        with open(spark_bin, "w", encoding="utf-8") as f:
            f.write(src.replace("is spark ok: every check", "is spark ok: each check"))
        found = judge(clone)
        ok(any("`spark help` differs" in x for x in found), "a help row changed is a finding: %s" % found)
        g("checkout", "--", "bin")
        write_log("## v9.9.1", "- the version line read a patch tag as nothing (#7)")
        found = judge(clone)
        ok(any("not '- S<n>: ... (#N)'" in x for x in found), "a bullet without a severity is a finding: %s" % found)
        write_log("## v9.9.1", "- S3: the version line read a patch tag as\n  nothing; it reads it now (#7)")
        big = os.path.join(clone, "lib", "spark", "_big.py")
        with open(big, "w", encoding="utf-8") as f:
            f.write("".join("# line %d\n" % i for i in range(PATCH_MAX_LINES + 1)))
        g("add", "-A")
        found = judge(clone)
        ok(any("a patch stays under %d" % PATCH_MAX_LINES in x for x in found), "a diff over the cap is a finding: %s" % found)
        g("rm", "-q", "-f", "--cached", "lib/spark/_big.py")
        os.remove(big)
        write_log("## v9.9.3", "- S3: a fix (#8)")
        found = judge(clone)
        ok(found == ["## v9.9.3 patches v9.9.2, and no such tag exists"], "a missing base tag is the one finding: %s" % found)
    finally:
        shutil.rmtree(T, ignore_errors=True)
    if fails:
        print("patch_test --selftest: FAILED")
        return 1
    print("patch_test --selftest: all ok")
    return 0


def main(argv):
    if argv[1:] == ["--selftest"]:
        return selftest()
    if argv[1:] == ["--protected"]:
        print("\n".join(PROTECTED))
        return 0
    if argv[1:]:
        print("usage: python3 tests/patch_test.py [--selftest | --protected]", file=sys.stderr)
        return 2
    try:
        found = judge(ROOT)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
        print("patch_test: could not judge: %s" % e)
        return 2
    if found is None:
        print("patch_test: na (the top heading is a major; the fence holds a patch, `## vX.Y.Z`)")
        return 0
    for x in found:
        print("patch_test: FAIL %s" % x)
    if found:
        return 1
    print("patch_test: ok (a patch in shape)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
