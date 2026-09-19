# spark.sbom -- what the tree depends on, as one CycloneDX 1.5 JSON
# document (`spark ver --sbom`; the release carries it as sbom.cdx.json).
# Built from the tree's own data files, never from a network or a live
# machine: the llama.cpp engine per flavour from engine.env, every model
# row config.model_tables() holds (the repo's list and yours), the
# packages every distro/<id>.env names, the python floor, and the GitHub
# Actions the workflows pin by sha. The order is fixed, so two runs of
# the same tree differ only in the timestamp -- tests/smoke.py holds it
# to that, and tests/docs_test.py to the model set and the flavours.

import json
import os
import re
import time

from . import REPO, config, packages, version
from .engine import FLAVOURS

PYTHON_FLOOR = ">=3.9"        # stdlib >= 3.9: Apple's /usr/bin/python3 is the floor
LLAMA_REPO = "ggml-org/llama.cpp"
_USES = re.compile(r"^\s*-?\s*uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([0-9a-f]{40})\b", re.M)


def _prop(name, value):
    return {"name": name, "value": str(value)}


def _engine(repo):
    """One library component per pinned flavour: the release the tree
    pins, its tarball's sha256, the flavour as a property."""
    pins = config.parse_env(os.path.join(repo, "engine.env"))
    pin = pins.get("LLAMA_VERSION", "")
    out = []
    for name, key in sorted(FLAVOURS.values()):
        sha = pins.get(key, "")
        if not pin or not sha:
            continue            # not pinned yet: the engine step skips it too
        out.append({"type": "library", "name": "llama.cpp", "version": pin,
                    "purl": "pkg:github/%s@%s" % (LLAMA_REPO, pin),
                    "hashes": [{"alg": "SHA-256", "content": sha}],
                    "properties": [_prop("spark:flavour", name)]})
    return out


def _models(repo):
    """One data component per model row, in the table's order: the sha256
    the download is verified against (its first 12 as the version), the
    license as models.env states it, the download URL, the RAM it takes."""
    out = []
    for name, _file, url, _bytes, sha, ram_gb, _src, _tested, license_, _note, _ground in config.model_tables(repo):
        words = license_.split()
        lic = {"name": words[0]}
        if len(words) > 1:
            lic["url"] = words[1]
        out.append({"type": "data", "name": name, "version": sha[:12],
                    "hashes": [{"alg": "SHA-256", "content": sha}],
                    "licenses": [{"license": lic}],
                    "externalReferences": [{"type": "distribution", "url": url}],
                    "properties": [_prop("spark:ram_gb", "%g" % ram_gb)]})
    return out


def _distro(repo):
    """One library component per package a family installs, family by
    family (the file's name), in the group order the file lists them."""
    out = []
    ddir = os.path.join(repo, "distro")
    for fname in sorted(os.listdir(ddir)):
        if not fname.endswith(".env"):
            continue
        family = fname[:-4]
        table = config.parse_env(os.path.join(ddir, fname))
        for group in packages.GROUPS:
            for name in table.get(group, "").split():
                out.append({"type": "library", "name": name,
                            "properties": [_prop("spark:family", family)]})
    return out


def _actions(repo):
    """The GitHub Actions the workflows pin by sha, each once."""
    seen = set()
    wdir = os.path.join(repo, ".github", "workflows")
    try:
        names = sorted(os.listdir(wdir))
    except OSError:
        names = []
    for fname in names:
        if fname.endswith((".yml", ".yaml")):
            with open(os.path.join(wdir, fname), encoding="utf-8") as f:
                seen.update(_USES.findall(f.read()))
    return [{"type": "library", "name": name, "version": sha,
             "purl": "pkg:github/%s@%s" % (name, sha)}
            for name, sha in sorted(seen)]


def build(repo=REPO):
    """The document as a dict: bomFormat, specVersion, version, metadata
    (the UTC timestamp and spark itself as the component), components."""
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "component": {"type": "application", "name": "spark", "version": version.version()},
        },
        "components": (_engine(repo) + _models(repo) + _distro(repo)
                       + [{"type": "platform", "name": "python", "version": PYTHON_FLOOR}]
                       + _actions(repo)),
    }


def dumps(repo=REPO):
    """The document as text: the JSON, indented, and one newline."""
    return json.dumps(build(repo), indent=2) + "\n"
