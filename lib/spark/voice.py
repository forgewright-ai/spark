# spark.voice -- `spark voice`: spark reads aloud, and hears a question.
#
# One runtime does both, sherpa-onnx, pinned per flavour in voice.env
# beside the three models it runs: the mouth (Kokoro v1.0, 54 speakers,
# English and Brazilian Portuguese among them), the ears (Whisper base)
# and the end of a spoken question (the Silero voice activity detector).
# Nothing is vendored: fetch() downloads what is missing into
# ~/.local/share/spark/voice (SPARK_VOICE_DIR overrides it, the tests'
# seam), checks the size and the sha256 before it unpacks a byte, and
# unpacks member by member, refusing an absolute path, a `..`, a link
# that points out, or anything but files, directories and links.
#
# Three modes, SPARK_VOICE (contract 3, spark.env):
#   off    silent (the default)
#   clear  a plain clear voice for low vision, no character; works before
#          spark awaken. SPARK_VOICE_RATE is its speed (50..300, 100 as
#          made: Kokoro's length scale is 100/rate). A screen reader
#          running (VoiceOver, Orca, speakup) wins: clear stays silent and
#          says why, unless `spark voice clear --anyway`.
#   on     the machine's own voice: never a plain human voice, a
#          character spark awaken makes from the temperament and the seed
#          the face's body uses -- the recipe in ~/.config/spark/voice.
#
# The characters, one family per temperament, stdlib only:
#   radio     plain    an RBJ band-pass near 1200 Hz (q 0.9), a tanh drive,
#                      a faint hiss from a seeded Random
#   choir     warm     a 3-voice chorus, then a 40 Hz ring at 0.5 wet
#   eightbit  playful  resampled x1.15, each sample held 3, 5 bits
#   robot     terse    a 55 Hz ring fully wet into a 4 ms comb, feedback 0.45
# The recipe jitters each chain's numbers within a small range by the
# seed, and picks the Kokoro speaker from a short list per family. The
# chains are deterministic for a recipe: the same input, the same bytes.
#
# Listening: the runtime's own voice activity tool records until a pause
# (sherpa-onnx-vad-microphone on macOS, through portaudio; -vad-alsa on
# Linux, SPARK_VOICE_DEVICE or ALSA's default), run in a private 0700
# directory with a 0077 umask. It writes the spoken segment there as a
# wav; Whisper (sherpa-onnx-offline) reads it and prints one JSON line
# whose "text" and "lang" listen() returns. The directory is removed
# before listen() returns, always. One tool on each OS ends at silence,
# and Whisper names the language itself.
#
# The API the voice's surfaces call: mode(cfg), say_aloud(cfg, text,
# wait=False), stop(), listen(cfg), spoken_command(command), lang_of(text),
# screen_reader(); below them speak(), character(), play(), fetch(),
# mint(), read_recipe() and write_recipe().

import array
import hashlib
import json
import math
import os
import platform
import random
import re
import select
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import wave

from . import CONFIG_DIR, DATA_DIR, IS_MAC, MARK, REPO, SPARK_ENV, STATE_DIR, config, is_musl, say

VOICE_USAGE = """%s voice -- spark reads aloud, and hears a question

  spark voice                   the state: the mode, the engine, the voice,
                                the player, the mic, a screen reader
  spark voice clear [--anyway]  read aloud in a plain clear voice, for low
                                vision; it needs no awaken. A screen reader
                                running wins, unless --anyway
  spark voice on                speak in this machine's own voice, the one
                                spark awaken chose for it
  spark voice off [--remove]    silent; --remove deletes the engine too
  spark voice rate [N]          the clear voice's speed, 50 to 300 (100 is
                                as made)
  spark voice test              one line aloud, in the current mode

  The first on or clear downloads the engine, about 380 MB, into
  ~/.local/share/spark/voice: sherpa-onnx, the Kokoro voice, Whisper and a
  voice activity detector, each pinned by sha256 in voice.env. On macOS
  the terminal asks once for the microphone.
""" % MARK

MODES = ("off", "on", "clear")
RATE_MIN, RATE_MAX, RATE_DEFAULT = 50, 300, 100
SPEAK_MAX = 2000            # characters one speak() reads; the rest is cut at a word
SPEAK_TIMEOUT = 120         # seconds the engine may take for one text
LISTEN_TIMEOUT = 60         # seconds Whisper may take for one question
SILENCE = 0.8               # seconds of quiet that end a spoken question
THREADS = 4

# What fetch() names the parts, the voice.env key each comes from, and
# where each lands under the voice directory. The runtime's key is the
# flavour's.
RUNTIME_KEYS = {"macos": "VOICE_RUNTIME_MACOS", "x86_64": "VOICE_RUNTIME_LINUX_X64",
                "aarch64": "VOICE_RUNTIME_LINUX_ARM64", "arm64": "VOICE_RUNTIME_LINUX_ARM64"}
PART_KEYS = (("runtime", None), ("mouth", "VOICE_MOUTH"), ("ears", "VOICE_EARS"), ("vad", "VOICE_VAD"))

# Kokoro v1.0's speaker table (sherpa-onnx's kokoro-int8-multi-lang-v1_0:
# 54 speakers, 0..52 and em_santa at 53), the ones spark uses. a* is
# American English, b* British, p* Brazilian Portuguese; f and m the
# voice's register. The English ones are those Kokoro's own grades rate
# clearest (af_heart A, af_bella A-, af_nicole B-, bf_emma B-, the C+
# ones after them).
SPEAKERS = {1: "af_aoede", 2: "af_bella", 3: "af_heart", 5: "af_kore", 6: "af_nicole", 7: "af_nova",
            9: "af_sarah", 11: "am_adam", 14: "am_fenrir", 16: "am_michael", 17: "am_onyx",
            18: "am_puck", 21: "bf_emma", 25: "bm_fable", 26: "bm_george",
            42: "pf_dora", 43: "pm_alex"}
SID_MAX = 53
PT_SIDS = {"f": 42, "m": 43}            # a Portuguese reply: the p* speaker of the same register
CLEAR_SID, CLEAR_SID_PT = 3, 42         # the clear voice: af_heart, pf_dora

# The four families: the temperament picks one, the seed a speaker from
# its list and each number within base +- span.
TEMPER_FAMILY = {"plain": "radio", "warm": "choir", "playful": "eightbit", "terse": "robot"}
FAMILY_SIDS = {"radio": (3, 16, 21, 26), "choir": (2, 9, 1, 25),
               "eightbit": (18, 5, 6, 7), "robot": (14, 17, 26, 11)}
RECIPES = {
    "radio": (("FREQ", 1200.0, 150.0), ("Q", 0.9, 0.1), ("DRIVE", 2.5, 0.5), ("HISS", 0.008, 0.003)),
    "choir": (("DEPTH", 3.0, 0.8), ("RATE", 0.3, 0.1), ("RING", 40.0, 4.0), ("WET", 0.5, 0.06)),
    "eightbit": (("SPEED", 1.15, 0.04), ("HOLD", 3, 0), ("BITS", 5, 0)),
    "robot": (("RING", 55.0, 5.0), ("COMB", 4.0, 0.5), ("FEEDBACK", 0.45, 0.05)),
}
INT_KEYS = ("HOLD", "BITS")

# The symbols a clear reading says by name (spoken_command), the longest
# first so `>>` is never `into, into`.
SYMBOL_WORDS = (("&&", "and then"), ("||", "or else"), (">>", "append to"), ("--", "dash dash"),
                ("|", "pipe"), (">", "into"), ("&", "and"), (";", "then"), ("~", "tilde"),
                ("-", "dash"), ("/", "slash"), ("*", "star"), ("$", "dollar"), ("`", "backtick"),
                ('"', "quote"), ("'", "quote"), ("<", "from"), ("\\", "backslash"))

# A few words that only Portuguese writes, and a few only English does:
# lang_of counts them, plus the letters with Portuguese marks.
PT_WORDS = frozenset("nao não você voce é está esta isso isto para uma que os da dos das na em eu ele ela "
                     "nós nos seu sua mais por como mas também tambem obrigado obrigada bom dia boa noite "
                     "tarde aqui agora quando onde porque já ja muito muita".split())
EN_WORDS = frozenset("the and is are you to of it that in this with for not what how was be on at "
                     "your my we they have has do does can will would".split())
PT_LETTERS = re.compile(u"[ãõçáéíóúâêôà]", re.I)


class VoiceError(Exception):
    """One lowercase line for the person: what failed, and the remedy."""


# ------------------------------------------------------------------ paths
def voice_dir():
    """Where the engine lives: SPARK_VOICE_DIR, else the data dir's voice/."""
    return os.environ.get("SPARK_VOICE_DIR") or os.path.join(DATA_DIR, "voice")


RECIPE_FILE = os.path.join(CONFIG_DIR, "voice")
ANYWAY_FILE = os.path.join(STATE_DIR, "voice-anyway")
PLAYING_FILE = os.path.join(STATE_DIR, "voice-playing")


def _bin(name):
    return os.path.join(voice_dir(), "runtime", "bin", name)


def _lib_env():
    """The environment the runtime's tools run in: its lib on the loader's path."""
    env = dict(os.environ)
    lib = os.path.join(voice_dir(), "runtime", "lib")
    key = "DYLD_LIBRARY_PATH" if IS_MAC else "LD_LIBRARY_PATH"
    env[key] = lib + (os.pathsep + env[key] if env.get(key) else "")
    return env


def _private_dir():
    """A fresh 0700 directory for one text's or one question's files."""
    return tempfile.mkdtemp(prefix="spark-voice-")


def _ours(path):
    return os.path.basename(path.rstrip("/")).startswith("spark-voice-")


def cleanup(path):
    """Remove a wav speak() made, with its private directory."""
    if not path:
        return
    d = path if os.path.isdir(path) else os.path.dirname(path)
    if _ours(d):
        shutil.rmtree(d, ignore_errors=True)
    else:
        try:
            os.remove(path)
        except OSError:
            pass


def _umask():
    os.umask(0o077)


# ------------------------------------------------------------------- pins
def pins(repo=None):
    """voice.env as a dict (contract 3's reader)."""
    return config.parse_env(os.path.join(repo or REPO, "voice.env"))


def runtime_key():
    if IS_MAC:
        return RUNTIME_KEYS["macos"]
    return RUNTIME_KEYS.get(platform.machine().lower(), "")


def _row(value):
    """(url, bytes, sha256) from "<url> <bytes> <sha256>", or None."""
    words = (value or "").split()
    if len(words) != 3 or not words[1].isdigit() or not re.match(r"^[0-9a-f]{64}$", words[2]):
        return None
    return words[0], int(words[1]), words[2]


def parts(p=None):
    """The four parts this machine needs, as dicts (name, url, size, sha,
    kind); a part with no pin here has url ''."""
    p = pins() if p is None else p
    out = []
    for name, key in PART_KEYS:
        key = key or runtime_key()
        row = _row(p.get(key, "")) if key else None
        url, size, sha = row or ("", 0, "")
        out.append({"name": name, "url": url, "size": size, "sha": sha,
                    "kind": "file" if url.endswith(".onnx") else "tar"})
    return out


def _target(part):
    d = voice_dir()
    if part["kind"] == "file":
        return os.path.join(d, part["name"], os.path.basename(part["url"]) or "model.onnx")
    return os.path.join(d, part["name"])


def installed(part):
    """The part is here and is the pin's: its sha file holds the pin's sha256."""
    if not part["sha"] or not os.path.exists(_target(part)):
        return False
    try:
        with open(os.path.join(voice_dir(), part["name"] + ".sha"), encoding="utf-8") as f:
            return f.read().strip() == part["sha"]
    except OSError:
        return False


def missing(p=None):
    return [x for x in parts(p) if not installed(x)]


def _mb(n):
    return int(round(n / 1e6))


# ------------------------------------------------------------------ fetch
def _download(url, dest):
    """curl into dest, https only, redirects included: the bar at a
    terminal (grammar rule 6), quiet otherwise. True when curl says so."""
    if not shutil.which("curl"):
        raise VoiceError("no curl on PATH, so nothing can be downloaded")
    tty = sys.stderr.isatty()
    cmd = ["curl", "-fL" if tty else "-fsSL", "--proto", "=https", "--proto-redir", "=https", "--retry", "3",
           "-o", dest, url]
    if tty:
        cmd.insert(2, "--progress-bar")
    return subprocess.run(cmd).returncode == 0


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path, size, sha):
    """'' when the file is `size` bytes and hashes to `sha`, else why not."""
    try:
        got = os.path.getsize(path)
    except OSError:
        return "missing"
    if got != size:
        return "%d bytes, the pin says %d" % (got, size)
    if _sha256(path) != sha:
        return "sha256 mismatch"
    return ""


def _members(tf):
    """[(member, relative path parts, a link's target inside)] for every
    member, the archive's one top directory stripped; VoiceError on the
    first one that may not land: an absolute path, a `..`, a link
    pointing out, a device or a fifo."""
    rows = []
    for m in tf.getmembers():
        name = m.name.replace("\\", "/")
        bits = [b for b in name.split("/") if b not in ("", ".")]
        if name.startswith("/") or ".." in bits:
            raise VoiceError("the archive holds %s, a path outside it -- nothing unpacked" % m.name)
        if not (m.isfile() or m.isdir() or m.issym() or m.islnk()):
            raise VoiceError("the archive holds %s, neither a file nor a directory -- nothing unpacked" % m.name)
        rows.append((m, bits))
    tops = {bits[0] for _m, bits in rows if bits}
    strip = 1 if len(tops) == 1 and any(len(bits) > 1 for _m, bits in rows) else 0
    out = []
    for m, bits in rows:
        rel, where = bits[strip:], ""
        if not rel:
            continue
        if m.issym() or m.islnk():
            link = m.linkname.replace("\\", "/")
            if m.issym():
                where = os.path.normpath(os.path.join(*(rel[:-1] or ["."]), link))
            else:
                lb = [b for b in link.split("/") if b not in ("", ".")]
                where = os.path.normpath(os.path.join(*(lb[strip:] or ["."])))
            if link.startswith("/") or where == ".." or where.startswith("../") or os.path.isabs(where):
                raise VoiceError("the archive's link %s points out of it -- nothing unpacked" % m.name)
        out.append((m, rel, where))
    return out


def unpack(tarpath, dest):
    """Unpack a verified tarball into dest (made fresh), member by member,
    every member checked first: nothing lands unless all of it may."""
    with tarfile.open(tarpath, "r:*") as tf:
        rows = _members(tf)
        os.makedirs(dest, mode=0o755)
        real = os.path.realpath(dest)
        for m, rel, where in rows:
            path = os.path.join(dest, *rel)
            parent = os.path.realpath(os.path.dirname(path))
            if parent != real and not parent.startswith(real + os.sep):
                raise VoiceError("the archive's %s lands outside it -- nothing kept" % m.name)
            if m.isdir():
                os.makedirs(path, mode=0o755, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
            if m.issym():
                os.symlink(m.linkname, path)
            elif m.islnk():
                shutil.copyfile(os.path.join(dest, where), path)
            else:
                src = tf.extractfile(m)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o755 if m.mode & 0o111 else 0o644)
                with os.fdopen(fd, "wb") as f:
                    shutil.copyfileobj(src, f, 1 << 20)


def _install(part, part_file):
    """A verified download into its place: the old one moved aside, the
    new one renamed in, the sha file written last."""
    d = voice_dir()
    target = _target(part)
    fresh = os.path.join(d, "." + part["name"] + ".new")
    shutil.rmtree(fresh, ignore_errors=True)
    if part["kind"] == "tar":
        try:
            unpack(part_file, fresh)
        except (tarfile.TarError, OSError, EOFError) as e:
            shutil.rmtree(fresh, ignore_errors=True)
            raise VoiceError("%s did not unpack (%s) -- nothing kept" % (part["name"], e))
        except VoiceError:
            shutil.rmtree(fresh, ignore_errors=True)
            raise
        os.remove(part_file)
        old = os.path.join(d, "." + part["name"] + ".old")
        shutil.rmtree(old, ignore_errors=True)
        if os.path.exists(target):
            os.rename(target, old)
        os.rename(fresh, target)
        shutil.rmtree(old, ignore_errors=True)
    else:
        os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
        os.chmod(part_file, 0o644)
        os.replace(part_file, target)
    fd = os.open(os.path.join(d, part["name"] + ".sha"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    with os.fdopen(fd, "w") as f:
        f.write(part["sha"] + "\n")


def fetch(cfg=None, p=None, out=say):
    """Download what is missing, each part checked (size, then sha256)
    before it is unpacked, and installed atomically. The names fetched;
    VoiceError on the first that fails, its partial file removed."""
    if not IS_MAC and is_musl():
        raise VoiceError("musl libc: the pinned voice runtime is a glibc build")
    todo = missing(p)
    if not todo:
        return []
    for part in todo:
        if not part["url"]:
            raise VoiceError("no pinned voice runtime for %s %s" % (platform.system(), platform.machine()))
    d = voice_dir()
    os.makedirs(d, mode=0o755, exist_ok=True)
    done = []
    for part in todo:
        partial = os.path.join(d, "." + part["name"] + ".part")
        out("       downloading %s (%d MB)" % (os.path.basename(part["url"]), _mb(part["size"])))
        try:
            if not _download(part["url"], partial):
                raise VoiceError("could not download %s (nothing left behind)" % os.path.basename(part["url"]))
            why = verify(partial, part["size"], part["sha"])
            if why:
                raise VoiceError("%s: %s -- refused, nothing kept" % (os.path.basename(part["url"]), why))
            _install(part, partial)
        finally:
            if os.path.exists(partial):
                os.remove(partial)
        done.append(part["name"])
    return done


def remove():
    """Delete the voice directory whole; the bytes it held."""
    stop()
    d = voice_dir()
    total = 0
    for root, _dirs, files in os.walk(d):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    shutil.rmtree(d, ignore_errors=True)
    return total


# ---------------------------------------------------------------- recipe
def _unit(seed, salt):
    """A number in [0, 1) made the same way from the same seed every time."""
    h = hashlib.sha256(("%s:%s" % (seed, salt)).encode("utf-8", "replace")).digest()
    return int.from_bytes(h[:8], "big") / float(1 << 64)


def _fmt(key, v):
    return str(int(round(v))) if key in INT_KEYS else ("%.4f" % v).rstrip("0").rstrip(".")


def _register(sid):
    name = SPEAKERS.get(sid, "")
    return "m" if name[1:2] == "m" else "f"


def mint(temper, seed):
    """The machine's voice from its temperament and a seed: the family,
    a Kokoro speaker from the family's list (and the Portuguese one of
    the same register), and the chain's numbers jittered by the seed.
    Strings, KEY=value-ready; the same (temper, seed), the same recipe."""
    family = TEMPER_FAMILY.get(temper, "radio")
    sids = FAMILY_SIDS[family]
    sid = sids[int(_unit(seed, family + ":sid") * len(sids))]
    r = {"FAMILY": family, "SID": str(sid), "SID_PT": str(PT_SIDS[_register(sid)])}
    for key, base, span in RECIPES[family]:
        r[key] = _fmt(key, base + span * (2 * _unit(seed, family + ":" + key) - 1))
    return r


def _checked(raw):
    """A recipe fit to use: a known family, speakers in Kokoro's table,
    every number of its chain, clamped to its range. None when not."""
    family = raw.get("FAMILY", "")
    if family not in RECIPES:
        return None
    out = {"FAMILY": family}
    for key in ("SID", "SID_PT"):
        v = raw.get(key, "")
        if not v.isdigit() or int(v) > SID_MAX:
            return None
        out[key] = str(int(v))
    for key, base, span in RECIPES[family]:
        try:
            v = float(raw.get(key, ""))
        except ValueError:
            return None
        if v != v:          # NaN
            return None
        out[key] = _fmt(key, min(base + span, max(base - span, v)))
    return out


def read_recipe(path=None):
    """The voice spark awaken kept (~/.config/spark/voice), checked; None
    when there is none or it does not hold a usable one."""
    raw = {}
    try:
        with open(path or RECIPE_FILE, encoding="utf-8", errors="replace") as f:
            for line in f.read().splitlines():
                key, sep, val = line.partition("=")
                if sep and re.match(r"^[A-Z_0-9]+$", key):
                    raw[key] = val.strip()
    except OSError:
        return None
    return _checked(raw)


def write_recipe(recipe, path=None):
    """The recipe as KEY=value lines, 0600, atomically."""
    r = _checked(recipe)
    if r is None:
        raise VoiceError("not a voice recipe")
    keys = ["FAMILY", "SID", "SID_PT"] + [k for k, _b, _s in RECIPES[r["FAMILY"]]]
    path = path or RECIPE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("".join("%s=%s\n" % (k, r[k]) for k in keys))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return r


def describe(recipe):
    """`radio, Kokoro af_heart` for a recipe."""
    sid = int(recipe["SID"])
    return "%s, Kokoro %s" % (recipe["FAMILY"], SPEAKERS.get(sid, "speaker %d" % sid))


# -------------------------------------------------------------- the chains
def _read_wav(path):
    """(samples in [-1, 1], rate) from a 16-bit PCM wav; stereo is averaged."""
    with wave.open(path, "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        data = w.readframes(n)
    if width != 2:
        raise VoiceError("a %d-bit wav: the characters read 16-bit" % (8 * width))
    a = array.array("h")
    a.frombytes(data)
    if sys.byteorder == "big":
        a.byteswap()
    if ch > 1:
        return [sum(a[i:i + ch]) / (ch * 32768.0) for i in range(0, len(a) - ch + 1, ch)], rate
    return [v / 32768.0 for v in a], rate


def _write_wav(path, x, rate):
    """16-bit mono PCM, the peak at 0.89 of full scale, 0600."""
    peak = max((abs(v) for v in x), default=0.0)
    k = 0.89 / peak if peak > 1e-9 else 1.0
    a = array.array("h", (max(-32767, min(32767, int(round(v * k * 32767)))) for v in x))
    if sys.byteorder == "big":
        a.byteswap()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        w = wave.open(f, "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(a.tobytes())
        w.close()
    return path


def _norm(x):
    peak = max((abs(v) for v in x), default=0.0)
    return [v / peak for v in x] if peak > 1e-9 else list(x)


def _at(x, pos):
    """x at a fractional position, linear between samples; 0 outside."""
    i = int(math.floor(pos))
    if i < 0 or i >= len(x):
        return 0.0
    f = pos - i
    b = x[i + 1] if i + 1 < len(x) else 0.0
    return x[i] + (b - x[i]) * f


def _radio(x, fs, r, seed):
    """RBJ band-pass (constant 0 dB peak), a tanh drive, a faint hiss."""
    f0, q, drive, hiss = float(r["FREQ"]), float(r["Q"]), float(r["DRIVE"]), float(r["HISS"])
    w0 = 2 * math.pi * f0 / fs
    alpha = math.sin(w0) / (2 * q)
    a0 = 1 + alpha
    b0, b2 = alpha / a0, -alpha / a0
    a1, a2 = -2 * math.cos(w0) / a0, (1 - alpha) / a0
    y, x1, x2, y1, y2 = [], 0.0, 0.0, 0.0, 0.0
    for v in x:
        o = b0 * v + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, v, y1, o
        y.append(o)
    y = _norm(y)
    t = math.tanh(drive)
    rng = random.Random(seed)
    return [math.tanh(drive * v) / t + hiss * (2 * rng.random() - 1) for v in y]


def _choir(x, fs, r, seed):
    """Three voices -- the dry one and two that drift a few ms behind it
    -- then a slow ring, half wet: a soft robot choir."""
    depth, rate, ring, wet = float(r["DEPTH"]), float(r["RATE"]), float(r["RING"]), float(r["WET"])
    voices = ((20.0, rate, 0.0), (28.0, rate * 1.37, 1.9))
    ms = fs / 1000.0
    w = 2 * math.pi / fs
    y = []
    for n, v in enumerate(x):
        s = v
        for base, hz, phase in voices:
            s += _at(x, n - (base + depth * math.sin(w * hz * n + phase)) * ms)
        y.append(s / 3.0 * ((1 - wet) + wet * math.sin(w * ring * n)))
    return y


def _eightbit(x, fs, r, seed):
    """Faster and higher (resampled), each sample held, few bits."""
    speed, hold, bits = float(r["SPEED"]), int(r["HOLD"]), int(r["BITS"])
    n = int(len(x) / speed)
    y = _norm([_at(x, i * speed) for i in range(n)])
    levels = float(2 ** (bits - 1) - 1)
    out, cur = [], 0.0
    for i, v in enumerate(y):
        if i % hold == 0:
            cur = round(v * levels) / levels
        out.append(cur)
    return out


def _robot(x, fs, r, seed):
    """A ring fully wet into a short comb that feeds back on itself."""
    ring, comb, fb = float(r["RING"]), float(r["COMB"]), float(r["FEEDBACK"])
    d = max(1, int(round(comb * fs / 1000.0)))
    w = 2 * math.pi * ring / fs
    y = []
    for n, v in enumerate(x):
        o = v * math.sin(w * n)
        if n >= d:
            o += fb * y[n - d]
        y.append(o)
    return y


CHAINS = {"radio": _radio, "choir": _choir, "eightbit": _eightbit, "robot": _robot}


def character(wav_in, recipe, wav_out=None):
    """The recipe's chain over a 16-bit wav: a new wav, 0600, the same rate."""
    r = _checked(recipe)
    if r is None:
        raise VoiceError("not a voice recipe")
    x, fs = _read_wav(wav_in)
    seed = int.from_bytes(hashlib.sha256(json.dumps(r, sort_keys=True).encode()).digest()[:8], "big")
    y = CHAINS[r["FAMILY"]](x, fs, r, seed)
    out = wav_out or re.sub(r"(\.wav)?$", "-character.wav", wav_in, count=1)
    return _write_wav(out, y, fs)


# --------------------------------------------------------------- speaking
def mode(cfg=None):
    """off | on | clear: SPARK_VOICE, anything else is off."""
    cfg = cfg or config.load()
    v = cfg.get("SPARK_VOICE", "off").strip().lower()
    return v if v in MODES else "off"


def rate(cfg=None):
    """The clear voice's speed, RATE_MIN..RATE_MAX, 100 as made."""
    cfg = cfg or config.load()
    try:
        n = int(cfg.get("SPARK_VOICE_RATE", str(RATE_DEFAULT)))
    except ValueError:
        return RATE_DEFAULT
    return n if RATE_MIN <= n <= RATE_MAX else RATE_DEFAULT


def lang_of(text):
    """"pt" or "en": the words only Portuguese writes and its marked
    letters, against the words only English does. A small heuristic,
    for a reply's text; a spoken question carries Whisper's own."""
    words = re.findall(r"[^\W\d_]+", (text or "").lower())
    pt = sum(1 for w in words if w in PT_WORDS) + len(PT_LETTERS.findall(text or ""))
    en = sum(1 for w in words if w in EN_WORDS)
    return "pt" if pt > en else "en"


def _speakable(text):
    """The text as one line the engine may read: controls out, spaces
    folded, cut at a word near SPEAK_MAX. It rides after `--`, the end
    of the engine's options, so a text starting with a dash is words."""
    t = "".join(c if (c >= " " and not ("\x7f" <= c <= "\x9f")) else " " for c in text or "")
    t = " ".join(t.split())
    if len(t) > SPEAK_MAX:
        t = t[:SPEAK_MAX].rsplit(" ", 1)[0]
    return t


def speak(cfg, text, mode_="clear", lang=None, recipe=None):
    """The text as a wav (its path, 0600, in a private 0700 directory the
    caller removes with cleanup()): Kokoro through the runtime. "on" runs
    the machine's character over it (recipe, else the one kept); "clear"
    is the plain voice at SPARK_VOICE_RATE."""
    cfg = cfg or config.load()
    t = _speakable(text)
    if not t:
        raise VoiceError("nothing to say")
    pt = (lang or lang_of(t)).lower().startswith("pt")
    scale = 1.0
    if mode_ == "on":
        recipe = _checked(recipe) if recipe else read_recipe()
        if recipe is None:
            raise VoiceError("this machine has no voice of its own yet -- spark awaken, or spark voice clear")
        sid = int(recipe["SID_PT" if pt else "SID"])
    else:
        sid = CLEAR_SID_PT if pt else CLEAR_SID
        scale = 100.0 / rate(cfg)
    tts = _bin("sherpa-onnx-offline-tts")
    mouth = os.path.join(voice_dir(), "mouth")
    if not (os.access(tts, os.X_OK) and os.path.isdir(mouth)):
        raise VoiceError("the voice engine is not here -- spark voice %s fetches it" % ("on" if mode_ == "on" else "clear"))
    d = _private_dir()
    raw = os.path.join(d, "voice.wav")
    cmd = [tts, "--kokoro-model=model.int8.onnx", "--kokoro-voices=voices.bin", "--kokoro-tokens=tokens.txt",
           "--kokoro-data-dir=espeak-ng-data", "--kokoro-dict-dir=dict",
           "--kokoro-lexicon=lexicon-us-en.txt,lexicon-zh.txt", "--kokoro-lang=" + ("pt-br" if pt else "en-us"),
           "--kokoro-length-scale=%.3f" % scale, "--num-threads=%d" % THREADS, "--sid=%d" % sid,
           "--output-filename=" + raw, "--", t]
    try:
        p = subprocess.run(cmd, cwd=mouth, env=_lib_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=SPEAK_TIMEOUT, preexec_fn=_umask)
    except (OSError, subprocess.TimeoutExpired) as e:
        cleanup(d)
        raise VoiceError("the voice engine did not answer (%s)" % e.__class__.__name__)
    if p.returncode != 0 or not os.path.isfile(raw):
        cleanup(d)
        raise VoiceError("the voice engine did not speak (exit %d)" % p.returncode)
    os.chmod(raw, 0o600)
    if mode_ != "on":
        return raw
    try:
        out = character(raw, recipe, os.path.join(d, "character.wav"))
    except (VoiceError, OSError, EOFError, wave.Error) as e:
        cleanup(d)
        raise VoiceError("the character did not run (%s)" % e)
    os.remove(raw)
    return out


# ---------------------------------------------------------------- playing
def player(cfg=None):
    """The OS's own player as argv, or None: afplay on macOS; aplay on
    Linux (-D SPARK_VOICE_DEVICE when set), else paplay."""
    if IS_MAC:
        return ["afplay"] if shutil.which("afplay") else None
    if shutil.which("aplay"):
        dev = (cfg or config.load()).get("SPARK_VOICE_DEVICE", "")
        return ["aplay", "-q"] + (["-D", dev] if dev else [])
    return ["paplay"] if shutil.which("paplay") else None


class Playing:
    """One wav playing: wait() for it, stop() it. The player runs in its
    own session under a small sh that removes the wav's private
    directory when it ends, so a wav never outlives its playing."""

    def __init__(self, proc, tmp):
        self.proc, self.tmp = proc, tmp

    def done(self):
        return self.proc.poll() is not None

    def wait(self, timeout=None):
        try:
            return self.proc.wait(timeout)
        finally:
            if self.done():
                _forget(self)

    def stop(self):
        if not self.done():
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                self.proc.wait(2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except OSError:
                    pass
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
        _forget(self)


_PLAYING = []


def _forget(h):
    if h in _PLAYING:
        _PLAYING.remove(h)
    try:
        with open(PLAYING_FILE, encoding="utf-8") as f:
            pid = f.read().split()[0]
        if pid == str(h.proc.pid):
            os.remove(PLAYING_FILE)
    except (OSError, IndexError):
        pass


def play(cfg, wav, wait=True):
    """Play a wav through the OS's player. wait=False returns at once;
    the handle's stop() (or stop()) ends it. VoiceError when nothing can
    play. A wav in speak()'s private directory goes with the playing."""
    argv = player(cfg)
    if not argv:
        raise VoiceError("no player on PATH (afplay on macOS, aplay or paplay on Linux)")
    tmp = os.path.dirname(os.path.abspath(wav))
    tmp = tmp if _ours(tmp) else ""
    env = dict(os.environ, SPARK_VOICE_TMP=tmp)
    proc = subprocess.Popen(["sh", "-c", '"$@"; [ -z "$SPARK_VOICE_TMP" ] || rm -rf -- "$SPARK_VOICE_TMP"', "sh"]
                            + argv + [wav], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    h = Playing(proc, tmp)
    _PLAYING.append(h)
    try:
        os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
        fd = os.open(PLAYING_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("%d %s\n" % (proc.pid, tmp))
    except OSError:
        pass
    if wait:
        try:
            h.wait()
        except KeyboardInterrupt:
            h.stop()
            raise
    return h


def stop():
    """Stop what is playing: this process's handles, and the one another
    spark started (state/voice-playing), when that process is still a
    spark player. True when something stopped."""
    stopped = False
    for h in list(_PLAYING):
        if not h.done():
            stopped = True
        h.stop()
    try:
        with open(PLAYING_FILE, encoding="utf-8") as f:
            words = f.read().split()
    except OSError:
        return stopped
    pid = int(words[0]) if words and words[0].isdigit() else 0
    tmp = words[1] if len(words) > 1 and _ours(words[1]) else ""
    if pid > 1:
        try:
            out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                                 timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        if "SPARK_VOICE_TMP" in out or "spark-voice-" in out:
            try:
                os.killpg(pid, signal.SIGTERM)
                stopped = True
            except OSError:
                pass
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    try:
        os.remove(PLAYING_FILE)
    except OSError:
        pass
    return stopped


def anyway():
    """The person chose `spark voice clear --anyway`: clear speaks beside a screen reader."""
    return os.path.exists(ANYWAY_FILE)


def say_aloud(cfg, text, wait=False):
    """The text aloud in the current mode: speak, the character or the
    clear voice, then play. A handle (stop() ends it) or None: off, a
    screen reader running in clear mode, or any failure -- never a raise;
    a failure says one line on stderr, at a terminal only."""
    try:
        cfg = cfg or config.load()
        m = mode(cfg)
        if m == "off" or not (text or "").strip():
            return None
        if m == "clear" and screen_reader() and not anyway():
            return None
        stop()
        wav = speak(cfg, text, m)
        try:
            return play(cfg, wav, wait=wait)
        except Exception:
            cleanup(wav)
            raise
    except Exception as e:  # noqa: BLE001 -- the voice never breaks the verb it speaks for
        try:
            if sys.stderr.isatty():
                sys.stderr.write("%s voice -- %s\n" % (MARK, e if isinstance(e, VoiceError) else e.__class__.__name__))
        except (OSError, ValueError):
            pass
        return None


# -------------------------------------------------------------- listening
def mic_tool():
    """The runtime's listener: argv without the device, or None."""
    name = "sherpa-onnx-vad-microphone" if IS_MAC else "sherpa-onnx-vad-alsa"
    tool = _bin(name)
    return [tool] if os.access(tool, os.X_OK) else None


def listen(cfg=None, max_seconds=15):
    """One spoken question: (text, lang), ("", "") when nothing was heard
    within max_seconds. The listener records until a pause into a 0700
    directory; Whisper reads the segment; the directory goes before this
    returns, always. VoiceError when the engine is not here."""
    cfg = cfg or config.load()
    tool = mic_tool()
    vad = os.path.join(voice_dir(), "vad", "silero_vad.onnx")
    ears = os.path.join(voice_dir(), "ears")
    asr = _bin("sherpa-onnx-offline")
    if not tool or not os.path.isfile(vad) or not os.path.isdir(ears) or not os.access(asr, os.X_OK):
        raise VoiceError("the voice engine is not here -- spark voice on or clear fetches it")
    d = _private_dir()
    try:
        argv = tool + ["--silero-vad-model=" + vad, "--silero-vad-min-silence-duration=%.2f" % SILENCE,
                       "--silero-vad-max-speech-duration=%d" % max_seconds]
        if not IS_MAC:
            argv.append(cfg.get("SPARK_VOICE_DEVICE", "") or "default")
        seg = _record(argv, d, max_seconds)
        if not seg:
            return "", ""
        os.chmod(seg, 0o600)
        try:
            p = subprocess.run([asr, "--whisper-encoder=" + os.path.join(ears, "base-encoder.int8.onnx"),
                                "--whisper-decoder=" + os.path.join(ears, "base-decoder.int8.onnx"),
                                "--tokens=" + os.path.join(ears, "base-tokens.txt"), "--whisper-task=transcribe",
                                "--num-threads=%d" % THREADS, seg],
                               cwd=d, env=_lib_env(), stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               errors="replace", timeout=LISTEN_TIMEOUT, preexec_fn=_umask)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise VoiceError("the ears did not answer (%s)" % e.__class__.__name__)
        for line in p.stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    got = json.loads(line)
                except ValueError:
                    continue
                return " ".join(str(got.get("text", "")).split()), str(got.get("lang", "") or "")
        return "", ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _record(argv, d, max_seconds):
    """Run the listener in d until it saves its first segment (its
    `Saved to NAME` line on stderr) or max_seconds pass; the segment's
    path, or ''. The listener is stopped either way."""
    try:
        proc = subprocess.Popen(argv, cwd=d, env=_lib_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, start_new_session=True, preexec_fn=_umask)
    except OSError as e:
        raise VoiceError("the listener did not start (%s)" % e)
    end = time.time() + max_seconds + SILENCE + 1
    buf, seg = b"", ""
    try:
        while not seg and time.time() < end:
            ready = select.select([proc.stderr], [], [], max(0.0, min(0.25, end - time.time())))[0]
            if not ready:
                if proc.poll() is not None:
                    break
                continue
            chunk = os.read(proc.stderr.fileno(), 4096)
            if not chunk:
                break
            buf += chunk
            for line in buf.decode("utf-8", "replace").splitlines():
                m = re.match(r"^Saved to (seg-[0-9]+-[0-9.]+s\.wav)\s*$", line.strip())
                if m and os.path.isfile(os.path.join(d, m.group(1))):
                    seg = os.path.join(d, m.group(1))
                    break
    finally:
        if proc.poll() is None:
            for sig in (signal.SIGINT, signal.SIGKILL):
                try:
                    os.killpg(proc.pid, sig)
                except OSError:
                    pass
                try:
                    proc.wait(2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        proc.stderr.close()
    return seg


# ------------------------------------------------------- reading commands
def _option(tok):
    """`-ah` as `dash a h`, `--all` as `dash dash all`; None when tok is
    not an option."""
    m = re.match(r"^(--?)([A-Za-z0-9][\w=-]*)$", tok)
    if not m:
        return None
    dash = "dash dash" if m.group(1) == "--" else "dash"
    word = m.group(2)
    if m.group(1) == "-" and len(word) <= 3 and word.isalpha():
        return "%s %s" % (dash, " ".join(word))
    return "%s %s" % (dash, word.replace("-", " dash "))


_PIECE = re.compile("|".join(re.escape(s) for s, _w in SYMBOL_WORDS) + r"|[^\s%s]+" % re.escape(
    "".join(sorted({c for s, _w in SYMBOL_WORDS for c in s}))))


def spoken_command(command):
    """A shell command as clear mode reads it, every symbol by name:
    `du -ah ~ | sort -rh` is "du, dash a h, tilde, pipe, sort, dash r h"."""
    words = dict(SYMBOL_WORDS)
    out = []
    for tok in (command or "").split():
        opt = _option(tok)
        if opt:
            out.append(opt)
            continue
        said = [words.get(p, p) for p in _PIECE.findall(tok)]
        if said:
            out.append(" ".join(said))
    return ", ".join(out)


# --------------------------------------------------------- screen readers
def screen_reader(mac=None):
    """The screen reader running, or '': VoiceOver on macOS (its defaults
    key), Orca (a process) or speakup (its kernel module) on Linux.
    SPARK_PROC_DIR and SPARK_SYS_MODULE are the tests' seams."""
    if IS_MAC if mac is None else mac:
        try:
            out = subprocess.run(["defaults", "read", "com.apple.universalaccess", "voiceOverOnOffKey"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            out = ""
        return "VoiceOver" if out == "1" else ""
    proc = os.environ.get("SPARK_PROC_DIR", "/proc")
    try:
        pids = [n for n in os.listdir(proc) if n.isdigit()]
    except OSError:
        pids = []
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "comm"), encoding="utf-8", errors="replace") as f:
                if f.read().strip() == "orca":
                    return "Orca"
        except OSError:
            continue
    if os.path.isdir(os.path.join(os.environ.get("SPARK_SYS_MODULE", "/sys/module"), "speakup")):
        return "speakup"
    return ""


# ------------------------------------------------------------------ state
def _capture():
    """Linux: whether ALSA lists a capture device (/proc/asound/pcm)."""
    try:
        with open(os.path.join(os.environ.get("SPARK_PROC_DIR", "/proc"), "asound", "pcm"), encoding="utf-8") as f:
            return "capture" in f.read()
    except OSError:
        return False


def status(cfg=None, repo=None):
    """What `spark voice` and the check row say: a dict of the facts."""
    cfg = cfg or config.load()
    p = pins(repo)
    ps = parts(p)
    gone = [x for x in ps if not installed(x)]
    recipe = read_recipe()
    play_ = player(cfg)
    return {"mode": mode(cfg), "rate": rate(cfg), "pinned": all(x["url"] for x in ps),
            "missing": [x["name"] for x in gone], "missing_mb": _mb(sum(x["size"] for x in gone)),
            "recipe": recipe, "player": play_[0] if play_ else "", "mic": bool(mic_tool()),
            "capture": True if IS_MAC else _capture(), "reader": screen_reader(), "anyway": anyway()}


# ------------------------------------------------------------------- verb
def _tilde(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


def _set(**kv):
    from . import site
    site.set_keys(_file=SPARK_ENV, _quiet=True, **kv)


def _no_apply():
    return bool(os.environ.get("SPARK_NO_APPLY"))


def _fetch_said(cfg):
    """fetch() with the size said first; True when the engine is here."""
    gone = missing()
    if not gone:
        return True
    say("the voice engine: %d MB to download into %s" % (_mb(sum(x["size"] for x in gone)), _tilde(voice_dir())))
    try:
        fetch(cfg)
    except VoiceError as e:
        say("%s voice -- %s" % (MARK, e))
        return False
    return True


def show(cfg=None):
    cfg = cfg or config.load()
    s = status(cfg)
    hint = {"off": "spark voice clear reads aloud; spark voice on, in its own voice",
            "clear": "the plain clear voice", "on": "this machine's own voice"}[s["mode"]]
    say("%-7s %-6s %s" % ("voice", s["mode"], hint))
    if not s["pinned"]:
        say("%-7s %s" % ("engine", "no pinned runtime for %s %s" % (platform.system(), platform.machine())))
    elif s["missing"]:
        say("%-7s %s" % ("engine", "not here -- %d MB, fetched by spark voice on or clear" % s["missing_mb"]))
    else:
        say("%-7s %s" % ("engine", "here, %s" % _tilde(voice_dir())))
    r = s["recipe"]
    say("%-7s %s" % ("own", describe(r) + " -- spark awaken chose it" if r else "none -- spark awaken chooses one"))
    say("%-7s %s" % ("player", s["player"] or "none on PATH -- nothing can be heard"))
    mic = "the engine's listener" if s["mic"] else "with the engine"
    if IS_MAC:
        mic += " -- the terminal asks once for the microphone"
    elif not s["capture"]:
        mic += " -- no capture device found"
    say("%-7s %s" % ("mic", mic))
    if s["reader"]:
        say("%-7s %s" % ("reader", "%s is running: clear stays silent%s" % (
            s["reader"], " -- unless --anyway, which you chose" if s["anyway"] else "")))
    say("%-7s %-6d %s" % ("rate", s["rate"], "the clear voice's speed (spark voice rate N)"))
    return 0


def _test_line(cfg, m):
    if m == "on":
        from . import words
        hello = words.load().get("hello", "") or "I am awake."
        return hello.replace("{name}", cfg.name)
    return "This is how spark reads aloud."


def cmd_voice(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(VOICE_USAGE.rstrip())
        return 0
    cfg = config.load()
    if not args or args[0] == "status":
        return show(cfg)
    word, rest = args[0].lower(), args[1:]
    if word == "on" and not rest:
        from . import look
        if not look.awake():
            say("%s voice -- on speaks in this machine's own voice, and it has none before spark awaken -- "
                "spark awaken, or spark voice clear" % MARK)
            return 1
        r = read_recipe()
        if r is None:
            from . import awaken, words
            r = write_recipe(mint(words.temper(), awaken._seed(cfg)))
            say("its own voice: %s, from its temperament" % describe(r))
        if not _no_apply() and not _fetch_said(cfg):
            return 1
        _set(SPARK_VOICE="on")
        say("the voice is on -- spark voice test plays it")
        return 0
    if word == "clear" and rest in ([], ["--anyway"]):
        forced = rest == ["--anyway"]
        reader = screen_reader()
        if reader and not forced:
            say("%s voice -- %s is running and reads for you, so spark stays silent -- "
                "spark voice clear --anyway speaks too" % (MARK, reader))
            return 1
        if not _no_apply() and not _fetch_said(cfg):
            return 1
        _set(SPARK_VOICE="clear")
        _flag(forced)
        say("the voice is clear -- spark voice test plays it")
        return 0
    if word == "off" and rest in ([], ["--remove"]):
        _set(SPARK_VOICE="off")
        _flag(False)
        stop()
        if rest:
            if _no_apply():
                say("the voice is off -- %s would go" % _tilde(voice_dir()))
                return 0
            freed = remove()
            say("the voice is off -- %s removed, %d MB" % (_tilde(voice_dir()), _mb(freed)))
            return 0
        say("the voice is off -- spark voice off --remove deletes the engine too")
        return 0
    if word == "rate" and len(rest) <= 1:
        if not rest:
            say("rate %d -- the clear voice's speed, %d to %d" % (rate(cfg), RATE_MIN, RATE_MAX))
            return 0
        n = int(rest[0]) if rest[0].isdigit() else 0
        if not RATE_MIN <= n <= RATE_MAX:
            say("%s voice -- the rate is a number, %d to %d" % (MARK, RATE_MIN, RATE_MAX))
            return 2
        _set(SPARK_VOICE_RATE=str(n))
        say("rate %d now -- the clear voice's speed" % n)
        return 0
    if word == "test" and not rest:
        m = mode(cfg)
        if m == "off":
            say("%s voice -- the voice is off -- spark voice clear, or spark voice on" % MARK)
            return 1
        line = _test_line(cfg, m)
        say("* " + line)
        if _no_apply():
            return 0
        try:
            wav = speak(cfg, line, m)
            try:
                play(cfg, wav, wait=True)
            finally:
                cleanup(wav)
        except VoiceError as e:
            say("%s voice -- %s" % (MARK, e))
            return 1
        return 0
    if len(args) > 1 or args[-1].endswith("?"):
        # `spark voice of reason?` is a question
        from . import cli
        return cli.main(["voice"] + list(args))
    say("%s voice -- no word %s: spark voice on, clear, off, rate N or test" % (MARK, args[0]))
    return 2


def _flag(on):
    """state/voice-anyway: the person's --anyway, kept until clear or off."""
    try:
        if on:
            os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
            os.close(os.open(ANYWAY_FILE, os.O_WRONLY | os.O_CREAT, 0o600))
        elif os.path.exists(ANYWAY_FILE):
            os.remove(ANYWAY_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------- awaken
def audition(cfg, temper, seed, line, ask, out=say):
    """spark awaken's offer: a recipe from the temperament and the seed,
    the line spoken in it, then keep / again / none (again takes the next
    seed). What is missing of the engine is downloaded first, its size
    said and asked. The recipe kept, or None; nothing is written here."""
    gone = missing()
    if gone:
        a = ask("a voice of its own too? %d MB to download first? yes/NO: " % _mb(sum(x["size"] for x in gone)))
        if a not in ("y", "yes"):
            return None
        try:
            fetch(cfg, out=out)
        except VoiceError as e:
            out("The voice did not download: %s." % e)
            return None
    for n in range(12):
        r = mint(temper, seed if n == 0 else "%s:%d" % (seed, n))
        try:
            wav = speak(cfg, line, "on", recipe=r)
            try:
                play(cfg, wav, wait=True)
            finally:
                cleanup(wav)
        except VoiceError as e:
            out("The voice did not play: %s." % e)
            return None
        a = ask("its voice: %s. keep it? (keep, again, none): " % describe(r))
        if a in ("keep", "k", "yes", "y"):
            return r
        if a not in ("again", "a"):
            return None
    return None
