#!/usr/bin/env python3
"""Bounded, local CPU compatibility evidence; no downloads or quality score.

python3 tests/model_validation.py --engine-archive FILE --model-file FILE
python3 tests/model_validation.py --selftest

Only the repository's qwen3-5-2b row and native Linux CPU engine pin run.
Stdout is one JSON record, including failures. No prompts, answers, paths,
server logs, hostnames or credentials are recorded.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import secrets
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
from spark.wire import gbnf  # noqa: E402  spark holds a JSON reply with a grammar
MODEL = "QWEN3_5_2B"
SAMPLES = 3
CASES = (
    {"messages": [{"role": "user", "content": "Reply with one short word."}]},
    # The JSON case holds the reply as spark does, with a grammar: llama-server
    # binds a response_format only after the template's thought channel, and
    # spark never sends one (CLAUDE.md, the prompt line's contract).
    {"messages": [{"role": "user", "content": 'Reply with a JSON object containing a word.'}],
     "grammar": gbnf({"type": "object", "properties": {"word": {"type": "string"}},
                      "required": ["word"]})},
)
SETTINGS = {"model": "spark-validation", "temperature": 0, "seed": 1,
            "max_tokens": 64, "stream": False}


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def table(path):
    # Data only: never source a shell file or read a user's model table.
    return dict(line.strip().split("=", 1) for line in path.read_text().splitlines()
                if line and not line.startswith("#") and "=" in line)


def verify(path, expected):
    if not path.is_file() or digest(path) != expected:
        raise ValueError("artifact missing or digest mismatch")


def unpack(archive, dest):
    """Copy only archive files, materializing internal links as plain files."""
    total, names = 0, set()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] == "/" or ".." in parts:
                raise ValueError("unsafe archive path")
            if member.isdir():
                continue
            if not (member.isfile() or member.issym() or member.islnk()):
                raise ValueError("unsupported archive entry")
            if member.name in names:
                raise ValueError("duplicate archive entry")
            names.add(member.name)
            # extractfile resolves links within the archive, never on disk.
            source = tar.extractfile(member)
            if source is None:
                raise ValueError("missing archive file")
            target = dest.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("xb") as out:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 2 * 1024 ** 3:
                        raise ValueError("engine archive exceeds limit")
                    out.write(chunk)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    servers = list(dest.rglob("llama-server"))
    if len(servers) != 1:
        raise ValueError("one llama-server required")
    return servers[0]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(base, key, route, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(base + route, data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=60 if body else 2) as response:
        data = response.read(65537)
    if len(data) > 65536:
        raise ValueError("response exceeds limit")
    return json.loads(data)


def compatible(reply, structured):
    try:
        content = reply["choices"][0]["message"]["content"]
        return (isinstance(content, str) and bool(content.strip())
                and (not structured or isinstance(json.loads(content), dict)))
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def host():
    cpu = ""
    if Path("/proc/cpuinfo").is_file():
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    return {"system": platform.system(), "release": platform.release(),
            "machine": platform.machine(), "cpu": cpu or platform.machine(),
            "logical_cpus": os.cpu_count(), "python": platform.python_version(),
            "memory_bytes": os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"),
            "backend": "cpu", "gpu_layers": 0, "threads": 2}


def run(archive, model):
    report = {"schema": 1, "kind": "compatibility", "status": "blocked",
              "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "quality": {"status": "not_run", "held_out_samples": 0},
              "requested": len(CASES) * SAMPLES, "executed": 0, "passed": 0,
              "samples_per_case": SAMPLES, "results": [], "settings": SETTINGS,
              "prompt_sha256": [hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()
                                for c in CASES],
              "artifact_verified": {"engine": False, "model": False},
              "untested": ["held-out quality", "spark command integration",
                           "GPU backends", "other models", "other platforms"]}
    stage = "host"
    try:
        report["host"] = host()
        key = {"x86_64": "LLAMA_SHA_LINUX_X64",
               "aarch64": "LLAMA_SHA_LINUX_ARM64"}.get(platform.machine())
        if platform.system() != "Linux" or not key or os.geteuid() == 0:
            raise ValueError("requires a non-root supported Linux CPU host")
        pins, models = table(ROOT / "engine.env"), table(ROOT / "models.env")
        row = models["MODEL_" + MODEL].strip('"').split()
        report["engine"] = {"revision": pins["LLAMA_VERSION"], "sha256": pins[key],
                            "flavour": key}
        report["model"] = {"name": "qwen3-5-2b", "sha256": row[3], "bytes": int(row[2]),
                           "revision_kind": "content sha256"}
        report["source"] = {p: digest(ROOT / p) for p in
                            ("engine.env", "models.env", "tests/model_validation.py")}
        stage = "engine artifact"
        verify(archive, pins[key])
        report["artifact_verified"]["engine"] = True
        stage = "model artifact"
        if model.stat().st_size != int(row[2]):
            raise ValueError("model size mismatch")
        verify(model, row[3])
        report["artifact_verified"]["model"] = True
        with tempfile.TemporaryDirectory(prefix="spark-compat-") as tmp:
            home = Path(tmp)
            stage = "engine extraction"
            server = unpack(archive, home / "engine")
            report["engine"]["binary_sha256"] = digest(server)
            key_value = secrets.token_hex(32)
            key_file = home / "key"
            key_file.write_text(key_value)
            key_file.chmod(0o600)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            base = "http://127.0.0.1:%d" % port
            cmd = [str(server), "-m", str(model.resolve()), "--alias", SETTINGS["model"],
                   "--host", "127.0.0.1", "--port", str(port), "-ngl", "0", "-t", "2",
                   "-c", "2048", "--cache-ram", "0", "--reasoning", "off",
                   "--reasoning-budget", "0", "--api-key-file", str(key_file),
                   "--no-webui", "--no-slots"]
            env = {"HOME": tmp, "PATH": "/usr/bin:/bin", "LANG": "C",
                   "LD_LIBRARY_PATH": str(server.parent)}
            stage = "server startup"
            proc = subprocess.Popen(cmd, cwd=tmp, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
            try:
                deadline = time.monotonic() + 120
                while True:
                    if proc.poll() is not None:
                        raise ValueError("server exited")
                    try:
                        health = request(base, key_value, "/health")
                        if isinstance(health, dict) and health.get("status") == "ok":
                            break
                    except (OSError, ValueError):
                        pass
                    if time.monotonic() >= deadline:
                        raise ValueError("server readiness timeout")
                    time.sleep(0.2)
                report["status"] = "failed"
                stage = "compatibility requests"
                for index, case in enumerate(CASES):
                    for sample in range(SAMPLES):
                        report["executed"] += 1
                        reply = request(base, key_value, "/v1/chat/completions", dict(SETTINGS, **case))
                        good = compatible(reply, "grammar" in case)
                        report["passed"] += int(good)
                        report["results"].append({"case": index, "sample": sample, "passed": good})
                report["status"] = "passed" if report["passed"] == report["requested"] else "failed"
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=10)
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as exc:
        # Exceptions can contain local paths or response text. Record neither.
        report["status"] = "failed" if report["executed"] else "blocked"
        report["error"] = {"stage": stage, "type": type(exc).__name__}
    report["not_completed"] = report["requested"] - len(report["results"])
    return report


def selftest():
    """Canned replies and archives test the harness, never a live model."""
    from unittest.mock import Mock, patch
    with tempfile.TemporaryDirectory(prefix="spark-compat-fixture-") as tmp:
        root = Path(tmp)
        archive, model = root / "engine.tgz", root / "model.gguf"
        report = run(archive, model)
        assert report["status"] == "blocked" and report["executed"] == 0
        assert report["quality"]["held_out_samples"] == 0
        model.write_bytes(b"fixture")
        try:
            verify(model, "0" * 64)
        except ValueError:
            pass
        else:
            raise AssertionError("wrong digest accepted")
        for name in ("../outside", "/outside", "dir/../../outside"):
            with tarfile.open(archive, "w:gz") as tar:
                member = tarfile.TarInfo(name)
                member.size = 1
                tar.addfile(member, io.BytesIO(b"x"))
            try:
                unpack(archive, root / "out")
            except ValueError:
                pass
            else:
                raise AssertionError("archive path accepted")
        reply = lambda s: {"choices": [{"message": {"content": s}}]}
        assert compatible(reply("word"), False)
        assert compatible(reply('{"word":"fixture"}'), True)
        for bad in ({}, reply(""), reply("not json"), reply("[]")):
            assert not compatible(bad, True)
        assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com") is None
        # Loss of a supported host must never produce a compatibility pass.
        with patch.object(platform, "machine", return_value="unsupported"):
            assert run(archive, model)["status"] == "blocked"
        with tarfile.open(archive, "w:gz") as tar:
            member = tarfile.TarInfo("engine/llama-server")
            member.size, member.mode = 7, 0o755
            tar.addfile(member, io.BytesIO(b"fixture"))
        pins = {"LLAMA_VERSION": "fixture", "LLAMA_SHA_LINUX_X64": digest(archive)}
        models = {"MODEL_" + MODEL: '"fixture unused 7 %s 1"' % digest(model)}
        proc = Mock(pid=123)
        proc.poll.return_value = None
        # This arm explicitly substitutes pins, process and wire: harness only.
        with patch.object(platform, "system", return_value="Linux"), \
                patch.object(platform, "machine", return_value="x86_64"), \
                patch.object(os, "geteuid", return_value=1000), \
                patch(__name__ + ".table", side_effect=lambda p: pins if p.name == "engine.env" else models), \
                patch.object(subprocess, "Popen", return_value=proc), \
                patch.object(os, "killpg") as kill, \
                patch(__name__ + ".request") as wire:
            wire.side_effect = [{"status": "ok"}] + [reply('{"word":"fixture"}')] * 6
            report = run(archive, model)
            assert report["status"] == "passed" and report["passed"] == 6
            assert report["quality"]["status"] == "not_run"
            assert report["artifact_verified"] == {"engine": True, "model": True}
            kill.assert_called_with(proc.pid, signal.SIGKILL)
            wire.side_effect = [{"status": "ok"}, reply("word"), OSError("private fixture detail")]
            report = run(archive, model)
            assert report["status"] == "failed" and report["executed"] == 2
            assert report["passed"] == 1 and report["not_completed"] == 5
            assert "private fixture detail" not in json.dumps(report)
            wire.side_effect = [{"status": "ok"}] + [reply("word")] * 6
            report = run(archive, model)
            assert report["status"] == "failed" and report["passed"] == 3
            proc.wait.side_effect = subprocess.TimeoutExpired("fixture", 10)
            wire.side_effect = [{"status": "ok"}] + [reply('{"word":"fixture"}')] * 6
            assert run(archive, model)["status"] == "failed"
            proc.wait.side_effect = None
            proc.poll.return_value = 1
            report = run(archive, model)
            assert report["status"] == "blocked" and report["executed"] == 0
    print("model validation selftest: ok (fixtures only)")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-archive", type=Path)
    parser.add_argument("--model-file", type=Path)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.engine_archive is None or args.model_file is None:
        parser.error("--engine-archive and --model-file are required")
    report = run(args.engine_archive, args.model_file)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
