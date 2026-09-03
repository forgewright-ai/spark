# spark.verify -- sha256 verification of downloaded model files, cached so
# `spark check` can afford to run it on every pass. Nothing here deletes a
# file: a mismatch is reported, never removed (spark model rm does that).

import hashlib
import json
import os
import time

from . import STATE_DIR, config, state_dir

VERIFY_JSON = os.path.join(STATE_DIR, "verify.json")
CHUNK = 2**20        # 1 MiB
MAX_AGE = 86400       # a cached hash is trusted for a day


def _hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _load_cache():
    try:
        with open(VERIFY_JSON, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    state_dir()
    fd = os.open(VERIFY_JSON, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def verify_all(cfg, force=False):
    """[{name, file, path, bytes, status: ok|bad, cached, at}] -- one entry
    per config.model_tables() row whose file exists under cfg.models_dir,
    catalog order. sha256 in 1 MiB chunks; the result is cached in
    ~/.local/state/spark/verify.json, keyed by file name, as {sha, mtime,
    size, at}. force=False (the check row) re-hashes a file only when its
    mtime or size differs from the cached entry, or the entry is older
    than a day; force=True (spark model verify) always re-hashes. A file
    not on disk is skipped, never reported. Never deletes anything."""
    cache = _load_cache()
    now = time.time()
    changed = False
    out = []
    for row in config.model_tables():
        name, fname, _url, _bytes, sha = row[0], row[1], row[2], row[3], row[4]
        path = os.path.join(cfg.models_dir, fname)
        if not os.path.isfile(path):
            continue
        st = os.stat(path)
        entry = cache.get(fname)
        stale = (force or not entry or entry.get("mtime") != st.st_mtime
                 or entry.get("size") != st.st_size or now - entry.get("at", 0) > MAX_AGE)
        if stale:
            entry = {"sha": _hash_file(path), "mtime": st.st_mtime, "size": st.st_size, "at": now}
            cache[fname] = entry
            changed = True
            cached = False
        else:
            cached = True
        out.append({"name": name, "file": fname, "path": path, "bytes": st.st_size,
                    "status": "ok" if entry["sha"] == sha else "bad", "cached": cached, "at": entry["at"]})
    if changed:
        _save_cache(cache)
    return out
