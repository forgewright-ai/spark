# spark.config -- the KEY=value reader, and the merged view of site.env +
# spark.env + environment + defaults (contract 3). Must agree with
# lib/env.sh about what a valid line is.

import os
import re
import socket
import subprocess

from . import (CONFIG_DIR, ENGINE_DIR, FORGE_TOKEN_FILE, HOME, IS_MAC, MODELS_DIR, REPO, SITE_ENV,
               SPARK_ENV, TOKEN_FILE, die)

LINE = re.compile(r"^[A-Z_0-9]+=[^;`$()|&<>]*$")
PLACEHOLDERS = {"SITE_GIT_NAME": "Your Name", "SITE_GIT_EMAIL": "you@example.com"}

# Contract 3: every key a config file may carry, in the documented order.
SITE_KEYS = ("SITE_NAME", "SITE_USER", "SITE_SET_HOSTNAME", "SITE_GIT_NAME", "SITE_GIT_EMAIL",
             "SITE_WORKSPACE", "SITE_PEER_AI_URL", "SITE_PEER_SSH", "SITE_THEME", "SITE_PROMPT",
             "SITE_PROMPT_STYLE", "SITE_AI_MODEL", "SITE_EMBER_MODEL", "SITE_AI_BUDGET", "SITE_AI_BUILD",
             "SITE_FONT_FACE", "SITE_FONT_SIZE", "SITE_QUIET_LOGIN", "SITE_QUIET_BOOT", "SITE_QUIET_START",
             "SITE_HEADLESS", "SITE_SHELL")
SPARK_KEYS = ("SPARK_PORT", "SPARK_BASE_URL", "SPARK_PREFER_URL", "SPARK_SERVE_HOST", "SPARK_ENGINE_DIR",
              "SPARK_MODELS_DIR", "SPARK_MODEL", "SPARK_NGL", "SPARK_CTX", "SPARK_FLASH_ATTN", "SPARK_KV",
              "SPARK_THREADS", "SPARK_EXTRA_ARGS", "SPARK_MEM_NEEDED_GB", "SPARK_API_KEY_FILE",
              "SPARK_TIMEOUT", "SPARK_HISTORY", "SPARK_MEMORY", "SPARK_PERSONA_EXTRA", "SPARK_SERVICE",
              "SPARK_FORGE", "SPARK_FORGE_HOST", "SPARK_FORGE_PORT", "SPARK_FORGE_TOKEN_FILE")
KEYS = SITE_KEYS + SPARK_KEYS


def parse_env(path):
    """dict of KEY -> value from a KEY=value file. Blank and # lines are
    skipped. Any other line that is not KEY=value refuses the file: config
    is data, never code. Empty values are absent. A leading ~ is expanded;
    surrounding double quotes are stripped."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    for n, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not LINE.match(line):
            die("%s:%d: not KEY=value: %s" % (path, n, line.strip()), 2)
        key, val = line.split("=", 1)
        if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
            val = val[1:-1]
        if val == "~" or val.startswith("~/"):
            val = HOME + val[1:]
        if val != "":
            out[key] = val
    return out


_HOST = []


def _short_host():
    """This machine's own short name, the one safe to bake into a rendered
    file. On macOS `hostname` is whatever the network last told configd while
    `scutil --get HostName` is unset, so it moves from network to network;
    LocalHostName is the name the owner set and does not move. lib/env.sh
    short_host() is the twin."""
    if not _HOST:
        name = ""
        if IS_MAC:
            try:
                name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True,
                                      text=True, timeout=5).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                name = ""
        _HOST.append(name or socket.gethostname().split(".")[0] or "spark")
    return _HOST[0]


class Config:
    """Lookup order: environment, then the file, then the default."""

    def __init__(self):
        self.site_file = parse_env(SITE_ENV)
        self.spark_file = parse_env(SPARK_ENV)
        self._file = {}
        self._file.update(self.site_file)
        self._file.update(self.spark_file)
        # placeholders shipped in site.env.example count as unset
        for k, v in PLACEHOLDERS.items():
            if self._file.get(k) == v:
                del self._file[k]

    def get(self, key, default=""):
        v = os.environ.get(key)
        if v:
            if v == "~" or v.startswith("~/"):
                v = HOME + v[1:]
            return v
        v = self._file.get(key)
        if v and v != PLACEHOLDERS.get(key):
            return v
        return default

    def has(self, key):
        return bool(os.environ.get(key) or self._file.get(key))

    def placeholder_left(self):
        """Names of site.env keys still holding the example placeholder."""
        return [k for k, v in PLACEHOLDERS.items() if self.site_file.get(k) == v]

    # ---- site: identity and choices ----
    @property
    def name(self):
        return self.get("SITE_NAME", _short_host())

    @property
    def user(self):
        return self.get("SITE_USER", os.environ.get("USER") or "user")

    @property
    def git_name(self):
        return self.get("SITE_GIT_NAME", self.user)

    @property
    def git_email(self):
        return self.get("SITE_GIT_EMAIL", "%s@%s" % (os.environ.get("USER") or "user", _short_host()))

    @property
    def workspace(self):
        return self.get("SITE_WORKSPACE", os.path.join(HOME, "projects"))

    @property
    def theme(self):
        return self.get("SITE_THEME", "none")

    @property
    def prompt(self):
        return self.get("SITE_PROMPT", "starship")

    @property
    def prompt_style(self):
        return self.get("SITE_PROMPT_STYLE", "minimal")

    @property
    def model_choice(self):
        return self.get("SITE_AI_MODEL", "auto")

    @property
    def ember_model(self):
        """none | auto | a name from models.env: the second, larger model
        for conversations; spark stays the small one at the prompt. The
        default is none: one model does both until `spark ember` adds one."""
        return self.get("SITE_EMBER_MODEL", "none")

    @property
    def ai_budget(self):
        """10..95: percent of RAM+GPU memory `auto` may use (default 60).
        spark model budget N sets it."""
        v = self.get("SITE_AI_BUDGET", "60")
        try:
            n = int(v)
        except ValueError:
            die("SITE_AI_BUDGET is not a number", 2)
        if not 10 <= n <= 95:
            die("SITE_AI_BUDGET must be 10..95", 2)
        return n

    @property
    def ai_build(self):
        """auto | cpu | vulkan: the Linux engine build as chosen (macOS
        ignores it: Metal). engine.backend() resolves auto by the GPU probe,
        as bootstrap.sh ai_build does."""
        return self.get("SITE_AI_BUILD", "auto")

    @property
    def font_face(self):
        return self.get("SITE_FONT_FACE", "JetBrainsMonoNFM-Regular" if IS_MAC else "")

    @property
    def font_size(self):
        return self.get("SITE_FONT_SIZE", "13" if IS_MAC else "16x32")

    @property
    def quiet_login(self):
        return self.get("SITE_QUIET_LOGIN", "no") == "yes"

    @property
    def quiet_boot(self):
        return self.get("SITE_QUIET_BOOT", "no") == "yes"

    @property
    def quiet_audio(self):
        """yes: spark plays no sound (the sounds it has are a game's and a
        bell); the audio row reads na. Both OSes; core."""
        return self.get("SITE_QUIET_AUDIO", "no") == "yes"

    @property
    def quiet_start(self):
        """yes: spark itself starts quietly -- no login banner, a one-line
        `spark serve` / `spark forge`, a one-line bare `spark` (explicit
        `spark status` stays the full report). Both OSes; core."""
        return self.get("SITE_QUIET_START", "no") == "yes"

    @property
    def headless(self):
        """yes: a box that is the brain -- the FORGE up from boot, never asleep."""
        return self.get("SITE_HEADLESS", "no") == "yes"

    @property
    def shell(self):
        """on: the shell layer is spark's -- tmux, starship, micro, the
        daily tools, the Nerd Font and the rc files. off (default): the
        AI only; the shell stays yours."""
        return self.get("SITE_SHELL", "off") == "on"

    @property
    def peer_ai_url(self):
        return self.get("SITE_PEER_AI_URL", "")

    @property
    def client(self):
        """a client: no model of its own (SITE_AI_MODEL=none) and another
        machine's FORGE or server (SITE_PEER_AI_URL) answering. Nothing runs
        here: no engine, no units; the prompt, chat and explain still do.
        spark client URL sets it, spark client off serves here again."""
        return self.model_choice.strip().lower() == "none" and bool(self.peer_ai_url)

    @property
    def peer_ssh(self):
        return self.get("SITE_PEER_SSH", "")

    # ---- spark: runtime ----
    @property
    def port(self):
        try:
            return int(self.get("SPARK_PORT", "8080"))
        except ValueError:
            die("SPARK_PORT is not a number", 2)

    @property
    def base_url(self):
        return self.get("SPARK_BASE_URL", "").rstrip("/")

    @property
    def prefer_url(self):
        return (self.get("SPARK_PREFER_URL", "") or self.peer_ai_url).rstrip("/")

    @property
    def serve_host(self):
        return self.get("SPARK_SERVE_HOST", "")

    @property
    def engine_dir(self):
        return self.get("SPARK_ENGINE_DIR", "")

    @property
    def models_dir(self):
        return self.get("SPARK_MODELS_DIR", MODELS_DIR)

    @property
    def model(self):
        return self.get("SPARK_MODEL", "")

    @property
    def ngl(self):
        return self.get("SPARK_NGL", "999")

    @property
    def ctx(self):
        return self.get("SPARK_CTX", "8192")

    @property
    def flash_attn(self):
        v = self.get("SPARK_FLASH_ATTN", "auto")
        if v not in ("auto", "on", "off"):
            die("SPARK_FLASH_ATTN must be auto, on or off", 2)
        return v

    @property
    def kv(self):
        v = self.get("SPARK_KV", "f16")
        if v not in ("f16", "q8_0", "q4_0", "bf16"):
            die("SPARK_KV must be f16, bf16, q8_0 or q4_0", 2)
        return v

    @property
    def threads(self):
        v = self.get("SPARK_THREADS", "")
        if v and not v.isdigit():
            die("SPARK_THREADS must be a number", 2)
        return v

    @property
    def extra_args(self):
        return self.get("SPARK_EXTRA_ARGS", "").split()

    @property
    def mem_needed_gb(self):
        v = self.get("SPARK_MEM_NEEDED_GB", "")
        try:
            return float(v) if v else 0.0
        except ValueError:
            die("SPARK_MEM_NEEDED_GB is not a number", 2)

    @property
    def token_file(self):
        return self.get("SPARK_API_KEY_FILE", TOKEN_FILE)

    @property
    def timeout(self):
        try:
            return float(self.get("SPARK_TIMEOUT", "20"))
        except ValueError:
            die("SPARK_TIMEOUT is not a number", 2)

    @property
    def history(self):
        """days of turns to keep; 0 means keep none."""
        v = self.get("SPARK_HISTORY", "30")
        if v.lower() in ("off", "none", "0"):
            return 0
        try:
            return int(v)
        except ValueError:
            die("SPARK_HISTORY must be a number of days or off", 2)

    @property
    def memory(self):
        """whether the remembered facts go into every request."""
        v = self.get("SPARK_MEMORY", "on")
        if v not in ("on", "off"):
            die("SPARK_MEMORY must be on or off", 2)
        return v == "on"

    @property
    def persona_extra(self):
        """deprecated: read only as the soul fallback (soul.read)."""
        return self.get("SPARK_PERSONA_EXTRA", "")[:1500]

    @property
    def service(self):
        return self.get("SPARK_SERVICE", "auto")

    # ---- the FORGE: the served agent ----
    @property
    def forge(self):
        """auto (wherever a model is served), on, or off."""
        v = self.get("SPARK_FORGE", "auto")
        if v not in ("auto", "on", "off"):
            die("SPARK_FORGE must be auto, on or off", 2)
        return v

    @property
    def forge_host(self):
        return self.get("SPARK_FORGE_HOST", "")

    @property
    def forge_port(self):
        try:
            return int(self.get("SPARK_FORGE_PORT", "8081"))
        except ValueError:
            die("SPARK_FORGE_PORT is not a number", 2)

    @property
    def forge_token_file(self):
        return self.get("SPARK_FORGE_TOKEN_FILE", FORGE_TOKEN_FILE)

    def loopback_url(self):
        return "http://127.0.0.1:%d" % self.port


def load():
    return Config()


def theme_path(name, repo=REPO):
    """The file behind a palette name: yours (`~/.config/spark/themes/
    <name>.env`) first, then the repository's `themes/<name>.env`; None
    when neither exists. lib/env.sh theme_load is the twin."""
    for d in (os.path.join(CONFIG_DIR, "themes"), os.path.join(repo, "themes")):
        path = os.path.join(d, name + ".env")
        if os.path.isfile(path):
            return path
    return None


def theme_names(repo=REPO):
    """Every palette name: the repository's and yours, sorted, each once."""
    names = set()
    for d in (os.path.join(repo, "themes"), os.path.join(CONFIG_DIR, "themes")):
        try:
            names.update(f[:-4] for f in os.listdir(d) if f.endswith(".env"))
        except OSError:
            pass
    return sorted(names)


def theme_palette(name, repo=REPO):
    """dict of THEME_* for a palette name, or None for `none`."""
    if name == "none":
        return None
    path = theme_path(name, repo)
    if path is None:
        die("SITE_THEME=%s: no such palette (themes/*.env, ~/.config/spark/themes/*.env)" % name, 2)
    pal = parse_env(path)
    # the same 21 keys lib/env.sh THEME_KEYS requires: the two validators agree
    for k in ("THEME_BG", "THEME_FG", "THEME_ACCENT", "THEME_MUTED", "THEME_BTOP") + tuple("THEME_ANSI_%d" % i for i in range(16)):
        if k not in pal:
            die("theme %s lacks %s" % (name, k), 2)
    return pal


OPEN_LICENSES = ("Apache-2.0", "MIT")     # the first word of a MODEL_*_LICENSE that auto may take (bootstrap.sh open_license is the twin)


def is_open(license_):
    """True when the license's first word is one of OPEN_LICENSES: the
    rows `auto` may pick and that download without a question."""
    return bool(license_) and license_.split()[0] in OPEN_LICENSES


def _parse_model_file(path, source):
    """[(name, file, url, bytes, sha256, ram_gb, source, tested, license,
    note)] from one KEY=value model file. Every MODEL_<NAME> row is
    exactly 5 fields (file url bytes sha256 ram_gb); anything else dies,
    naming the file (config is data, wrong data is refused). The
    side-keys are not rows: MODEL_<NAME>_LICENSE ("<name> <url>",
    required for every row), MODEL_<NAME>_TESTED ("line": the row was
    proven on the line, so auto may pick it; absent otherwise) and
    MODEL_<NAME>_NOTE (one line, optional). `source` is "repo"
    (models.env) or "user" (~/.config/spark/models.env). Missing file
    -> []."""
    kv = parse_env(path)
    base = os.path.basename(path)
    rows = []
    for k, v in kv.items():
        if not k.startswith("MODEL_") or k.endswith(("_LICENSE", "_NOTE", "_TESTED")):
            continue
        parts = v.split()
        if len(parts) != 5:
            die("%s: %s needs 5 fields: file url bytes sha256 ram_gb" % (base, k), 2)
        stem = k[6:]
        name = stem.lower().replace("_", "-")
        license_ = kv.get(k + "_LICENSE", "")
        note = kv.get(k + "_NOTE", "")
        tested = kv.get(k + "_TESTED", "") == "line"
        if not license_:
            die("%s: %s has no %s_LICENSE" % (base, k, k), 2)
        rows.append((name, parts[0], parts[1], int(parts[2]), parts[3], float(parts[4]),
                     source, tested, license_, note))
    return rows


def auto_rows(rows):
    """The rows `auto` may pick: tested on the line, open license (the
    only filter; bootstrap.sh model_rows is the twin)."""
    return [r for r in rows if r[7] and is_open(r[8])]


def models_table(repo=REPO):
    """[(name, file, url, bytes, sha256, ram_gb)] -- the rows auto reads
    (tested, open license), in file order, from models.env only."""
    return [row[:6] for row in auto_rows(_parse_model_file(os.path.join(repo, "models.env"), "repo"))]


def model_tables(repo=REPO):
    """The one list plus yours: [(name, file, url, bytes, sha256, ram_gb,
    source, tested, license, note)] from models.env ("repo") then
    ~/.config/spark/models.env ("user", when present -- yours, never in
    the repo). A name that appears in both is refused, naming both."""
    seen = {}
    out = []
    for path, source in ((os.path.join(repo, "models.env"), "repo"),
                          (os.path.join(CONFIG_DIR, "models.env"), "user")):
        for row in _parse_model_file(path, source):
            name = row[0]
            if name in seen:
                die("model %s is in both %s and %s" % (name, seen[name], path), 2)
            seen[name] = path
            out.append(row)
    return out


def default_engine_dir():
    """Where llama-server lives when SPARK_ENGINE_DIR is unset (bootstrap.sh
    engine_home is the sh twin): the newest engine/<name> directory holding
    one, then Homebrew's bin on macOS, else the pinned directory bootstrap
    fills -- so the error names where it would be."""
    try:
        names = sorted(d for d in os.listdir(ENGINE_DIR) if os.path.isdir(os.path.join(ENGINE_DIR, d)))
    except OSError:
        names = []
    for n in reversed(names):
        if os.access(os.path.join(ENGINE_DIR, n, "llama-server"), os.X_OK):
            return os.path.join(ENGINE_DIR, n)
    if IS_MAC:
        for p in ("/opt/homebrew/bin", "/usr/local/bin"):
            if os.access(os.path.join(p, "llama-server"), os.X_OK):
                return p
    return os.path.join(ENGINE_DIR, names[-1]) if names else ENGINE_DIR
