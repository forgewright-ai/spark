#!/usr/bin/env python3
"""Audit the locked SDK closure using the verified runtime's npm, in isolation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from spark import agent


def main():
    source = Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "agent"
    node, _ = agent.runtime()
    node = Path(node).resolve()
    npm = node.parent.parent / "lib/node_modules/npm/bin/npm-cli.js"
    with tempfile.TemporaryDirectory(prefix="spark-agent-audit-") as scratch:
        home = Path(scratch)
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(source / name, home / name)
        # No ambient registry, authentication, proxy, Node flags or npmrc.
        env = {"PATH": str(node.parent) + os.pathsep + os.defpath,
               "HOME": scratch, "NPM_CONFIG_USERCONFIG": str(home / "user.npmrc"),
               "NPM_CONFIG_GLOBALCONFIG": str(home / "global.npmrc")}
        for name in ("user.npmrc", "global.npmrc"):
            (home / name).touch()
        result = subprocess.run(
            [str(node), str(npm), "audit", "--package-lock-only", "--ignore-scripts",
             "--registry=https://registry.npmjs.org", "--json"],
            cwd=scratch, env=env, capture_output=True, text=True, timeout=120)
        report = json.loads(result.stdout)
        counts = report.get("metadata", {}).get("vulnerabilities")
        if not counts or not isinstance(counts.get("total"), int):
            raise ValueError("the registry returned no advisory verdict")
        print("agent audit: " + json.dumps(counts, sort_keys=True))
        for name, entry in sorted(report.get("vulnerabilities", {}).items()):
            print("agent audit: %s (%s)" % (name, entry["severity"]))
        if result.returncode or counts["total"]:
            return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Do not echo registry bodies, environment or npm's local log paths.
        print("agent audit: no clean verdict (%s)" % type(exc).__name__)
        sys.exit(1)
