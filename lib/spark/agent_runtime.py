"""Install Pi from the signed tree's Node and npm integrity pins.

No package manager, lifecycle scripts or ambient Node installation is used.
Every archive is verified before extraction. A fresh complete tree passes
the restricted SDK probe before one atomic symlink change activates it.
"""
import base64
import concurrent.futures
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import platform
import posixpath
import shutil
import subprocess
import tarfile
import tempfile

from . import say, wire
from . import agent, voice

USAGE = """spark do --agent -- Pi for tasks and chat

  spark do --agent on       download and enable the pinned local runtime
  spark do --agent off      disable it and remove its downloads
  spark do --agent status   show whether it is ready

  Home tasks, spark do and spark chat use it. Ordinary desktop controls
  and the prompt line work without it. No service runs in the background.
"""


def pins():
    with open(os.path.join(agent.ROOT, "agent", "node.json"), encoding="utf-8") as f:
        node = json.load(f)
    with open(os.path.join(agent.ROOT, "agent", "package-lock.json"), "rb") as f:
        lock_bytes = f.read()
    lock = json.loads(lock_bytes)
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(platform.machine().lower())
    flavor = platform.system().lower() + "-" + str(arch)
    part = node["platforms"].get(flavor)
    if not part or (platform.system() == "Linux" and platform.libc_ver()[0] != "glibc"):
        raise wire.BrainError("bad", "the agent needs macOS or glibc Linux on arm64 or x64")
    fingerprint = hashlib.sha256(lock_bytes + json.dumps(part, sort_keys=True).encode()).hexdigest()
    return part, lock, fingerprint


def status():
    target = agent.runtime_dir()
    if not os.path.lexists(target):
        return "off"
    try:
        _, _, expected = pins()
        with open(os.path.join(target, "verified"), encoding="ascii") as f:
            actual = f.read().strip()
        agent.runtime()
        return "ready" if actual == expected else "needs update"
    except (OSError, ValueError, wire.BrainError):
        return "needs update"


def _archive(url, digest, algorithm, cache, size=None):
    if not url.startswith("https://") or algorithm not in ("sha256", "sha512"):
        raise ValueError("invalid download pin")
    dest = os.path.join(cache, algorithm + "-" + digest.hex())

    def verified():
        try:
            if size is not None and os.path.getsize(dest) != size:
                return False
            h = hashlib.new(algorithm)
            with open(dest, "rb") as f:
                for chunk in iter(lambda: f.read(1048576), b""):
                    h.update(chunk)
            return h.digest() == digest
        except OSError:
            return False

    if verified():
        return dest
    fd, downloading = tempfile.mkstemp(prefix="download-", dir=cache)
    os.close(fd)
    try:
        download = subprocess.run(["curl", "-fsSL", "--proto", "=https", "--proto-redir", "=https",
                                   "--connect-timeout", "20", "--max-time", "300", "--retry", "2",
                                   "--max-filesize", str(size or 100000000), "-o", downloading, url],
                                  timeout=930)
        if download.returncode:
            raise ValueError("a pinned download failed")
        if os.path.getsize(downloading) > 100000000:
            raise ValueError("download exceeds its limit")
        os.replace(downloading, dest)
        if not verified():
            os.unlink(dest)
            raise ValueError("a download does not match its integrity pin")
        return dest
    finally:
        if os.path.exists(downloading):
            os.unlink(downloading)


def _unpack(archive, destination):
    with tarfile.open(archive) as tf:
        rows, size = [], 0
        for member in tf:
            size += member.size
            if len(rows) >= 30000 or size > 500000000:
                raise ValueError("archive exceeds its unpacking limit")
            rows.append(member)
        seen, duplicates = {}, set()
        for i, member in enumerate(rows):
            if member.name.startswith("/") or ".." in member.name.split("/"):
                raise ValueError("archive path leaves its root")
            key = posixpath.normpath(member.name)
            if key in seen:
                earlier = seen[key]
                # Two pinned npm archives repeat a file under ./ and without
                # it. Only byte-identical regular files may collapse; paths,
                # links, permissions and conflicting contents never override.
                if (not member.isfile() or not earlier.isfile() or member.mode != earlier.mode
                        or member.size != earlier.size):
                    raise ValueError("conflicting duplicate archive member")
                def digest(item):
                    h = hashlib.sha256()
                    with tf.extractfile(item) as f:
                        for chunk in iter(lambda: f.read(1048576), b""):
                            h.update(chunk)
                    return h.digest()
                if digest(member) != digest(earlier):
                    raise ValueError("conflicting duplicate archive contents")
                duplicates.add(i)
            else:
                seen[key] = member
        if duplicates:
            with tempfile.NamedTemporaryFile(suffix=".tar") as normalized:
                with tarfile.open(fileobj=normalized, mode="w") as out:
                    for i, member in enumerate(rows):
                        if i not in duplicates:
                            out.addfile(member, tf.extractfile(member) if member.isfile() else None)
                normalized.flush()
                voice.unpack(normalized.name, destination)
        else:
            voice.unpack(archive, destination)


def probe(node, sdk):
    with tempfile.TemporaryDirectory(prefix="spark-agent-probe-") as home:
        result = subprocess.run(agent.command(node, sdk, home) + ["--probe"], cwd=home,
                                env=agent.environment(home), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    if result.returncode or result.stdout != b"spark agent ready\n":
        raise ValueError("the restricted agent did not start on this machine")


@contextmanager
def locked(base):
    os.makedirs(base, mode=0o700, exist_ok=True)
    with open(os.path.join(base, ".install.lock"), "a", encoding="ascii") as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise ValueError("another agent setup is running") from e
        yield


def install():
    part, lock, fingerprint = pins()
    target = agent.runtime_dir()
    base = os.path.dirname(target)
    with locked(base):
        if status() == "ready":
            return
        cache = os.path.join(base, "downloads")
        os.makedirs(cache, mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=base) as fresh:
            node_archive = _archive(part["url"], bytes.fromhex(part["sha256"]), "sha256", cache, part["size"])
            _unpack(node_archive, os.path.join(fresh, "node"))
            sdk = os.path.join(fresh, "sdk")
            os.mkdir(sdk, 0o700)
            packages = []
            for path, package in lock["packages"].items():
                if not path:
                    continue
                if not path.startswith("node_modules/") or any(p in ("", ".", "..") for p in path.split("/")):
                    raise ValueError("invalid locked package path")
                url = package["resolved"]
                if not url.startswith("https://registry.npmjs.org/"):
                    raise ValueError("invalid package registry")
                kind, digest = package["integrity"].split("-", 1)
                if kind != "sha512":
                    raise ValueError("invalid package integrity")
                packages.append((path, url, base64.b64decode(digest, validate=True)))

            def download(row):
                path, url, digest = row
                return path, _archive(url, digest, "sha512", cache)

            # Downloads are independent; extraction is parent before child.
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                downloaded = list(pool.map(download, packages))
            for path, archive in sorted(downloaded, key=lambda row: (row[0].count("/"), row[0])):
                destination = os.path.join(sdk, path)
                os.makedirs(os.path.dirname(destination), mode=0o700, exist_ok=True)
                if os.path.realpath(destination) != os.path.join(os.path.realpath(sdk), path):
                    raise ValueError("a package path crosses an archive link")
                _unpack(archive, destination)
            for name in ("package.json", "package-lock.json"):
                shutil.copyfile(os.path.join(agent.ROOT, "agent", name), os.path.join(sdk, name))
            probe(os.path.join(fresh, "node", "bin", "node"), sdk)
            with open(os.path.join(fresh, "verified"), "w", encoding="ascii") as f:
                f.write(fingerprint + "\n")
            releases = os.path.join(base, "releases")
            os.makedirs(releases, mode=0o700, exist_ok=True)
            release = tempfile.mkdtemp(prefix=fingerprint[:12] + "-", dir=releases)
            os.rmdir(release)
            os.rename(fresh, release)
            link = os.path.join(base, ".activate-" + os.path.basename(release))
            try:
                os.symlink(os.path.relpath(release, base), link)
                os.replace(link, target)
            finally:
                if os.path.islink(link):
                    os.unlink(link)
            # Keep the previous tree: an in-flight bounded child may still
            # import it. Off removes all trees after no new worker can start.


def remove():
    target = agent.runtime_dir()
    base = os.path.dirname(target)
    with locked(base):
        if os.path.islink(target):
            os.unlink(target)
        elif os.path.exists(target):
            raise ValueError("the agent path is not an installed runtime link")
        for name in ("releases", "downloads"):
            shutil.rmtree(os.path.join(base, name), ignore_errors=True)


def converge():
    """An enabled runtime follows pins, including a retry after failed setup."""
    if os.environ.get("SPARK_NO_APPLY") or status() in ("off", "ready"):
        return 0
    return main(["on"])


def main(args):
    if not args or args == ["status"]:
        say("* agent: " + status())
        return 0
    if args in (["-h"], ["--help"]):
        say(USAGE.rstrip())
        return 0
    if args not in (["on"], ["off"]):
        say("! agent: use spark do --agent on, off or status")
        return 2
    try:
        if args == ["on"]:
            say("* installing Pi and Node from the signed download pins")
            install()
        else:
            remove()
        say("* agent: " + status())
        return 0
    except (OSError, ValueError, tarfile.TarError, voice.VoiceError, wire.BrainError, subprocess.TimeoutExpired) as e:
        say("! agent: " + wire._plain(str(e)) + " -- run: spark do --agent on")
        return 2
