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
again, none, and none under SPARK_NO_APPLY).
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
check("voice.env: about 380 MB in all on this machine (%d MB)" % total, 350 < total < 400)

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
GOOD_MOUTH = tarball("mouth.tar.bz2", [("kokoro/model.int8.onnx", "file", b"m"), ("kokoro/voices.bin", "file", b"v")])
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
      "sha256 mismatch" in refused and not os.path.exists(os.path.join(VDIR, "mouth"))
      and not os.path.exists(os.path.join(VDIR, "mouth.sha")) and not leftovers(), (refused, leftovers()))
check("fetch: the part before it landed whole (runtime, its sha file)",
      voice.installed(voice.parts(fetch_pins())[0]), os.listdir(VDIR))
try:
    voice.fetch(None, fetch_pins(VOICE_MOUTH=row(GOOD_MOUTH, size=5)), out=lambda s: None)
    refused = ""
except voice.VoiceError as e:
    refused = str(e)
check("fetch: a size mismatch is refused before the sha256", "the pin says 5" in refused and not leftovers(), refused)

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
fetched[:] = []
said = []
got = voice.fetch(None, fetch_pins(), out=said.append)
check("fetch: the missing parts come, each said with its size; the one there is not fetched again",
      got == ["mouth", "ears", "vad"] and fetched == ["mouth.tar.bz2", "ears.tar.bz2", "silero_vad.onnx"]
      and all("downloading" in s and "MB)" in s for s in said), (got, fetched, said))
check("fetch: the top directory is stripped, executables kept, links inside kept",
      os.path.isfile(os.path.join(VDIR, "mouth", "voices.bin"))
      and os.access(os.path.join(VDIR, "runtime", "bin", "sherpa-onnx-offline-tts"), os.X_OK)
      and os.readlink(os.path.join(VDIR, "runtime", "lib", "libx.so")) == "libx.so.1"
      and os.path.isfile(os.path.join(VDIR, "vad", "silero_vad.onnx")), os.listdir(VDIR))
check("fetch: nothing missing after, nothing left over, a second fetch does nothing",
      voice.missing(fetch_pins()) == [] and not leftovers() and voice.fetch(None, fetch_pins()) == [], leftovers())
check("remove: the voice dir goes whole, its bytes counted", voice.remove() > 0 and not os.path.exists(VDIR))

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
      and "--kokoro-model=model.int8.onnx" in argv and "--kokoro-lexicon=lexicon-us-en.txt,lexicon-zh.txt" in argv
      and "--num-threads=4" in argv and argv[-2:] == ["--", "This is how spark reads aloud."], argv)
d = os.path.dirname(w)
voice.cleanup(w)
check("cleanup: the private dir goes", not os.path.exists(d))
w = voice.speak(cfg, "Bom dia, você está bem? Não sei.", "clear")
argv = json.load(open(os.path.join(LOG, "tts.json")))["argv"]
check("speak clear, Portuguese: pf_dora, pt-br", "--sid=42" in argv and "--kokoro-lang=pt-br" in argv, argv)
voice.cleanup(w)
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
      rc == 0 and out.startswith("voice   off ") and "\nengine  here" in out and "\nplayer  " in out
      and "\nrate    100 " in out and not senv(), out)
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
check("spark voice off --remove under SPARK_NO_APPLY: says what would go, keeps it; the --anyway choice goes",
      rc == 0 and "would go" in out and os.path.isdir(VDIR) and not os.path.exists(voice.ANYWAY_FILE), out)
rc, out = spark("voice", "loud")
check("spark voice loud: one signed line, exit 2", rc == 2 and out.startswith("spark voice -- no word loud"), out)


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
os.remove(spark_env)
rc, out = awaken("plain\n\n")
check("awaken: Enter at the voice is none: no recipe, SPARK_VOICE untouched",
      rc == 0 and "keep it?" in out and voice.read_recipe() is None and "SPARK_VOICE" not in senv(), out[-600:])
rc, out = awaken("terse\n", extra={"SPARK_NO_APPLY": "1"})
check("awaken under SPARK_NO_APPLY: no voice offered", rc == 0 and "keep it?" not in out, out[-600:])
shutil.rmtree(VDIR)
rc, out = awaken("plain\n\n")
check("awaken with no engine: the size asked first (yes/NO), Enter is no, nothing fetched",
      rc == 0 and "MB to download first? yes/NO" in out and not os.path.exists(VDIR) and voice.read_recipe() is None,
      out[-600:])

shutil.rmtree(ROOT, ignore_errors=True)
print("voice_test: %s" % ("all ok" if not FAILED else "%d failed" % FAILED))
sys.exit(1 if FAILED else 0)
