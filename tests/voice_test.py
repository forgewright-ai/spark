#!/usr/bin/env python3
"""The voice's core (lib/spark/voice.py) against stubs: no download, no
engine, no sound.

The runtime is a stub: small scripts named like sherpa-onnx's tools in
a throwaway voice dir (SPARK_VOICE_DIR). The speaking one writes a known
wav and keeps its argv; the listening one saves a segment and says so
the way the real one does; the ears print sherpa's JSON line. The player
and `defaults` are stubs on PATH. Covered: voice.env's pins; fetch()
refusing a size or sha256 mismatch and a tarball with `..`, an absolute
path or a link pointing out, and installing a good one (its top
directory stripped, its sha file last); speak() in both modes and both
languages; every family's chain, deterministic (its output hashed);
mint() per (temper, seed); the recipe file round trip, 0600; the SBOM
and uninstall naming the voice; play(),
stop(); listen() and its private directory; spoken_command(); lang_of();
screen_reader(); say_aloud() never raising; the `spark voice` verb under
SPARK_NO_APPLY; the check row's na, ok and warn; awaken's offer (keep,
again, none, and none under SPARK_NO_APPLY). Then the surfaces' half:
the SPARK_VOICE_STUB seam (what would be spoken, appended to a file; a
heard question from SPARK_VOICE_STUB_HEARD, no microphone), heard_line()
taking every control character out, what clear mode says for contract
4's lines and for a spark do step or block, plain() over Markdown, the
Reader's order, cut and hush, aloud_later() from a detached process, and
`spark voice listen [--buffer]` and `spark voice stop`. v1.71: the
splitter a streamed reply is spoken through (numbers, abbreviations,
fences, list items, the long-run cut, the first sentence at its
first pause or its sixth word, any chunking the same), the lead-in, and the Reader's two
stages timed against a slow engine: per clip (macOS) against a player
that records what it got and when, and as one stream (Linux) against a
stub that keeps every byte it was given at a sound card's pace -- one
process a burst, the lead-in once, silence between, closed when idle,
killed by a cut. v1.70's int8 mouth fetched again and removed; spark
update's voice step; the engine's fallback to the tool. On this Mac
only, never in CI, the engine against the real runtime when a voice is
here (SPARK_VOICE_REAL_DIR, else ~/.local/share/spark/voice): the
structs, one load, two sentences, the language per call, the timings.
"""
import array
import hashlib
import io
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPARK = os.path.join(REPO, "bin", "spark")
ROOT = tempfile.mkdtemp(prefix="spark-voice-test-")
HOME = os.path.join(ROOT, "home")
STUBS = os.path.join(ROOT, "stubs")
VDIR = os.path.join(ROOT, "voice")
LOG = os.path.join(ROOT, "log")
for d in (HOME, STUBS, LOG):
    os.makedirs(d)

# the real runtime, for the engine's own test (this Mac, never CI)
REAL_VOICE = os.environ.get("SPARK_VOICE_REAL_DIR") or os.path.join(os.path.expanduser("~"), ".local", "share",
                                                                     "spark", "voice")
IN_CI = bool(os.environ.get("CI"))
for k in [k for k in os.environ if k.startswith(("SPARK_", "XDG_", "SITE_"))]:
    del os.environ[k]
os.environ.update({"HOME": HOME, "XDG_CONFIG_HOME": HOME + "/.config", "XDG_STATE_HOME": HOME + "/.local/state",
                   "XDG_DATA_HOME": HOME + "/.local/share", "SPARK_VOICE_DIR": VDIR,
                   "SPARK_PROC_DIR": os.path.join(ROOT, "proc"), "SPARK_SYS_MODULE": os.path.join(ROOT, "module"),
                   "PATH": STUBS + os.pathsep + os.environ.get("PATH", ""), "STUB_LOG": LOG,
                   "SPARK_NO_REFRESH": "1", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
os.makedirs(os.environ["SPARK_PROC_DIR"])
os.makedirs(os.environ["SPARK_SYS_MODULE"])
sys.path.insert(0, os.path.join(REPO, "lib"))
from spark import IS_MAC, config, voice  # noqa: E402

FAILED = 0


def check(name, cond, detail=""):
    global FAILED
    if not cond:
        FAILED += 1
        print("FAIL %s\n  %s" % (name, str(detail)[:600]))
    else:
        print("ok   %s" % name)


def stub(name, body, where=STUBS):
    path = os.path.join(where, name)
    with open(path, "w") as f:
        f.write(body)
    os.chmod(path, 0o755)
    return path


def tone(path, seconds=0.25, rate=24000):
    """A fixed input: a rising tone, 16-bit mono."""
    n = int(seconds * rate)
    a = array.array("h", (int(12000 * math.sin(2 * math.pi * (220 + 400 * i / n) * i / rate)) for i in range(n)))
    if sys.byteorder == "big":
        a.byteswap()
    w = wave.open(path, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(a.tobytes())
    w.close()
    return path


TONE = tone(os.path.join(ROOT, "tone.wav"))
PY = sys.executable

# the stub runtime: the tools sherpa-onnx ships, by name
TTS = '''#!%s
import json, os, shutil, sys
out = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--output-filename=")][0]
with open(os.path.join(os.environ["STUB_LOG"], "tts.json"), "w") as f:
    json.dump({"argv": sys.argv[1:], "cwd": os.getcwd()}, f)
shutil.copyfile(%r, out)
''' % (PY, TONE)
VAD = '''#!%s
import os, shutil, sys, time
with open(os.path.join(os.environ["STUB_LOG"], "vad.json"), "w") as f:
    f.write(repr((sys.argv[1:], os.getcwd(), oct(os.umask(0o077)))))
if os.environ.get("STUB_SILENT"):
    sys.stderr.write("Started. Please speak\\n"); sys.stderr.flush(); time.sleep(30); sys.exit(0)
shutil.copyfile(%r, "seg-0-1.000s.wav")
sys.stderr.write("Started. Please speak\\nDuration: 1.000 seconds\\nSaved to seg-0-1.000s.wav\\n----------\\n")
sys.stderr.flush()
time.sleep(30)
''' % (PY, TONE)
ASR = '''#!%s
import json, os, stat, sys
wav = sys.argv[-1]
mode = oct(os.stat(wav).st_mode & 0o777)
with open(os.path.join(os.environ["STUB_LOG"], "asr.json"), "w") as f:
    json.dump({"argv": sys.argv[1:], "mode": mode}, f)
print(json.dumps({"lang": "pt", "emotion": "", "text": " Bom dia,  spark ", "tokens": []}))
''' % PY


def stub_engine(pins=None):
    """A voice dir that holds every part, each with the given pins' sha
    file (voice.env's by default), and the stub tools."""
    shutil.rmtree(VDIR, ignore_errors=True)
    os.makedirs(os.path.join(VDIR, "runtime", "bin"))
    os.makedirs(os.path.join(VDIR, "runtime", "lib"))
    for d in ("mouth", "ears", "vad"):
        os.makedirs(os.path.join(VDIR, d))
    with open(os.path.join(VDIR, "vad", "silero_vad.onnx"), "w") as f:
        f.write("stub\n")
    stub("sherpa-onnx-offline-tts", TTS, os.path.join(VDIR, "runtime", "bin"))
    stub("sherpa-onnx-offline", ASR, os.path.join(VDIR, "runtime", "bin"))
    for name in ("sherpa-onnx-vad-microphone", "sherpa-onnx-vad-alsa"):
        stub(name, VAD, os.path.join(VDIR, "runtime", "bin"))
    for part in voice.parts(pins):
        with open(os.path.join(VDIR, part["name"] + ".sha"), "w") as f:
            f.write(part["sha"] + "\n")


class Cfg:
    name = "fixture"

    def __init__(self, **kv):
        self.kv = kv

    def get(self, key, default=""):
        return self.kv.get(key, default)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ------------------------------------------------------------- 1. the pins
pins = voice.pins()
ps = voice.parts(pins)
check("voice.env: four parts, each a URL, a size and a sha256",
      [p["name"] for p in ps] == ["runtime", "mouth", "ears", "vad"]
      and all(p["url"].startswith("https://") and p["size"] > 0 and len(p["sha"]) == 64 for p in ps), ps)
check("voice.env: the three runtime flavours and every licence",
      all(k in pins for k in ("VOICE_RUNTIME_LINUX_X64", "VOICE_RUNTIME_LINUX_ARM64", "VOICE_RUNTIME_MACOS",
                              "VOICE_RUNTIME_LICENSE", "VOICE_MOUTH_LICENSE", "VOICE_EARS_LICENSE",
                              "VOICE_VAD_LICENSE")), sorted(pins))
from spark import sbom, uninstall  # noqa: E402
comps = sbom.build(REPO)["components"]
runtimes = sorted(c["hashes"][0]["content"] for c in comps if c["name"] == "sherpa-onnx")
models = sorted(c["hashes"][0]["content"] for c in comps if c["type"] == "machine-learning-model")
check("the SBOM lists voice.env's pins: a sherpa-onnx per flavour, the three models",
      runtimes == sorted(pins[k].split()[2] for k in ("VOICE_RUNTIME_LINUX_X64", "VOICE_RUNTIME_LINUX_ARM64",
                                                      "VOICE_RUNTIME_MACOS"))
      and models == sorted(pins[k].split()[2] for k in ("VOICE_MOUTH", "VOICE_EARS", "VOICE_VAD")), (runtimes, models))
check("uninstall: the kept voice goes with spark's config, the engine with the data dir",
      "voice" in uninstall.SPARK_CONFIG and voice.voice_dir() != os.path.join(uninstall.DATA_DIR, "voice")
      and os.path.join(uninstall.DATA_DIR, "voice").startswith(uninstall.DATA_DIR))
total = sum(p["size"] for p in ps) / 1e6
check("voice.env: about 600 MB in all on this machine (%d MB)" % total, 570 < total < 620)
mouth = [p for p in ps if p["name"] == "mouth"][0]
check("voice.env: the mouth is Kokoro's full-precision export (model.onnx), 350 MB",
      mouth["url"].endswith("/kokoro-multi-lang-v1_0.tar.bz2") and mouth["size"] == 349906910, mouth)
check("threads: 8 from 8 cores up, else the cores, at least 2",
      [voice.threads(n) for n in (16, 10, 8, 6, 4, 2, 1)] == [8, 8, 8, 6, 4, 2, 2]
      and voice.THREADS == voice.threads(os.cpu_count()))

# ------------------------------------------------------------ 2. fetch
SRC = os.path.join(ROOT, "src")
os.makedirs(SRC)


def tarball(name, members):
    """A .tar.bz2 of (name, kind, data-or-target) members."""
    path = os.path.join(SRC, name)
    with tarfile.open(path, "w:bz2") as tf:
        for mname, kind, data in members:
            ti = tarfile.TarInfo(mname)
            if kind == "dir":
                ti.type, ti.mode = tarfile.DIRTYPE, 0o755
                tf.addfile(ti)
            elif kind == "sym":
                ti.type, ti.linkname = tarfile.SYMTYPE, data
                tf.addfile(ti)
            else:
                ti.size, ti.mode = len(data), 0o755 if kind == "exe" else 0o644
                tf.addfile(ti, io.BytesIO(data))
    return path


def row(path, size=None, digest=None):
    return "https://voice.invalid/%s %d %s" % (os.path.basename(path), size or os.path.getsize(path),
                                              digest or sha(path))


GOOD_RT = tarball("rt.tar.bz2", [("rt-1/", "dir", None), ("rt-1/bin/", "dir", None),
                                 ("rt-1/bin/sherpa-onnx-offline-tts", "exe", b"#!/bin/sh\n"),
                                 ("rt-1/lib/libx.so.1", "file", b"lib"), ("rt-1/lib/libx.so", "sym", "libx.so.1")])
GOOD_MOUTH = tarball("mouth.tar.bz2", [("kokoro/model.onnx", "file", b"m"), ("kokoro/voices.bin", "file", b"v")])
OLD_MOUTH = tarball("old-mouth.tar.bz2", [("kokoro/model.int8.onnx", "file", b"8"), ("kokoro/voices.bin", "file", b"v")])
GOOD_EARS = tarball("ears.tar.bz2", [("whisper/base-tokens.txt", "file", b"t")])
VADF = os.path.join(SRC, "silero_vad.onnx")
with open(VADF, "wb") as f:
    f.write(b"vad")
fetched = []


def fake_download(url, dest):
    fetched.append(os.path.basename(url))
    shutil.copyfile(os.path.join(SRC, os.path.basename(url)), dest)
    return True


voice._download = fake_download


def fetch_pins(**over):
    p = {voice.runtime_key(): row(GOOD_RT), "VOICE_MOUTH": row(GOOD_MOUTH), "VOICE_EARS": row(GOOD_EARS),
         "VOICE_VAD": row(VADF)}
    p.update(over)
    return p


def leftovers():
    return sorted(n for n in os.listdir(VDIR) if n.startswith(".")) if os.path.isdir(VDIR) else []


shutil.rmtree(VDIR, ignore_errors=True)
try:
    voice.fetch(None, fetch_pins(VOICE_MOUTH=row(GOOD_MOUTH, digest="0" * 64)), out=lambda s: None)
    refused = ""
except voice.VoiceError as e:
    refused = str(e)
check("fetch: a sha256 mismatch is refused, nothing kept of it",
      "damaged" in refused and not os.path.exists(os.path.join(VDIR, "mouth"))
      and not os.path.exists(os.path.join(VDIR, "mouth.sha")) and not leftovers(), (refused, leftovers()))
check("fetch: the part before it landed whole (runtime, its sha file)",
      voice.installed(voice.parts(fetch_pins())[0]), os.listdir(VDIR))
try:
    voice.fetch(None, fetch_pins(VOICE_MOUTH=row(GOOD_MOUTH, size=5)), out=lambda s: None)
    refused = ""
except voice.VoiceError as e:
    refused = str(e)
check("fetch: a size mismatch is refused before the sha256", "the wrong size" in refused and not leftovers(), refused)

for label, members in (
        ("a `..` member", [("kokoro/model.int8.onnx", "file", b"m"), ("kokoro/../../evil", "file", b"x")]),
        ("an absolute path", [("/tmp/spark-voice-evil", "file", b"x")]),
        ("a link pointing out", [("kokoro/model.int8.onnx", "file", b"m"), ("kokoro/up", "sym", "../../..")]),
        ("an absolute link", [("kokoro/model.int8.onnx", "file", b"m"), ("kokoro/etc", "sym", "/etc")])):
    bad = tarball("evil.tar.bz2", members)
    try:
        voice.fetch(None, fetch_pins(VOICE_MOUTH=row(bad)), out=lambda s: None)
        refused = ""
    except voice.VoiceError as e:
        refused = str(e)
    check("fetch: a tarball with %s is refused whole, nothing unpacked" % label,
          refused and not os.path.exists(os.path.join(VDIR, "mouth")) and not leftovers()
          and not os.path.exists(os.path.join(ROOT, "evil")) and not os.path.exists("/tmp/spark-voice-evil"),
          (refused, leftovers()))


# unpack against crafted archives: links are created last and resolved
# on disk, a hard link is written from the archive's own member, a name
# twice or a path through a link is refused before a byte lands
def crafted(name, members):
    """A plain .tar of (name, kind, data-or-target) members: dir, file,
    sym, hard, fifo."""
    path = os.path.join(SRC, name)
    with tarfile.open(path, "w") as tf:
        for mname, kind, data in members:
            ti = tarfile.TarInfo(mname)
            if kind == "dir":
                ti.type, ti.mode = tarfile.DIRTYPE, 0o755
                tf.addfile(ti)
            elif kind in ("sym", "hard"):
                ti.type, ti.linkname = (tarfile.SYMTYPE if kind == "sym" else tarfile.LNKTYPE), data
                tf.addfile(ti)
            elif kind == "fifo":
                ti.type = tarfile.FIFOTYPE
                tf.addfile(ti)
            else:
                ti.size, ti.mode = len(data), 0o644
                tf.addfile(ti, io.BytesIO(data))
    return path


TARX = os.path.join(ROOT, "tarx")


def unpacked(tarpath, sub):
    """(refused, dest) for voice.unpack into TARX/a/b/<sub>: two levels
    under TARX/a, where victim.txt and secret.txt live."""
    shutil.rmtree(TARX, ignore_errors=True)
    os.makedirs(os.path.join(TARX, "a", "b"))
    with open(os.path.join(TARX, "a", "victim.txt"), "w") as f:
        f.write("SAFE\n")
    with open(os.path.join(TARX, "a", "secret.txt"), "w") as f:
        f.write("SECRET\n")
    dest = os.path.join(TARX, "a", "b", sub)
    try:
        voice.unpack(tarpath, dest)
        return "", dest
    except voice.VoiceError as e:
        return str(e), dest


def found(dest, text):
    for top, _dirs, files in os.walk(dest):
        for n in files:
            p = os.path.join(top, n)
            if not os.path.islink(p) and text in open(p, "rb").read():
                return p
    return ""


# the review's two: a link chain (s -> ., t -> s/s/../..) that resolves
# out of dest on disk though each looks inside; then a hard link through
# it that copied a file in, and a file member under a link's name that
# wrote one out
READ_TAR = crafted("read.tar", [("top/", "dir", None), ("top/s", "sym", "."), ("top/t", "sym", "s/s/../.."),
                                ("top/copied", "hard", "top/t/secret.txt"), ("top/README", "file", b"r")])
WRITE_TAR = crafted("write.tar", [("top/", "dir", None), ("top/s", "sym", "."), ("top/t", "sym", "s/s/../.."),
                                  ("top/f", "sym", "t/victim.txt"), ("top/f", "file", b"PWNED\n"),
                                  ("top/README", "file", b"r")])
refused, dest = unpacked(READ_TAR, "dest1")
check("unpack: a hard link through a link chain is refused; nothing from outside is copied in",
      refused and not found(dest, b"SECRET") and not os.path.exists(os.path.join(dest, "copied")), (refused, dest))
refused, dest = unpacked(WRITE_TAR, "dest2")
check("unpack: a name twice (a link, then a file over it) is refused; nothing outside is written",
      "twice" in refused and open(os.path.join(TARX, "a", "victim.txt")).read() == "SAFE\n", refused)
refused, dest = unpacked(crafted("chain.tar", [("top/s", "sym", "."), ("top/t", "sym", "s/s/../.."),
                                               ("top/README", "file", b"r")]), "dest3")
check("unpack: a link that looks inside but resolves out on disk is refused",
      "leads out" in refused, refused)
refused, dest = unpacked(crafted("late.tar", [("top/a", "sym", "b/.."), ("top/b", "sym", "."),
                                              ("top/README", "file", b"r")]), "dest4")
check("unpack: a link that escapes only once a later link lands is refused (every link checked again)",
      "leads out" in refused, refused)
refused, dest = unpacked(crafted("under.tar", [("top/d", "sym", "sub"), ("top/sub/", "dir", None),
                                               ("top/d/x", "file", b"x")]), "dest5")
check("unpack: a member under a link's name is refused", "lies under" in refused, refused)
refused, dest = unpacked(crafted("fifo.tar", [("top/README", "file", b"r"), ("top/pipe", "fifo", None)]), "dest6")
check("unpack: a fifo is refused", "neither a file nor a directory" in refused, refused)
refused, dest = unpacked(crafted("hard.tar", [("top/lib/libx.so.1", "file", b"LIB"),
                                              ("top/lib/libx.so", "hard", "top/lib/libx.so.1"),
                                              ("top/lib/liby.so", "sym", "libx.so.1")]), "dest7")
check("unpack: a hard link is written from the member it names; a link inside is kept",
      not refused and open(os.path.join(dest, "lib", "libx.so"), "rb").read() == b"LIB"
      and os.readlink(os.path.join(dest, "lib", "liby.so")) == "libx.so.1", refused)
refused, dest = unpacked(crafted("hardout.tar", [("top/README", "file", b"r"),
                                                 ("top/x", "hard", "top/../secret.txt")]), "dest8")
check("unpack: a hard link naming no file of the archive is refused", refused and not found(dest, b"SECRET"), refused)
shutil.rmtree(TARX, ignore_errors=True)

fetched[:] = []
said = []
got = voice.fetch(None, fetch_pins(), out=said.append)
check("fetch: the missing parts come, each said with its size; the one there is not fetched again",
      got == ["mouth", "ears", "vad"] and fetched == ["mouth.tar.bz2", "ears.tar.bz2", "silero_vad.onnx"]
      and said == ["downloading the voice (%d of 3, %d MB)" % (k, voice._mb(x["size"]))
                   for k, x in enumerate(voice.parts(fetch_pins())[1:], 1)], (got, fetched, said))
check("fetch: the top directory is stripped, executables kept, links inside kept",
      os.path.isfile(os.path.join(VDIR, "mouth", "voices.bin"))
      and os.access(os.path.join(VDIR, "runtime", "bin", "sherpa-onnx-offline-tts"), os.X_OK)
      and os.readlink(os.path.join(VDIR, "runtime", "lib", "libx.so")) == "libx.so.1"
      and os.path.isfile(os.path.join(VDIR, "vad", "silero_vad.onnx")), os.listdir(VDIR))
check("fetch: nothing missing after, nothing left over, a second fetch does nothing",
      voice.missing(fetch_pins()) == [] and not leftovers() and voice.fetch(None, fetch_pins()) == [], leftovers())
# a machine that has v1.70's mouth (the int8 export): its sha file is
# not the new pin's, so the mouth is missing, fetched again, the old gone
voice.fetch(None, fetch_pins(VOICE_MOUTH=row(OLD_MOUTH)), out=lambda s: None)
had_int8 = os.path.isfile(os.path.join(VDIR, "mouth", "model.int8.onnx"))
was = voice._mouth_model(os.path.join(VDIR, "mouth"))
gone = [p["name"] for p in voice.missing(fetch_pins())]
fetched[:] = []
voice.fetch(None, fetch_pins(), out=lambda s: None)
check("fetch: v1.70's int8 mouth is not the pin; fetched again, the old model gone, nothing left over",
      had_int8 and was == "model.int8.onnx" and gone == ["mouth"] and fetched == ["mouth.tar.bz2"]
      and sorted(os.listdir(os.path.join(VDIR, "mouth"))) == ["model.onnx", "voices.bin"] and not leftovers()
      and voice._mouth_model(os.path.join(VDIR, "mouth")) == "model.onnx", (gone, fetched, leftovers()))
check("remove: the voice dir goes whole, its bytes counted", voice.remove() > 0 and not os.path.exists(VDIR))
from spark import update  # noqa: E402
asked, _fetch_said = [], voice._fetch_said
voice._fetch_said = lambda c: asked.append(voice.mode(c)) or True
update._voice_pins(Cfg(SPARK_VOICE="off"))
update._voice_pins(Cfg(SPARK_VOICE="clear"))
voice._fetch_said = _fetch_said
check("spark update: the voice on or clear fetches a part whose pin changed (said first); off, nothing",
      asked == ["clear"], asked)

# ------------------------------------------------------------ 3. speaking
stub_engine()
cfg = Cfg(SPARK_VOICE_RATE="125")
w = voice.speak(cfg, "This is how spark reads aloud.", "clear")
argv = json.load(open(os.path.join(LOG, "tts.json")))["argv"]
check("speak clear: a wav 0600 in a private 0700 dir",
      os.path.isfile(w) and stat.S_IMODE(os.stat(w).st_mode) == 0o600
      and stat.S_IMODE(os.stat(os.path.dirname(w)).st_mode) == 0o700, w)
check("speak clear: Kokoro's flags, af_heart, en-us, the rate as the length scale, the text after --",
      "--sid=3" in argv and "--kokoro-lang=en-us" in argv and "--kokoro-length-scale=0.800" in argv
      and "--kokoro-model=model.onnx" in argv and "--kokoro-lexicon=lexicon-us-en.txt,lexicon-zh.txt" in argv
      and "--num-threads=%d" % voice.THREADS in argv and argv[-2:] == ["--", "This is how spark reads aloud."], argv)
d = os.path.dirname(w)
voice.cleanup(w)
check("cleanup: the private dir goes", not os.path.exists(d))
w = voice.speak(cfg, "Bom dia, você está bem? Não sei.", "clear")
argv = json.load(open(os.path.join(LOG, "tts.json")))["argv"]
check("speak clear, Portuguese: pf_dora, pt-br", "--sid=42" in argv and "--kokoro-lang=pt-br" in argv, argv)
voice.cleanup(w)
INT8 = os.path.join(VDIR, "mouth", "model.int8.onnx")
open(INT8, "w").close()
voice.cleanup(voice.speak(cfg, "Hello.", "clear"))
argv = json.load(open(os.path.join(LOG, "tts.json")))["argv"]
os.remove(INT8)
check("speak: a mouth an older pin left (model.int8.onnx alone) still speaks until the fetch replaces it",
      "--kokoro-model=model.int8.onnx" in argv, argv)
check("load_engine: no runtime library here (the stub runtime) -- None, the tool speaks", voice.load_engine() is None)
LIBF = voice._lib_file()
with open(LIBF, "wb") as f:
    f.write(b"not a library")
check("load_engine: a library that does not load -- None, never a raise", voice.load_engine() is None)
os.remove(LIBF)
w = voice.speak(cfg, "-rf is a flag\x1b[31m", "clear")
argv = json.load(open(os.path.join(LOG, "tts.json")))["argv"]
check("speak: a text starting with a dash rides after --, a control character is a space",
      argv[-2:] == ["--", "-rf is a flag [31m"], argv[-2:])
voice.cleanup(w)
r = voice.mint("terse", "fixture-seed")
w = voice.speak(cfg, "Hello.", "on", recipe=r)
argv = json.load(open(os.path.join(LOG, "tts.json")))["argv"]
with wave.open(w) as wv:
    shape = (wv.getnchannels(), wv.getsampwidth(), wv.getframerate())
check("speak on: the recipe's speaker at length scale 1, the character over it, 16-bit mono 24 kHz",
      "--sid=%s" % r["SID"] in argv and "--kokoro-length-scale=1.000" in argv and shape == (1, 2, 24000)
      and sha(w) != sha(TONE) and os.listdir(os.path.dirname(w)) == ["character.wav"], (argv, shape))
voice.cleanup(w)
try:
    voice.speak(cfg, "Hello.", "on")
    refused = ""
except voice.VoiceError as e:
    refused = str(e)
check("speak on with no voice kept: refused, naming spark awaken", "spark awaken" in refused, refused)

# ------------------------------------------------------------ 4. the chains
# the output of each family's chain over the fixed tone, hashed: the same
# recipe, the same bytes, on every machine (the hiss is a seeded Random)
PINNED = {
    "plain": "b095d867551c808c17a8c99c05cf4a915191d644be0ddb0a5766a2a7e6708544",
    "warm": "2f3b4cc80bbe7370279d5ea16e46f29ac9664bdf417d2ef20209ae3fca85d666",
    "playful": "91a2f6927d9a7f049abc3009cfbeb97ce1c45598e67458d4798cc8a8c2a94ef4",
    "terse": "f285e71169d0bf4df362e601014a981bc1f550356e8263025dad98cae177e9b3",
}
for temper in ("plain", "warm", "playful", "terse"):
    r = voice.mint(temper, "fixture-seed")
    a = voice.character(TONE, r, os.path.join(ROOT, "a-%s.wav" % temper))
    b = voice.character(TONE, r, os.path.join(ROOT, "b-%s.wav" % temper))
    with wave.open(a) as wv:
        shape = (wv.getnchannels(), wv.getsampwidth(), wv.getframerate(), wv.getnframes())
    check("character %s (%s): 16-bit mono at the input's rate, 0600" % (temper, r["FAMILY"]),
          shape[:3] == (1, 2, 24000) and shape[3] > 0 and stat.S_IMODE(os.stat(a).st_mode) == 0o600, shape)
    check("character %s: deterministic, and pinned (%s)" % (temper, sha(a)[:16]),
          sha(a) == sha(b) and sha(a) == PINNED[temper], sha(a))
check("character playful: resampled x%s, so shorter" % voice.mint("playful", "fixture-seed")["SPEED"],
      wave.open(os.path.join(ROOT, "a-playful.wav")).getnframes() < wave.open(TONE).getnframes())
other = voice.character(TONE, voice.mint("plain", "another-seed"), os.path.join(ROOT, "c-plain.wav"))
check("character: another seed, another radio", sha(other) != sha(os.path.join(ROOT, "a-plain.wav")))

# -------------------------------------------------------------- 5. mint
for temper, family in (("plain", "radio"), ("warm", "choir"), ("playful", "eightbit"), ("terse", "robot")):
    r1, r2 = voice.mint(temper, "box"), voice.mint(temper, "box")
    ok_range = all(abs(float(r1[k]) - base) <= span + 1e-9 for k, base, span in voice.RECIPES[family])
    check("mint %s: %s, the same for the same seed, a speaker of its list, every number in range" % (temper, family),
          r1 == r2 and r1["FAMILY"] == family and int(r1["SID"]) in voice.FAMILY_SIDS[family] and ok_range
          and int(r1["SID_PT"]) in voice.PT_SIDS.values(), r1)
seeds = {json.dumps(voice.mint("plain", "box:%d" % n), sort_keys=True) for n in range(6)}
check("mint: the next seeds give other voices (again)", len(seeds) > 1, seeds)
check("mint: an unknown temperament is plain's family", voice.mint("wistful", "box")["FAMILY"] == "radio")
check("the speakers: Kokoro v1.0's ids, a* and b* for English, p* for Portuguese",
      all(voice.SPEAKERS[s][:1] in "ab" for f in voice.FAMILY_SIDS.values() for s in f)
      and voice.SPEAKERS[42] == "pf_dora" and voice.SPEAKERS[43] == "pm_alex" and voice.SID_MAX == 53)

# ------------------------------------------------------------ 6. the recipe
r = voice.mint("warm", "box")
voice.write_recipe(r)
check("recipe: written 0600 as KEY=value lines, read back the same",
      stat.S_IMODE(os.stat(voice.RECIPE_FILE).st_mode) == 0o600 and voice.read_recipe() == r
      and all(config.LINE.match(l) for l in open(voice.RECIPE_FILE).read().splitlines()), open(voice.RECIPE_FILE).read())
with open(voice.RECIPE_FILE, "w") as f:
    f.write("FAMILY=radio\nSID=3\nSID_PT=42\nFREQ=99999\nQ=0.9\nDRIVE=2.5\nHISS=0.008\n")
check("recipe: a number out of its range is clamped", voice.read_recipe()["FREQ"] == "1350")
for body in ("FAMILY=opera\nSID=3\nSID_PT=42\n", "FAMILY=radio\nSID=99\nSID_PT=42\nFREQ=1200\nQ=1\nDRIVE=2\nHISS=0\n",
             "FAMILY=radio\nSID=3\nSID_PT=42\nFREQ=nan\nQ=1\nDRIVE=2\nHISS=0\n"):
    with open(voice.RECIPE_FILE, "w") as f:
        f.write(body)
    check("recipe: %r is no recipe" % body.split("\n")[0 if "opera" in body else 1 if "99" in body else 3],
          voice.read_recipe() is None)
os.remove(voice.RECIPE_FILE)
check("recipe: none kept, none read", voice.read_recipe() is None)

# ----------------------------------------------- 7. spoken_command, lang_of
for cmd, want in (("du -ah ~ | sort -rh", "du, dash a h, tilde, pipe, sort, dash r h"),
                  ("rm -rf build && ls > out.txt", "rm, dash r f, build, and then, ls, into, out.txt"),
                  ("echo $HOME >> ~/log; cat < in || true", "echo, dollar HOME, append to, tilde slash log then, "
                   "cat, from, in, or else, true"),
                  ("ls --all *.txt 2>&1 \\", "ls, dash dash all, star .txt, 2 into and 1, backslash"),
                  ("git log --pretty=oneline `pwd` \"a b\" 'c'", "git, log, dash dash pretty=oneline, backtick pwd "
                   "backtick, quote a, b quote, quote c quote"),
                  ("", "")):
    got = voice.spoken_command(cmd)
    check("spoken_command %r" % cmd, got == want, got)
for text, want in (("Bom dia, você está bem?", "pt"), ("How are you today?", "en"), ("Não.", "pt"),
                   ("The disk is full and the backup failed.", "en"), ("", "en")):
    check("lang_of %r is %s" % (text, want), voice.lang_of(text) == want, voice.lang_of(text))

# -------------------------------------------------------- 8. screen readers
for out, want in (("1", "VoiceOver"), ("0", ""), ("", "")):
    stub("defaults", "#!/bin/sh\n[ \"$3\" = voiceOverOnOffKey ] && echo %s\n" % out)
    check("screen_reader on macOS: defaults says %r -> %r" % (out, want), voice.screen_reader(mac=True) == want)
proc = os.environ["SPARK_PROC_DIR"]
os.makedirs(os.path.join(proc, "4242"))
with open(os.path.join(proc, "4242", "comm"), "w") as f:
    f.write("bash\n")
check("screen_reader on Linux: nothing running is ''", voice.screen_reader(mac=False) == "")
os.makedirs(os.path.join(proc, "4343"))
with open(os.path.join(proc, "4343", "comm"), "w") as f:
    f.write("orca\n")
check("screen_reader on Linux: an orca process is Orca", voice.screen_reader(mac=False) == "Orca")
shutil.rmtree(os.path.join(proc, "4343"))
os.makedirs(os.path.join(os.environ["SPARK_SYS_MODULE"], "speakup"))
check("screen_reader on Linux: the speakup module is speakup", voice.screen_reader(mac=False) == "speakup")
shutil.rmtree(os.path.join(os.environ["SPARK_SYS_MODULE"], "speakup"))
stub("defaults", "#!/bin/sh\necho 0\n")

# ------------------------------------------------------- 9. play and stop
PLAYER = "afplay" if IS_MAC else "aplay"
stub(PLAYER, "#!/bin/sh\necho \"$@\" >> \"$STUB_LOG/player\"\nsleep \"${STUB_PLAY:-0}\"\n")
w = voice.speak(cfg, "Hello there.", "clear")
d = os.path.dirname(w)
h = voice.play(Cfg(SPARK_VOICE_DEVICE="plughw:1,0"), w, wait=True)
played = open(os.path.join(LOG, "player")).read()
check("play: the OS's player on the wav, waited for; the private dir goes with it",
      w in played and h.done() and not os.path.exists(d) and not os.path.exists(voice.PLAYING_FILE), played)
if not IS_MAC:
    check("play on Linux: aplay -q -D SPARK_VOICE_DEVICE", "-q -D plughw:1,0 " + w in played, played)
os.environ["STUB_PLAY"] = "20"
w = voice.speak(cfg, "A long reply.", "clear")
t0 = time.time()
h = voice.play(cfg, w, wait=False)
check("play wait=False: back at once, the playing recorded for another spark",
      time.time() - t0 < 2 and not h.done() and os.path.exists(voice.PLAYING_FILE))
check("stop: the playing ends, its dir and the record go",
      voice.stop() and h.done() and not os.path.exists(os.path.dirname(w)) and not os.path.exists(voice.PLAYING_FILE))
w = voice.speak(cfg, "Another.", "clear")
code = ("import sys; sys.path.insert(0, %r); from spark import voice, config; "
        "voice.play(config.load(), %r, wait=False)" % (os.path.join(REPO, "lib"), w))
subprocess.run([PY, "-c", code], env=os.environ, timeout=20)
check("stop from another process: the recorded player is stopped",
      os.path.exists(voice.PLAYING_FILE) and voice.stop() and not os.path.exists(os.path.dirname(w)))
del os.environ["STUB_PLAY"]

# ------------------------------------------------------------ 10. listen
t0 = time.time()
heard = voice.listen(cfg, max_seconds=5)
vad = open(os.path.join(LOG, "vad.json")).read()
asr = json.load(open(os.path.join(LOG, "asr.json")))
check("listen: Whisper's text and lang, quick, the listener stopped at its first segment",
      heard == ("Bom dia, spark", "pt") and time.time() - t0 < 8, (heard, time.time() - t0))
check("listen: the silence detector's model, the pause, the device on Linux; a 0077 umask",
      "--silero-vad-model=" + os.path.join(VDIR, "vad", "silero_vad.onnx") in vad
      and "--silero-vad-min-silence-duration=0.80" in vad and "0o77" in vad
      and (IS_MAC or "'default'" in vad), vad)
rec_dir = os.path.dirname(asr["argv"][-1])
check("listen: the recording 0600 in a private dir, gone before listen returned",
      asr["mode"] == "0o600" and voice._ours(rec_dir) and not os.path.exists(rec_dir)
      and "--whisper-task=transcribe" in asr["argv"], asr)
os.environ["STUB_SILENT"] = "1"
t0 = time.time()
heard = voice.listen(cfg, max_seconds=1)
check("listen: nothing said is ('', ''), within the bound, the dir gone",
      heard == ("", "") and time.time() - t0 < 6, (heard, time.time() - t0))
del os.environ["STUB_SILENT"]


# 10b. the recorder never outlives spark: a listener that loops forever
# (and shrugs off SIGINT), spark hung up, terminated or killed mid-listen
# -- the recorder is gone within a second and its private dir with it
LOOP = """#!/bin/sh
trap '' INT
echo "$$ $PWD" > "$STUB_LOG/loop.pid"
while :; do sleep 0.2; done
"""
for name in ("sherpa-onnx-vad-microphone", "sherpa-onnx-vad-alsa"):
    stub(name, LOOP, os.path.join(VDIR, "runtime", "bin"))


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")


def killed_mid_listen(sig, argv):
    """(the recorder gone, its dir gone, seconds after the signal, the exit)"""
    pidf = os.path.join(LOG, "loop.pid")
    if os.path.exists(pidf):
        os.remove(pidf)
    tmpd = tempfile.mkdtemp(prefix="tmpdir-", dir=ROOT)
    env = dict(os.environ, SPARK_VOICE="clear", TMPDIR=tmpd)
    env.pop("SPARK_NO_APPLY", None)
    child = subprocess.Popen(argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    while time.time() - t0 < 15 and not (os.path.exists(pidf) and open(pidf).read().endswith("\n")):
        time.sleep(0.05)
    try:
        pid, where = open(pidf).read().split()
        pid = int(pid)
    except (OSError, ValueError):
        child.kill()
        child.wait()
        return False, False, -1, None
    time.sleep(0.3)
    os.kill(child.pid, sig)
    t0 = time.time()
    while time.time() - t0 < 3 and (alive(pid) or os.path.exists(where)):
        time.sleep(0.02)
    took = time.time() - t0
    gone = not alive(pid)
    if not gone:
        os.kill(pid, signal.SIGKILL)
    try:
        rc = child.wait(10)
    except subprocess.TimeoutExpired:
        child.kill()
        rc = child.wait()
    return gone, not os.path.exists(where) and voice._ours(where), took, rc


import signal  # noqa: E402
CALL = [PY, "-c", "import sys; sys.path.insert(0, %r); from spark import voice; voice.listen(None, max_seconds=30)"
        % os.path.join(REPO, "lib")]
for sig, label in ((signal.SIGHUP, "SIGHUP (a closed terminal)"), (signal.SIGTERM, "SIGTERM"),
                   (signal.SIGKILL, "SIGKILL")):
    gone, clean, took, rc = killed_mid_listen(sig, CALL)
    check("listen, spark sent %s mid-listen: the recorder is gone within a second, its dir removed" % label,
          gone and clean and 0 <= took < 1.0, (gone, clean, took, rc))
gone, clean, took, rc = killed_mid_listen(signal.SIGHUP, [PY, SPARK, "voice", "listen", "--buffer"])
check("spark voice listen --buffer hung up mid-listen: the recorder gone within a second, the dir removed, exit 129",
      gone and clean and 0 <= took < 1.0 and rc == 129, (gone, clean, took, rc))
src = open(os.path.join(REPO, "lib", "spark", "voice.py")).read()
check("listen: the recorder is never started in a session of its own (it stays in spark's process group)",
      "start_new_session" not in src[src.index("def _record("):src.index("def _option(")])
stub_engine()

# ------------------------------------------------------- 11. say_aloud
check("say_aloud off: None", voice.say_aloud(Cfg(SPARK_VOICE="off"), "hello") is None)
os.environ["STUB_PLAY"] = "0"
h = voice.say_aloud(Cfg(SPARK_VOICE="clear"), "hello", wait=True)
check("say_aloud clear: a handle, played", h is not None and h.done())
stub("defaults", "#!/bin/sh\necho 1\n")
os.makedirs(os.path.join(proc, "4444"))
with open(os.path.join(proc, "4444", "comm"), "w") as f:
    f.write("orca\n")
check("say_aloud clear beside a screen reader: silent", voice.say_aloud(Cfg(SPARK_VOICE="clear"), "hello") is None)
open(voice.ANYWAY_FILE, "w").close()
h = voice.say_aloud(Cfg(SPARK_VOICE="clear"), "hello", wait=True)
check("say_aloud clear --anyway: speaks beside it", h is not None)
os.remove(voice.ANYWAY_FILE)
shutil.rmtree(os.path.join(proc, "4444"))
stub("defaults", "#!/bin/sh\necho 0\n")
os.remove(os.path.join(VDIR, "runtime", "bin", "sherpa-onnx-offline-tts"))
try:
    h = voice.say_aloud(Cfg(SPARK_VOICE="clear"), "hello")
    raised = False
except Exception:  # noqa: BLE001
    raised = True
check("say_aloud with the engine gone: None, never a raise", h is None and not raised)
check("say_aloud on with no voice kept: None", voice.say_aloud(Cfg(SPARK_VOICE="on"), "hello") is None)
check("mode: off, on, clear; anything else off",
      [voice.mode(Cfg(SPARK_VOICE=v)) for v in ("off", "on", "CLEAR", "loud", "")] == ["off", "on", "clear", "off", "off"])
del os.environ["STUB_PLAY"]


# ------------------------------------------------------- 12. the verb
def spark(*args, extra=None):
    env = dict(os.environ, SPARK_NO_APPLY="1", **(extra or {}))
    p = subprocess.run([PY, SPARK] + list(args), capture_output=True, text=True, env=env, timeout=60)
    return p.returncode, p.stdout + p.stderr


def senv():
    try:
        return open(os.path.join(HOME, ".config", "spark", "spark.env")).read()
    except OSError:
        return ""


stub_engine()
rc, out = spark("voice", "-h")
check("spark voice -h: signed, within 80 columns",
      rc == 0 and out.startswith("spark voice -- ") and max(len(l) for l in out.splitlines()) <= 80, out)
rc, out = spark("voice")
check("spark voice: the state, off; nothing written",
      rc == 0 and out.startswith("voice   off ") and "\nengine  downloaded" in out and "\nplayer  " in out
      and out.endswith("\nrate    100\n") and not senv(), out)
rc, out = spark("voice", "status")
check("spark voice status is bare", rc == 0 and out.startswith("voice   off "), out)
rc, out = spark("voice", "clear")
check("spark voice clear: SPARK_VOICE=clear", rc == 0 and "SPARK_VOICE=clear\n" in senv() and "clear" in out, out)
rc, out = spark("voice", "rate", "150")
check("spark voice rate 150: kept", rc == 0 and "SPARK_VOICE_RATE=150\n" in senv(), out)
rc, out = spark("voice", "rate", "20")
check("spark voice rate 20: refused, exit 2", rc == 2 and out.startswith("spark voice -- ") and "50" in out, out)
rc, out = spark("voice", "test")
check("spark voice test under SPARK_NO_APPLY: the line said, nothing played",
      rc == 0 and out.startswith("* ") and not os.path.exists(os.path.join(LOG, "player-test")), out)
rc, out = spark("voice", "off")
check("spark voice off: SPARK_VOICE=off", rc == 0 and "SPARK_VOICE=off\n" in senv(), out)
rc, out = spark("voice", "test")
check("spark voice test while off: says so, exit 1", rc == 1 and "off" in out, out)
rc, out = spark("voice", "on")
check("spark voice on, unawakened: refused, naming spark awaken and clear",
      rc == 1 and "spark awaken" in out and "spark voice clear" in out and "SPARK_VOICE=on" not in senv(), out)
stub("defaults", "#!/bin/sh\necho 1\n")
os.makedirs(os.path.join(proc, "4545"))
with open(os.path.join(proc, "4545", "comm"), "w") as f:
    f.write("orca\n")
rc, out = spark("voice", "clear")
check("spark voice clear beside a screen reader: stays off, says why, exit 1",
      rc == 1 and ("VoiceOver" in out or "Orca" in out) and "--anyway" in out and "SPARK_VOICE=off\n" in senv(), out)
rc, out = spark("voice", "clear", "--anyway")
check("spark voice clear --anyway: on, the choice kept",
      rc == 0 and "SPARK_VOICE=clear\n" in senv() and os.path.exists(voice.ANYWAY_FILE), out)
rc, out = spark("voice")
check("spark voice: the screen reader and the --anyway named", rc == 0 and "\nreader  " in out and "--anyway" in out, out)
shutil.rmtree(os.path.join(proc, "4545"))
stub("defaults", "#!/bin/sh\necho 0\n")
rc, out = spark("voice", "off", "--remove")
check("spark voice off --remove under SPARK_NO_APPLY: says what would be freed, keeps it; the --anyway choice goes",
      rc == 0 and "MB would be freed" in out and os.path.isdir(VDIR) and not os.path.exists(voice.ANYWAY_FILE), out)
rc, out = spark("voice", "loud")
check("spark voice loud: one signed line, exit 2", rc == 2 and out.startswith("spark voice -- no word loud"), out)
for bad in (["on", "please"], ["test", "it", "now"], ["listen", "--bufer"], ["stop", "x"], ["status", "now"],
            ["--loud"], ["of", "reason", "--x"], ["rate", "1", "2"]):
    rc, out = spark("voice", *bad, extra={"SPARK_BASE_URL": "http://127.0.0.1:9", "SPARK_API_KEY": "t"})
    check("spark voice %s: the usage, exit 2 -- never a question for the model" % " ".join(bad),
          rc == 2 and "is not a voice command" in out and "spark voice listen" in out, out[-300:])


# --------------------------------------------------- 13. the check row
class Ctx:
    def __init__(self):
        self.cfg = config.load()
        self.repo = REPO


from spark import check as checkmod  # noqa: E402
os.environ["SPARK_VOICE"] = "off"
r = checkmod.row_voice(Ctx())
check("check voice, off: na, the remedy spark voice clear", r.status == "na" and r.remedy.startswith("spark voice clear"),
      (r.status, r.value, r.remedy))
os.environ["SPARK_VOICE"] = "clear"
r = checkmod.row_voice(Ctx())
check("check voice, clear, the engine its pins', a player: ok", r.status == "ok" and PLAYER in r.value,
      (r.status, r.value))
with open(os.path.join(VDIR, "ears.sha"), "w") as f:
    f.write("0" * 64 + "\n")
r = checkmod.row_voice(Ctx())
check("check voice, a part not its pin: warn, naming it, the remedy spark voice clear",
      r.status == "warn" and "ears" in r.value and r.remedy == "spark voice clear", (r.status, r.value, r.remedy))
stub_engine()
os.environ["SPARK_VOICE"] = "on"
r = checkmod.row_voice(Ctx())
check("check voice, on with no voice kept: warn, the remedy spark awaken",
      r.status == "warn" and r.remedy == "spark awaken", (r.status, r.value))
voice.write_recipe(voice.mint("plain", "box"))
r = checkmod.row_voice(Ctx())
check("check voice, on with its voice: ok", r.status == "ok", (r.status, r.value))
os.remove(voice.RECIPE_FILE)
del os.environ["SPARK_VOICE"]

# ------------------------------------------------------ 14. awaken's offer
spark_env = os.path.join(HOME, ".config", "spark", "spark.env")
if os.path.exists(spark_env):
    os.remove(spark_env)


def awaken(answers, extra=None):
    path = os.path.join(ROOT, "answers")
    with open(path, "w") as f:
        f.write(answers)
    env = dict(os.environ, SPARK_AWAKEN_TTY=path, SPARK_BASE_URL="http://127.0.0.1:9", SPARK_API_KEY="t",
               SPARK_TIMEOUT="3", STUB_PLAY="0")
    env.pop("SPARK_NO_APPLY", None)
    env.update(extra or {})
    p = subprocess.run([PY, SPARK, "awaken"], capture_output=True, text=True, env=env, timeout=120)
    return p.returncode, p.stdout + p.stderr


open(os.path.join(LOG, "player"), "w").close()
rc, out = awaken("warm\nagain\nkeep\n")
kept = voice.read_recipe()
check("awaken: the voice offered, spoken twice (again), kept: the recipe 0600, SPARK_VOICE=on",
      rc == 0 and out.count("keep it? (keep, again, none)") == 2 and kept and kept["FAMILY"] == "choir"
      and stat.S_IMODE(os.stat(voice.RECIPE_FILE).st_mode) == 0o600 and "SPARK_VOICE=on\n" in senv()
      and len(open(os.path.join(LOG, "player")).read().splitlines()) == 2, out[-900:])
os.remove(voice.RECIPE_FILE)
with open(spark_env, "w") as f:
    f.write("SPARK_VOICE=clear\n")
rc, out = awaken("plain\nkeep\n")
check("awaken with the clear voice on: the voice kept is written, SPARK_VOICE stays clear, said in one line",
      rc == 0 and voice.read_recipe() and "SPARK_VOICE=clear\n" in senv() and "SPARK_VOICE=on" not in senv()
      and "The clear voice stays on: spark voice on speaks in this one." in out, out[-600:])
os.remove(voice.RECIPE_FILE)
os.remove(spark_env)
rc, out = awaken("plain\n\n")
check("awaken: Enter at the voice is none: no recipe, SPARK_VOICE untouched",
      rc == 0 and "keep it?" in out and voice.read_recipe() is None and "SPARK_VOICE" not in senv(), out[-600:])
rc, out = awaken("terse\n", extra={"SPARK_NO_APPLY": "1"})
check("awaken under SPARK_NO_APPLY: no voice offered", rc == 0 and "keep it?" not in out, out[-600:])
shutil.rmtree(VDIR)
rc, out = awaken("plain\n\n")
check("awaken with no engine: the size asked first (yes/NO), Enter is no, nothing fetched",
      rc == 0 and "MB to download? yes/NO" in out and not os.path.exists(VDIR) and voice.read_recipe() is None,
      out[-600:])

# ---------------------------------------------------- 15. the surfaces
STUBF = os.path.join(ROOT, "spoken")


def spoken():
    try:
        with open(STUBF) as f:
            return f.read().splitlines()
    except OSError:
        return []


os.environ["SPARK_VOICE_STUB"] = STUBF
check("stub: say_aloud appends what it would say, one line, and plays nothing",
      voice.say_aloud(Cfg(SPARK_VOICE="clear"), "two\nlines  here") is None and spoken() == ["two lines here"],
      spoken())
voice.say_aloud(Cfg(SPARK_VOICE="off"), "never")
check("stub: mode off says nothing", spoken() == ["two lines here"], spoken())
os.environ["SPARK_VOICE_STUB_HEARD"] = "  what is   using the disk  "
check("stub: listen hears SPARK_VOICE_STUB_HEARD and opens no microphone (the engine is gone)",
      voice.listen(Cfg(SPARK_VOICE="clear")) == ("what is using the disk", "en"))
check("heard_line: every control character out -- a heard newline never sends a line",
      voice.heard_line("rm -rf /\r\nyes\x1b[A\x07 ok") == "rm -rf / yes [A ok")
check("line_words: a command by its symbols, then the hint",
      voice.line_words(["cmd\tdu -ah ~ | sort -rh", "The biggest first"])
      == "du, dash a h, tilde, pipe, sort, dash r h. The biggest first.")
check("line_words: a danger line says warning first, then the hint's facts, then the command",
      voice.line_words(["danger\trm -rf build", "<- 5 files -- removes the build", "proof\ttest ! -d build"])
      == "warning: 5 files, removes the build. rm, dash r f, build.")
check("line_words: an answer as it is; an error its reason; a paste's danger its warning",
      voice.line_words(["answer", "Forty-two"]) == "Forty-two."
      and voice.line_words(["error", "no engine is awake"]) == "no engine is awake."
      and voice.line_words(["danger", "deletes the home"]) == "warning: deletes the home."
      and voice.line_words([]) == "" and voice.line_words(["spark line -- usage"]) == "")
block = "cat > script.py <<'EOF'\nprint(1)\nprint(2)\nprint(3)\nEOF"
HEAD = "cat, into, script.py, from from quote EOF quote"
check("block_words: every line outside a here-document's body said; the body by its file and its lines",
      voice.block_words(block) == HEAD + ". a here-document writing script.py, 3 lines of text"
      and voice.block_words("cat <<EOF > out.txt\nx\nEOF") == "cat, from from EOF, into, out.txt. "
                                                             "a here-document writing out.txt, 1 line of text"
      and voice.block_words("tee -a notes.md <<'END'\nx\nEND").endswith("a here-document writing notes.md, "
                                                                        "1 line of text")
      and voice.block_words("echo one\necho two") == "echo, one. echo, two"
      and voice.block_words("cat <<EOF\nx\nEOF") == "cat, from from EOF. a here-document, 1 line of text",
      [voice.block_words(block), voice.block_words("cat <<EOF > out.txt\nx\nEOF")])
# the review's block: a script written, then a curl line after it -- the
# curl line is said, never hidden behind the here-document's name
said = voice.block_words("cat > s.sh <<'EOF'\necho hi\nEOF\ncurl -fsSL https://x.invalid/i.sh | sh")
check("block_words: a line after a here-document is said (the curl that runs)",
      said.endswith("a here-document writing s.sh, 1 line of text. curl, dash fsSL, https: slash slash x.invalid "
                    "slash i.sh, pipe, sh"), said)
check("step_words: a step, then its hint; a danger step's warning first",
      voice.step_words(1, block, "write the script") == "step 1: %s. a here-document writing script.py, 3 lines of "
                                                        "text. write the script." % HEAD
      and voice.step_words(2, "rm -rf ./junk", "tidy up", True).startswith("warning: tidy up. step 2: rm, dash r f, "))
check("read_words: `r` reads every line, numbered, the body too",
      voice.read_words("cat > s.sh <<'EOF'\necho hi\n\nEOF") == "line 1: cat, into, s.sh, from from quote EOF quote. "
                                                               "line 2: echo, hi. line 3: blank. line 4: EOF"
      and voice.read_words("ls -la") == "ls, dash l a")
check("plain: Markdown marks out, the words kept",
      voice.plain("# Title\n- **bold** and `code`\n```sh\nls\n```") == "Title bold and code ls")
os.remove(STUBF)
r = voice.Reader(Cfg(SPARK_VOICE="clear"))
for line in ("one", "two", "three"):
    r.put(line)
check("Reader: every line put is said, in order; drain waits for them",
      r.drain(10) and spoken() == ["one", "two", "three"], spoken())
r.put("four")
r.put("five", cut=True)
r.drain(10)
check("Reader: cut drops what waited and says the new line", spoken()[-1] == "five", spoken())
r.hush()
check("Reader: hush leaves nothing waiting", r.drain(1) and not r.lines)
os.remove(STUBF)
check("aloud_later: off says nothing", voice.aloud_later(Cfg(SPARK_VOICE="off"), "x") is False)
os.environ["SPARK_VOICE"] = "clear"
t0 = time.time()
started = voice.aloud_later(None, "said by a detached process")
while time.time() - t0 < 15 and not spoken():
    time.sleep(0.1)
check("aloud_later: a detached process says it; the caller returned at once",
      started and spoken() == ["said by a detached process"], spoken())


def spark3(*args, extra=None):
    env = dict(os.environ, SPARK_NO_APPLY="1", **(extra or {}))
    p = subprocess.run([PY, SPARK] + list(args), capture_output=True, text=True, env=env, timeout=60)
    return p.returncode, p.stdout, p.stderr


rc, out, err = spark3("voice", "listen", "--buffer")
check("spark voice listen --buffer: the words on stdout alone, exit 0", rc == 0 and out == "what is using the disk\n",
      repr(out))
check("the stub seam honoured says so once on stderr, as SPARK_DO_STDIN's banner does",
      err == voice.SEAM_BANNER + "\n" and "SPARK_VOICE_STUB" in err, repr(err))
rc, out, err = spark3("voice", "listen")
check("spark voice listen: says it listens, then the words",
      rc == 0 and out == "listening -- speak, a pause ends it\nwhat is using the disk\n", repr(out))
rc, out, err = spark3("voice", "listen", "--buffer", extra={"SPARK_VOICE_STUB_HEARD": " "})
check("spark voice listen --buffer, nothing heard: nothing on stdout, exit 1", rc == 1 and out == "", repr(out))
env_off = dict(os.environ, SPARK_VOICE="off", SPARK_NO_APPLY="1")
p = subprocess.run([PY, SPARK, "voice", "listen", "--buffer"], capture_output=True, text=True, env=env_off, timeout=60)
check("spark voice listen --buffer while off: stdout empty, the reason on stderr, exit 2",
      p.returncode == 2 and p.stdout == "" and "off" in p.stderr, (p.returncode, p.stdout, p.stderr))
rc, out = spark("voice", "stop")
check("spark voice stop: nothing playing, nothing said, exit 0", rc == 0 and out == "", repr(out))
rc, out = spark("voice", "-h")
check("spark voice -h: listen and stop named, within 80 columns",
      "spark voice listen" in out and "spark voice stop" in out and max(len(l) for l in out.splitlines()) <= 80, out)
for k in ("SPARK_VOICE", "SPARK_VOICE_STUB", "SPARK_VOICE_STUB_HEARD"):
    os.environ.pop(k, None)

# ------------------------------------------------- 16. keeping pace (v1.71)
# the splitter: the reply's text as it streams, cut into sentences
def split(text, code=True):
    s = voice.Sentences(code)
    return s.feed(text) + s.flush()


def split_chunks(text, sizes, code=True):
    s = voice.Sentences(code)
    out, i, k = [], 0, 0
    while i < len(text):
        n = sizes[k % len(sizes)]
        out += s.feed(text[i:i + n])
        i, k = i + n, k + 1
    return out + s.flush()


check("Sentences: a sentence ends at . ! ? before a space or the end",
      split("One here. Two there! Three? Four") == ["One here.", "Two there!", "Three?", "Four"],
      split("One here. Two there! Three? Four"))
check("Sentences: never inside a number (3.14, 2.718, v1.70)",
      split("Ok. Pi is 3.14 and e is 2.718 in v1.70. Next.") == ["Ok.", "Pi is 3.14 and e is 2.718 in v1.70.", "Next."],
      split("Ok. Pi is 3.14 and e is 2.718 in v1.70. Next."))
check("Sentences: never after a kept abbreviation (e.g. i.e. Dr. Mr. Mrs. vs.)",
      split("Ok. Use a tool, e.g. grep, i.e. a finder. Dr. Who and Mr. and Mrs. Smith, vs. them. End.")
      == ["Ok.", "Use a tool, e.g. grep, i.e. a finder.", "Dr. Who and Mr. and Mrs. Smith, vs. them.", "End."],
      split("Ok. Use a tool, e.g. grep, i.e. a finder. Dr. Who and Mr. and Mrs. Smith, vs. them. End."))
check("Sentences: closing quotes and brackets stay with their sentence; a run of marks is one end",
      split('He said "stop." Then (once.) Wait... Really?! Ok') == ['He said "stop."', "Then (once.)", "Wait...",
                                                                "Really?!", "Ok"])
check("Sentences: a list item ends at its line break; a numbered item's `1.` ends nothing",
      split("Steps:\n1. Install it.\n2. Run it\n- one\n- two\n\nAfter.")
      == ["Steps:", "1. Install it.", "2. Run it", "- one", "- two", "After."],
      split("Steps:\n1. Install it.\n2. Run it\n- one\n- two\n\nAfter."))
check("Sentences: nothing splits inside an inline code span",
      split("Run `ls -la. echo! x?` now. Done.") == ["Run `ls -la. echo! x?` now.", "Done."],
      split("Run `ls -la. echo! x?` now. Done."))
FENCED = "Run this:\n```sh\necho one. two!\necho three\n\n```\nThen look."
check("Sentences: a fence is one line in clear mode -- a code block, N lines -- never split inside",
      split(FENCED) == ["Run this:", "a code block, 3 lines", "Then look."], split(FENCED))
check("Sentences: mode on skips a fence whole",
      split(FENCED, code=False) == ["Run this:", "Then look."], split(FENCED, code=False))
check("Sentences: an unclosed fence at the end is still one line",
      split("Look:\n```\nx = 1\ny = 2") == ["Look:", "a code block, 2 lines"], split("Look:\n```\nx = 1\ny = 2"))
LONG = "word " * 30 + "and then, " + "more " * 60 + "end"
got = split("Ok. " + LONG)[1:]
check("Sentences: a run with no end is cut near SENTENCE_MAX, at a comma when one is there, else at a space",
      len(got) >= 2 and got[0].endswith("and then,") and all(len(x) <= voice.SENTENCE_MAX for x in got)
      and " ".join(got).split() == LONG.split(), [len(x) for x in got])
got = split("x" * 300)
check("Sentences: one word longer than the cut is said whole, never lost",
      "".join(got) == "x" * 300, [len(x) for x in got])
check("Sentences: marks alone are no sentence", split("**\n---\n\nOk.") == ["Ok."], split("**\n---\n\nOk."))
REPLY = ("Pi is 3.14, e.g. close. The disk is full! Why?\n1. Free it.\n- `du -sh .` first.\n"
         "```sh\ndu -sh ~\nls\n```\nAll done" + " and so on, more words" * 14 + ".")
whole = split(REPLY)
same = all(split_chunks(REPLY, sizes) == whole for sizes in ([1], [2], [3], [5, 1, 7], [4, 9, 2, 1], [11], [64]))
check("Sentences: a stream split anywhere -- mid-word, mid-number, mid-fence -- gives the sentences one chunk does",
      same and len(whole) == 9 and whole[0] == "Pi is 3.14,", whole)
s = voice.Sentences()
first = s.feed("The first one is here. The sec")
check("Sentences: a sentence goes the moment its end is seen; the rest waits",
      first == ["The first one is here."] and s.feed("ond one") == [] and s.flush() == ["The second one"],
      first)
s = voice.Sentences()
check("Sentences: a period at the chunk's end waits for the next character (3. then 14)",
      s.feed("Pi is 3.") == [] and s.feed("14 now. ") == ["Pi is 3.14 now."])

# the lead-in: silence before the first word, the wav's format kept
stub_engine()


def frames(path):
    with wave.open(path) as wv:
        return (wv.getnchannels(), wv.getsampwidth(), wv.getframerate()), wv.readframes(wv.getnframes())


shape0, tone0 = frames(TONE)
cfg = Cfg(SPARK_VOICE_RATE="100")
w = voice.speak(cfg, "Hello there.", "clear")
shape, data = frames(w)
lead = int(24000 * voice.LEAD_IN_MS / 1000) * 2
check("lead-in: the clear wav opens with %d ms of zero samples, then the engine's own, the format kept"
      % voice.LEAD_IN_MS, voice.LEAD_IN_MS == 250 and shape == shape0 and data[:lead] == b"\0" * lead
      and data[lead:] == tone0 and stat.S_IMODE(os.stat(w).st_mode) == 0o600, (shape, len(data), len(tone0)))
voice.cleanup(w)
w = voice.speak(Cfg(SPARK_VOICE="clear"), "hello there", "clear", lead=0)
check("lead-in: speak(lead=0) adds none", frames(w)[1] == tone0)
voice.cleanup(w)
os.environ["SPARK_VOICE_LEAD_MS"] = "0"
w = voice.speak(cfg, "Hello there.", "clear")
check("lead-in: SPARK_VOICE_LEAD_MS=0 adds none", frames(w)[1] == tone0)
voice.cleanup(w)
os.environ["SPARK_VOICE_LEAD_MS"] = "100"
w = voice.speak(cfg, "Hello there.", "clear")
check("lead-in: SPARK_VOICE_LEAD_MS=100 adds 100 ms", frames(w)[1] == b"\0" * 4800 + tone0)
voice.cleanup(w)
for bad in ("1001", "-5", "loud"):
    os.environ["SPARK_VOICE_LEAD_MS"] = bad
    check("lead-in: SPARK_VOICE_LEAD_MS=%s is out of 0..1000: the constant" % bad, voice.lead_ms() == voice.LEAD_IN_MS)
del os.environ["SPARK_VOICE_LEAD_MS"]
w = voice.speak(cfg, "Hello.", "on", recipe=voice.mint("terse", "fixture-seed"))
shape, data = frames(w)
check("lead-in: after the character chain too (mode on), still one wav in its dir",
      data[:lead] == b"\0" * lead and data[lead:].strip(b"\0") != b"" and shape == (1, 2, 24000)
      and os.listdir(os.path.dirname(w)) == ["character.wav"], os.listdir(os.path.dirname(w)))
voice.cleanup(w)
eight = os.path.join(ROOT, "eight.wav")
with wave.open(eight, "wb") as wv:
    wv.setnchannels(2)
    wv.setsampwidth(1)
    wv.setframerate(8000)
    wv.writeframes(b"\x10\x20" * 10)
voice.lead_in(eight, 10)
check("lead-in: an 8-bit stereo wav keeps its format, its silence the 8-bit middle",
      frames(eight) == ((2, 1, 8000), b"\x80" * 160 + b"\x10\x20" * 10), frames(eight))

# the first sentence of a reply goes at its first pause, or after
# FIRST_WORDS words with none: the first sound never waits for a whole
# sentence to be shown
check("Sentences: the first sentence goes at its first comma; the rest of it, and the next, whole",
      split("Well, the disk is nearly full and the logs grow by a gigabyte a day, so clean them. "
            "Then, once that is done, look again.")
      == ["Well,", "the disk is nearly full and the logs grow by a gigabyte a day, so clean them.",
          "Then, once that is done, look again."])
check("Sentences: a semicolon or a colon is a first pause too; a comma inside 1,000 is not",
      split("It holds 1,000 files; most are logs. Ok.") == ["It holds 1,000 files;", "most are logs.", "Ok."]
      and split("Three steps: copy, check, go. Ok.") == ["Three steps:", "copy, check, go.", "Ok."])
check("Sentences: a short first sentence with no pause is whole",
      split("Yes it works. Next, the rest of it.") == ["Yes it works.", "Next, the rest of it."])
check("Sentences: a first sentence with no pause goes after %d words, the rest of it whole" % voice.FIRST_WORDS,
      split("Runit is a lightweight init system and service manager for Linux. It is small, and fast.")
      == ["Runit is a lightweight init system", "and service manager for Linux.", "It is small, and fast."])
FIRST = ("So here is what I found after reading the whole log file twice: three errors. "
         "Two, maybe three, are the same one. Fine.")
whole = split(FIRST)
def ended(text, sizes):
    s, ends, i, k = voice.Sentences(), [], 0, 0
    while i < len(text):
        n = sizes[k % len(sizes)]
        s.feed(text[i:i + n])
        ends += s.ends()
        i, k = i + n, k + 1
    s.flush()
    return ends + s.ends()


ENDED = "Pi is 3.14, e.g. close. Is it \"full!\" Why?\n1. Free it.\n```sh\ndu -sh ~\n```\nAll done."
cuts = ended(ENDED, [len(ENDED)])
check("Sentences: ends() -- where each piece ends in the text fed, the same whatever the chunking",
      [ENDED[a:b] for a, b in zip([0] + cuts, cuts)] == ["Pi is 3.14, ", "e.g. close.", ' Is it "full!"', " Why?",
                                                          "\n1. Free it.", "\n```sh\ndu -sh ~\n```\n", "All done."]
      and all(ended(ENDED, sizes) == cuts for sizes in ([1], [2], [3], [7, 1])), cuts)
check("Sentences: the first cut is the same whatever the chunking",
      whole[:2] == ["So here is what I found", "after reading the whole log file twice: three errors."]
      and all(split_chunks(FIRST, sizes) == whole for sizes in ([1], [2], [3], [7, 1], [64])), whole)
s = voice.Sentences()
check("Sentences: the first cut goes the moment its pause or its word count is seen",
      s.feed("Right, ") == ["Right,"] and s.feed("word " * 12) == [] and s.feed("and more. ") == ["word " * 11 + "word and more."]
      and s.flush() == [] and voice.Sentences().feed("one two three four five six") == []
      and voice.Sentences().feed("one two three four five six ") == ["one two three four five six"])

# the Reader's two stages, against a slow stub engine: each clip it makes
# is one value held (an id from its text), so the player's side can say
# which clip it got, and where silence was
CLIP_S = 0.2


def ident(text):
    return 1000 + sum(text.encode()) % 20000


SLOW_TTS = '''#!%s
import array, json, os, sys, time, wave
out = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--output-filename=")][0]
t0 = time.time()
time.sleep(float(os.environ.get("STUB_TTS", "0")))
text = sys.argv[-1]
n = int(24000 * float(os.environ.get("STUB_CLIP", "%s")))
a = array.array("h", [1000 + sum(text.encode()) %% 20000] * n)
if sys.byteorder == "big":
    a.byteswap()
w = wave.open(out, "wb")
w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(a.tobytes()); w.close()
with open(os.path.join(os.environ["STUB_LOG"], "tts.jsonl"), "a") as f:
    f.write(json.dumps({"text": text, "t0": t0, "t1": time.time()}) + "\\n")
''' % (PY, CLIP_S)
# the player of a file (afplay on macOS): what it got -- the clip's id,
# the silence before it -- and when it started and ended
TIMED_PLAYER = '''#!%s
import array, json, os, sys, time, wave
log = os.path.join(os.environ["STUB_LOG"], "plays.jsonl")
with wave.open(sys.argv[-1]) as w:
    a = array.array("h", w.readframes(w.getnframes()))
lead = next((i for i, v in enumerate(a) if v), len(a))
ident = a[lead] if lead < len(a) else 0
with open(log, "a") as f:
    f.write(json.dumps({"id": ident, "lead": lead, "start": time.time()}) + "\\n")
time.sleep(float(os.environ.get("STUB_PLAY", "0")))
with open(log, "a") as f:
    f.write(json.dumps({"id": ident, "end": time.time()}) + "\\n")
''' % PY
# the stream (aplay -t raw on Linux): every byte it was given, in order,
# with when each read came and whether it held sound; its EOF logged
STREAM = '''#!%s
import json, os, sys, time
log = os.environ["STUB_LOG"]
pid = os.getpid()
rate = int(sys.argv[sys.argv.index("-r") + 1]) if "-r" in sys.argv else 24000
def note(**kv):
    with open(os.path.join(log, "streams.jsonl"), "a") as f:
        f.write(json.dumps(dict(pid=pid, **kv)) + "\\n")
note(start=time.time(), argv=sys.argv[1:])
with open(os.path.join(log, "stream-%%d.raw" %% pid), "wb") as raw:
    while True:
        b = os.read(0, 4800)
        if not b:
            break
        raw.write(b)
        raw.flush()
        note(t=time.time(), n=len(b), sound=any(b))
        time.sleep(len(b) / (2.0 * rate))           # a sound card's pace
note(eof=time.time())
''' % PY
stub("sherpa-onnx-offline-tts", SLOW_TTS, os.path.join(VDIR, "runtime", "bin"))
stub(PLAYER, TIMED_PLAYER)
STREAM_STUB = stub("spark-test-stream", STREAM)
TMP = os.path.join(ROOT, "tmp")
os.makedirs(TMP)
tempfile.tempdir = TMP              # the private dirs land here, so a leftover is seen
_stream_argv = voice.stream_argv


def per_clip(on):
    """The player the Reader picks: one wav at a time (macOS's afplay),
    or the stream stub fed raw PCM (Linux's aplay -t raw)."""
    voice.stream_argv = (lambda cfg, rate: None) if on else (lambda cfg, rate: [STREAM_STUB, "-r", str(rate)])


def jsonl(name):
    try:
        with open(os.path.join(LOG, name)) as f:
            return [json.loads(l) for l in f if l.strip()]
    except OSError:
        return []


def ours():
    return sorted(d for d in os.listdir(TMP) if d.startswith("spark-voice-"))


def reset_logs():
    for name in os.listdir(LOG):
        if name.endswith((".jsonl", ".raw")):
            os.remove(os.path.join(LOG, name))


def wait_for(cond, secs=15):
    end = time.time() + secs
    while time.time() < end and not cond():
        time.sleep(0.02)
    return cond()


def runs(pid):
    """A stream's bytes as runs: [(value or 0 for silence, frames)]."""
    a = array.array("h")
    with open(os.path.join(LOG, "stream-%d.raw" % pid), "rb") as f:
        a.frombytes(f.read())
    if sys.byteorder == "big":
        a.byteswap()
    out = []
    for v in a:
        if out and out[-1][0] == v:
            out[-1][1] += 1
        else:
            out.append([v, 1])
    return [tuple(x) for x in out]


LEAD = int(24000 * voice.LEAD_IN_MS / 1000)
FRAMES = int(24000 * CLIP_S)

# per clip (macOS): made ahead while one plays, the lead-in after quiet
per_clip(True)
reset_logs()
os.environ.update(STUB_TTS="0.4", STUB_PLAY="0.8")
r = voice.Reader(Cfg(SPARK_VOICE="clear"))
t0 = time.time()
for line in ("one.", "two.", "three."):
    r.put(line)
put_took = time.time() - t0
done = r.drain(20, played=True)
made = jsonl("tts.jsonl")
plays = jsonl("plays.jsonl")
starts = [p for p in plays if "start" in p]
ends = [p for p in plays if "end" in p]
check("Reader per clip: put returns at once; every line made and played, in order",
      put_took < 0.2 and done and [m["text"] for m in made] == ["one.", "two.", "three."]
      and [p["id"] for p in starts] == [ident(t) for t in ("one.", "two.", "three.")],
      (put_took, done, [m["text"] for m in made], starts))
if len(made) == 3 and len(starts) == 3 and len(ends) == 3:
    overlap = min(made[1]["t1"], ends[0]["end"]) - max(made[1]["t0"], starts[0]["start"])
    gap = starts[1]["start"] - ends[0]["end"]
else:
    overlap, gap = -1.0, 99.0
check("Reader per clip: sentence 2 is made WHILE sentence 1 plays (overlap %.2f s), so it starts as 1 ends "
      "(gap %.2f s)" % (overlap, gap), overlap > 0.2 and gap < 0.35, (overlap, gap))
check("Reader per clip: every wav removed once played", wait_for(lambda: not ours(), 5), ours())
check("Reader per clip: the lead-in only on the first of a run of sentences",
      [p["lead"] for p in starts] == [LEAD, 0, 0], [p["lead"] for p in starts])
time.sleep(voice.WAKE_AFTER + 0.3)
os.environ.update(STUB_PLAY="0.1")
r.put("four.")
r.drain(10, played=True)
check("Reader per clip: after a quiet moment the next sentence has its lead-in again",
      [p["lead"] for p in jsonl("plays.jsonl") if "start" in p][3:] == [LEAD])

# per clip: cut drops the queued text and the clips made ready, and stops
# what plays; a new line after it plays
reset_logs()
os.environ.update(STUB_TTS="0.3", STUB_PLAY="5")
r = voice.Reader(Cfg(SPARK_VOICE="clear"))
for line in ("alpha.", "beta.", "gamma.", "delta."):
    r.put(line)
full = wait_for(lambda: len(r.ready) == voice.AHEAD and r.playing is not None and len(jsonl("plays.jsonl")) == 1)
playing_dir = r.playing.tmp if r.playing is not None else ""
check("Reader: bounded -- %d made ahead while one plays, the rest still text" % voice.AHEAD,
      full and [x[1] for x in r.lines] == ["delta."], (full, r.lines, len(r.ready)))
cut = r.cut()
gone = wait_for(lambda: not os.path.isdir(playing_dir) and not ours(), 5)
check("Reader: cut drops the queued text and the ready clips and stops what plays (its wav removed)",
      cut and playing_dir and gone and not r.lines and not r.ready and r.playing is None
      and [m["text"] for m in jsonl("tts.jsonl")] == ["alpha.", "beta.", "gamma."]
      and not any("end" in p for p in jsonl("plays.jsonl")), (cut, gone, ours(), jsonl("tts.jsonl")))
os.environ["STUB_PLAY"] = "0"
r.put("after.")
r.drain(10, played=True)
check("Reader: after a cut the next line is made and played",
      [p["id"] for p in jsonl("plays.jsonl") if "start" in p] == [ident("alpha."), ident("after.")] and not ours(),
      (jsonl("plays.jsonl"), ours()))
r.put("hushed.")
wait_for(lambda: r.busy or r.ready or r.playing is not None, 5)
r.hush()
check("Reader: hush leaves nothing waiting, nothing ready", r.drain(2) and not r.lines and not r.ready)
wait_for(lambda: not ours(), 5)

# the stream (Linux): one player for a burst -- the lead-in once, the
# clips in order with silence between, closed once idle, a cut kills it
per_clip(False)
reset_logs()
os.environ.update(STUB_TTS="0.6", STUB_PLAY="0")
r = voice.Reader(Cfg(SPARK_VOICE="clear"))
for line in ("one.", "two.", "three."):
    r.put(line)
done = r.drain(20, played=True)
opened = [x for x in jsonl("streams.jsonl") if "start" in x]
pid = opened[0]["pid"] if opened else 0
check("stream: one player process for three sentences, raw PCM at the clip's rate",
      done and len(opened) == 1 and opened[0]["argv"] == ["-r", "24000"], opened)
# the card's pace lags the writes (the player's start): its EOF, once idle, says all of it was read
eof = wait_for(lambda: any("eof" in x for x in jsonl("streams.jsonl")), 8)
got = runs(pid) if pid else []
said = [v for v, _n in got if v]
check("stream: the lead-in once, at the start (%d frames of silence), then the first clip" % LEAD,
      len(got) > 1 and got[0] == (0, LEAD) and got[1] == (ident("one."), FRAMES), got[:3])
check("stream: the clips whole and in order, silence between them while the next is made",
      said == [ident(t) for t in ("one.", "two.", "three.")] and all(n == FRAMES for v, n in got if v)
      and [v for v, _n in got[1:6]] == [ident("one."), 0, ident("two."), 0, ident("three.")], got)
log = jsonl("streams.jsonl")
last_sound = max((x["t"] for x in log if x.get("sound")), default=0)
closed = next((x["eof"] for x in log if "eof" in x), 0)
check("stream: closed (its end of input, not a kill) about %.1f s after the last clip (%.2f s)"
      % (voice.STREAM_IDLE, closed - last_sound), eof and 1.0 < closed - last_sound < 3.5 and r.stream is None,
      (closed - last_sound, r.stream))
check("stream: the stream's player is gone after its close", wait_for(lambda: not alive(pid), 5))
r.put("four.")
r.drain(10, played=True)
# the stub reads at a card's pace: its EOF says it read all it was given
wait_for(lambda: len([x for x in jsonl("streams.jsonl") if "eof" in x]) == 2, 8)
opened = [x for x in jsonl("streams.jsonl") if "start" in x]
check("stream: the next burst opens a new player, the lead-in first again",
      len(opened) == 2 and runs(opened[1]["pid"])[:2] == [(0, LEAD), (ident("four."), FRAMES)],
      runs(opened[1]["pid"])[:3] if len(opened) == 2 else opened)
wait_for(lambda: r.stream is None, 5)

reset_logs()
os.environ.update(STUB_TTS="0.1", STUB_CLIP="3")
r = voice.Reader(Cfg(SPARK_VOICE="clear"))
for line in ("long one.", "never two.", "never three."):
    r.put(line)
wait_for(lambda: any(x.get("sound") for x in jsonl("streams.jsonl")), 10)
pid = next((x["pid"] for x in jsonl("streams.jsonl") if "start" in x), 0)
cut = r.cut()
dead = wait_for(lambda: not alive(pid), 5)
time.sleep(0.5)
said = [v for v, _n in runs(pid) if v] if pid else []
check("stream: a cut kills the player at once -- no end of input, nothing queued written after",
      cut and dead and not any("eof" in x and x["pid"] == pid for x in jsonl("streams.jsonl")) and r.stream is None
      and set(said) <= {ident("long one.")} and not r.lines and not r.ready, (cut, dead, said))
check("stream: stopped, it leaves no record for another spark's stop", not os.path.exists(voice.PLAYING_FILE))
os.environ.pop("STUB_CLIP")

# the exit: a process that ends with clips made ahead drops them; the one
# playing runs on (per clip: its player removes its wav; the stream: its
# end of input, so it plays out what it holds and exits on its own)
reset_logs()
code = ("import sys, time; sys.path.insert(0, %r); from spark import voice\n"
        "voice.stream_argv = lambda cfg, rate: None\n"
        "r = voice.Reader(None)\n"
        "for t in ('first.', 'second.', 'third.'):\n"
        "    r.put(t)\n"
        "end = time.time() + 15\n"
        "while time.time() < end and not (len(r.ready) == 2 and r.playing is not None):\n"
        "    time.sleep(0.02)\n"
        "print(len(r.ready), r.playing is not None)\n" % os.path.join(REPO, "lib"))
p = subprocess.run([PY, "-c", code], capture_output=True, text=True, timeout=60,
                   env=dict(os.environ, TMPDIR=TMP, SPARK_VOICE="clear", STUB_TTS="0.2", STUB_PLAY="1.5"))
left = ours()
check("Reader at exit (per clip): the clips made ahead go with the process; only the one playing is left",
      p.stdout.split() == ["2", "True"] and len(left) <= 1, (p.stdout, p.stderr[-300:], left))
check("Reader at exit (per clip): the one playing removes its own when it ends", wait_for(lambda: not ours(), 8),
      ours())
code = ("import sys, time; sys.path.insert(0, %r); from spark import voice\n"
        "voice.stream_argv = lambda cfg, rate: [%r, '-r', str(rate)]\n"
        "r = voice.Reader(None)\n"
        "r.put('last words.')\n"
        "print(r.drain(15))\n" % (os.path.join(REPO, "lib"), STREAM_STUB))
p = subprocess.run([PY, "-c", code], capture_output=True, text=True, timeout=60,
                   env=dict(os.environ, TMPDIR=TMP, SPARK_VOICE="clear", STUB_TTS="0.1"))
wait_for(lambda: any("start" in x for x in jsonl("streams.jsonl")), 8)     # it may start after the exit
pid = next((x["pid"] for x in jsonl("streams.jsonl") if "start" in x), 0)
eof = wait_for(lambda: any("eof" in x and x["pid"] == pid for x in jsonl("streams.jsonl")), 8)
check("Reader at exit (stream): drain waits until the clip is written whole; the stream ends with its input, "
      "every frame of it given", p.stdout.split() == ["True"] and eof and pid
      and [v for v, _n in runs(pid) if v] == [ident("last words.")]
      and sum(n for v, n in runs(pid) if v) == FRAMES, (p.stdout, p.stderr[-300:], eof))

# the runtime's warnings (fprintf to the C library's stderr) go nowhere
# once the engine is loaded; Python's own lines and a child's still show
HUSH = """import ctypes, os, sys
sys.path.insert(0, %r)
from spark import voice
libc = ctypes.CDLL(None)
libc.fputs.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
cerr = lambda: ctypes.c_void_p.in_dll(libc, "__stderrp" if voice.IS_MAC else "stderr").value
libc.fputs(b"c-before\\n", cerr()); libc.fflush(None)
took = voice.hush_native()
libc.fputs(b"c-after\\n", cerr()); libc.fflush(None)
sys.stderr.write("python %%s\\n" %% took); sys.stderr.flush()
os.system("echo child >&2")
""" % os.path.join(REPO, "lib")
p = subprocess.run([PY, "-c", HUSH], capture_output=True, text=True, timeout=30)
check("hush_native: the C library's stderr goes nowhere; Python's lines and a child's still show",
      p.stderr.split() == ["c-before", "python", "True", "child"], p.stderr)

# the text follows the voice (forge._Spoken.begin): each sentence goes to
# the reader as the model writes it, and its text is shown as its sound
# starts, at the pace that ends it with the sound. A wrap that writes at
# once and keeps when, so the waits are the follow's own
from spark import forge  # noqa: E402


class Shown:
    def __init__(self, cps):
        self.cps, self.got, self.paces = cps, [], []

    def pace(self, cps):
        self.paces.append(cps)

    def feed(self, text):
        self.got.append((time.monotonic(), text))


class Busy:
    def __init__(self):
        self.stopped = None

    def stop(self):
        if self.stopped is None:
            self.stopped = time.monotonic()


def follow(reply, cfg, chunk=5, halt_after=None):
    r = voice.Reader(cfg)
    forge.VOICE.update(reader=r, mode="clear", aloud=True)
    sp, wrap, busy = forge._Spoken(), Shown(100), Busy()
    sp.begin(wrap, busy)
    t0 = time.monotonic()
    for i in range(0, len(reply), chunk):
        sp.take(reply[i:i + chunk])
    if halt_after is not None:
        time.sleep(halt_after)
        sp.stop()
    else:
        sp.end()
    took = time.monotonic() - t0
    r.cut()
    return sp, wrap, busy, took, t0


REPLY = "Void Linux is small, and it is fast. It boots with runit. Done."
per_clip(False)
reset_logs()
os.environ.update(STUB_TTS="0.1", STUB_CLIP="0.6")
sp, wrap, busy, took, t0 = follow(REPLY, Cfg(SPARK_VOICE="clear"))
made = jsonl("tts.jsonl")
text = "".join(t for _w, t in wrap.got)
check("follow: every sentence to the voice as written, the text shown whole and in order",
      [m["text"] for m in made] == ["Void Linux is small,", "and it is fast.", "It boots with runit.", "Done."]
      and text == REPLY, ([m["text"] for m in made], text))
check("follow: the first text waits for the first sound (the busy pulse until then)",
      made and wrap.got and busy.stopped is not None and wrap.got[0][0] - t0 >= 0.1 + voice.LEAD_IN_MS / 1000.0 - forge.FOLLOW_EARLY - 0.05,
      (wrap.got[:1], busy.stopped and busy.stopped - t0))
check("follow: back only once the last sentence sounds, after three of 0.6 s (%.2f s)" % took,
      took >= 3 * 0.6 - forge.FOLLOW_EARLY, took)
want = [len(x) / (0.6 * forge.FOLLOW_SHARE) for x in ("Void Linux is small,", "and it is fast.",
                                                      "It boots with runit.", "Done.")]
check("follow: each sentence at the pace its sound sets, never the chosen one",
      len(wrap.paces) == 4 and all(abs(a - max(b, 5)) < 2 for a, b in zip(wrap.paces, want)), (wrap.paces, want))

reset_logs()
sp, wrap, busy, took, t0 = follow(REPLY, Cfg(SPARK_VOICE="off"))
check("follow: nothing sounds (the voice off) -- the text at the chosen pace, no wait",
      took < 1.0 and "".join(t for _w, t in wrap.got) == REPLY and set(wrap.paces) == {100}, (took, wrap.paces))

reset_logs()
os.environ.update(STUB_TTS="1.5")
forge.FOLLOW_WAIT, wait = 0.3, forge.FOLLOW_WAIT
sp, wrap, busy, took, t0 = follow(REPLY, Cfg(SPARK_VOICE="clear"))
forge.FOLLOW_WAIT = wait
check("follow: a voice too slow -- after one wait the text goes on at the chosen pace, whole",
      took < 1.5 and "".join(t for _w, t in wrap.got) == REPLY and sp.loose and set(wrap.paces) == {100},
      (took, wrap.paces))

reset_logs()
os.environ.update(STUB_TTS="0.1", STUB_CLIP="2")
sp, wrap, busy, took, t0 = follow(REPLY, Cfg(SPARK_VOICE="clear"), halt_after=0.8)
shown = "".join(t for _w, t in wrap.got)
check("follow: stopped (Ctrl-C) -- back at once, the text not yet sounded stays unshown",
      took < 1.5 and not sp.thread.is_alive() and REPLY.startswith(shown) and len(shown) < len(REPLY), (took, shown))
os.environ.pop("STUB_CLIP", None)
forge.VOICE.update(reader=None, aloud=False)

voice.stream_argv = _stream_argv
for k in ("STUB_TTS", "STUB_PLAY"):
    os.environ.pop(k, None)
tempfile.tempdir = None

# the engine against the real runtime: on this Mac only, when a voice is
# here (SPARK_VOICE_REAL_DIR, else ~/.local/share/spark/voice); never in CI
REAL_LIB = os.path.join(REAL_VOICE, "runtime", "lib", "libsherpa-onnx-c-api.dylib")
REAL_MOUTH = os.path.join(REAL_VOICE, "mouth")
why = ("not macOS" if not IS_MAC else "CI" if IN_CI else "no runtime library at %s" % REAL_LIB
       if not os.path.isfile(REAL_LIB) else "no model.onnx in %s" % REAL_MOUTH
       if not os.path.isfile(os.path.join(REAL_MOUTH, "model.onnx")) else "")
if why:
    print("skip the engine against the real runtime: %s" % why)
else:
    import ctypes
    c = voice._c()
    P = ctypes.sizeof(ctypes.c_void_p)
    check("engine: the structs mirror c-api.h (Kokoro 7 pointers and a float; lang last; the audio a pointer and 2 ints)",
          ctypes.sizeof(c["Kokoro"]) == 7 * P + P and c["Kokoro"].lang.offset == 7 * P
          and c["Kokoro"].length_scale.offset == 4 * P and ctypes.sizeof(c["Audio"]) == P + 8
          and c["Gen"].extra.offset == ctypes.sizeof(c["Gen"]) - P)
    t0 = time.monotonic()
    e = voice.Engine(REAL_LIB, REAL_MOUTH)
    rate = e.load()
    load_s = time.monotonic() - t0
    lib = e.lib
    lib.SherpaOnnxOfflineTtsNumSpeakers.restype = ctypes.c_int32
    lib.SherpaOnnxOfflineTtsNumSpeakers.argtypes = [ctypes.c_void_p]
    speakers = lib.SherpaOnnxOfflineTtsNumSpeakers(e.handles[""])
    check("engine: loaded once, Kokoro v1.0 as the config said (24 kHz, 54 speakers, %s, lang per call)" % e.model,
          rate == 24000 and speakers == 54 and e.loads == 1 and e.per_call and e.model == "model.onnx",
          (rate, speakers, e.loads, e.per_call))
    SENT = "The quick brown fox jumps over the lazy dog while the sun sets slowly behind the hills."
    t1 = time.monotonic()
    x1, fs1 = e.say(SENT, 3, 1.0, "en-us")
    g1 = time.monotonic() - t1
    t2 = time.monotonic()
    x2, fs2 = e.say("Bom dia, você está bem? Não sei o que fazer agora.", 42, 1.0, "pt-br")
    g2 = time.monotonic() - t2
    x3, _ = e.say(SENT, 3, 1.25, "en-us")
    check("engine: two sentences, the second with no reload (loads %d), each well inside its own length"
          % e.loads, e.loads == 1 and fs1 == fs2 == 24000 and len(x1) > 3 * fs1 and len(x2) > fs2
          and g1 < len(x1) / fs1 and g2 < len(x2) / fs2 and max(abs(v) for v in x1) <= 1.0
          and len(x3) < len(x1), (e.loads, g1, g2))
    x4, _ = e.say("Bom dia, você está bem? Não sei o que fazer agora.", 42, 1.0, "en-us")
    check("engine: the language rides each call (pt-br and en-us read the same words differently)",
          abs(len(x4) - len(x2)) > fs2 // 10, (len(x2), len(x4)))
    pcm, fs = voice.clip(Cfg(SPARK_VOICE="on"), SENT, "on", engine=e, recipe=voice.mint("warm", "fixture-seed"))
    check("clip on: the character over the engine's samples, 16-bit, the peak at 0.89",
          fs == 24000 and len(pcm) // 2 > 3 * fs
          and abs(max(abs(v) for v in array.array("h", pcm)) - 29163) <= 1, (len(pcm), len(x1)))
    costs = []
    for temper in ("plain", "warm", "playful", "terse"):
        t3 = time.monotonic()
        voice._pcm(voice.chain(x1, fs1, voice.mint(temper, "fixture-seed")), 0.89)
        costs.append("%s %.2f s" % (temper, time.monotonic() - t3))
    print("     engine: load %.2f s; generate %.2f s for %.2f s of audio, %.2f s for %.2f s (pt-br); "
          "the chain and the PCM over it: %s" % (load_s, g1, len(x1) / fs1, g2, len(x2) / fs2, ", ".join(costs)))
    e.close()
    # the Reader end to end: the real engine, the stream stub; loaded once
    per_clip(False)
    reset_logs()
    os.environ["SPARK_VOICE_DIR"] = REAL_VOICE
    r = voice.Reader(Cfg(SPARK_VOICE="clear"))
    t0 = time.monotonic()
    r.put("Hello there.")
    first = wait_for(lambda: any(x.get("sound") for x in jsonl("streams.jsonl")), 20)
    first_s = time.monotonic() - t0
    r.put("A second sentence, made by the same engine.")
    r.drain(20, played=True)
    pid = next((x["pid"] for x in jsonl("streams.jsonl") if "start" in x), 0)
    check("Reader with the engine: the first sound %.2f s after put (the load once with it), both sentences "
          "on one stream, the engine loaded once" % first_s,
          first and r.engine and r.engine.loads == 1 and len([x for x in jsonl("streams.jsonl") if "start" in x]) == 1
          and sum(n for v, n in runs(pid) if v) > 24000, (first_s, r.engine))
    r.cut()
    os.environ["SPARK_VOICE_DIR"] = VDIR
    voice.stream_argv = _stream_argv

shutil.rmtree(ROOT, ignore_errors=True)
print("voice_test: %s" % ("all ok" if not FAILED else "%d failed" % FAILED))
sys.exit(1 if FAILED else 0)
