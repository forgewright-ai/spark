# spark.site -- the commands that change a site.env choice and apply it:
# `spark shell`, `spark font`, `spark bootconfig`, `spark model`,
# `spark ember`, `spark headless` (and `spark theme`, in theme.py). Each
# writes the key, then runs bootstrap.sh so the machine follows; editing
# site.env by hand and running bootstrap does the same thing.

import math
import os
import pwd
import re
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from . import CONFIG_DIR, HOME, IS_MAC, MARK, REPO, SITE_ENV, config, glyph, mem_total_gb, say


def set_keys(_file=None, _quiet=False, **kv):
    """Rewrite KEY= lines in site.env (or _file; append the missing ones);
    keep it 0600. One `ok site KEY=value` row per key unless _quiet."""
    path = _file or SITE_ENV
    lines = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        pass
    for key, val in kv.items():
        done = False
        for i, line in enumerate(lines):
            if line.startswith(key + "="):
                lines[i] = "%s=%s" % (key, val)
                done = True
        if not done:
            lines.append("%s=%s" % (key, val))
        if not _quiet:
            say("ok     %-12s %s=%s" % ("site" if path == SITE_ENV else "spark.env", key, val))
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def apply(rows, stream=False):
    """Run bootstrap.sh and show the rows that matter for this change.
    stream=True at a terminal hands bootstrap the terminal unfiltered, so
    a model download shows curl's progress bar live; captured output (a
    pipe, a script) keeps the filtered rows either way. An empty rows shows
    every row that is not ok (the non-stream branch): a caller that does
    not know which rows changed, like `spark update`, wants everything
    bootstrap did.
    SPARK_NO_APPLY=1 (tests) writes the key only."""
    if os.environ.get("SPARK_NO_APPLY"):
        return 0
    cmd = ["sh", os.path.join(REPO, "bootstrap.sh")]
    if stream and sys.stdout.isatty():
        if subprocess.run(cmd).returncode != 0:
            say("spark: bootstrap.sh failed (the output above says where)")
            return 1
    else:
        p = subprocess.run(cmd, capture_output=True, text=True)
        if rows:
            pattern = r"^(ok|would|skip|todo)\s+(%s)\b" % "|".join(rows)
            for line in p.stdout.splitlines():
                if re.match(pattern, line):
                    say(line)
        else:
            for line in p.stdout.splitlines():
                if not re.match(r"^ok\s", line):
                    say(line)
        if p.returncode != 0:
            say("spark: bootstrap.sh failed:\n" + (p.stderr or p.stdout)[-800:])
            return 1
    from . import check
    check.refresh()
    return 0


def _downloads_pending(cfg):
    """The chosen roles' model files not on disk yet: models.env rows."""
    from . import engine
    pair = engine.chosen_rows(cfg)
    out = []
    for role in engine.ROLES:
        r = pair.get(role)
        if r and not os.path.isfile(os.path.join(cfg.models_dir, r[1])):
            out.append(r)
    return out


def _announce_downloads(pend):
    """One row per pending download, before bootstrap runs: what, how big."""
    for r in pend:
        say("ok     download     %s (%.1f GB)%s" % (
            r[1], r[3] / 2**30,
            " -- curl's progress bar follows" if sys.stdout.isatty() else ""))


def shell_off(sub):
    """The guard of a shell-layer verb (bar, font, bootconfig): when the
    layer is off, say so in the signing shape and return 2; else None."""
    if config.load().shell:
        return None
    say("%s %s -- the shell layer is off (spark shell on)" % (MARK, sub))
    return 2


# ------------------------------------------------------------------- font
FONT_USAGE = """%s font -- the terminal's font

  spark font                    what is set
  spark font FACE SIZE          Linux console: Terminus|VGA|Fixed and 16x32/8x16
                                macOS: a font's PostScript name; points (13)
  spark font none               Linux: leave the console's font alone
""" % MARK


def cmd_font(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(FONT_USAGE.rstrip())
        return 0
    if shell_off("font"):
        return 2
    cfg = config.load()
    if not args:
        if IS_MAC:
            say("%s font -- Terminal.app profile: %s %s   (spark theme profile applies it)" % (MARK, cfg.font_face, cfg.font_size))
        elif cfg.font_face:
            say("%s font -- console: %s %s" % (MARK, cfg.font_face, cfg.font_size))
        else:
            say("%s font -- console: not managed (SITE_FONT_FACE unset)" % MARK)
        return 0
    if args[0] == "none":
        set_keys(SITE_FONT_FACE="", SITE_FONT_SIZE="")
        say("the console keeps whatever font it has now")
        return 0
    if len(args) != 2:
        say(FONT_USAGE.rstrip())
        return 2
    face, size = args
    if IS_MAC:
        if not re.match(r"^\d+(\.\d+)?$", size):
            say("spark font: %s is not a size -- points on macOS, e.g. 13" % size)
            return 2
    elif not re.match(r"^\d+x\d+$", size):
        say("spark font: %s is not a size -- WxH on the Linux console, e.g. 16x32" % size)
        return 2
    set_keys(SITE_FONT_FACE=face, SITE_FONT_SIZE=size)
    if IS_MAC:
        from . import theme
        return theme.profile(config.load(), False)
    return apply(["console", "font"])


# ------------------------------------------------------------- bootconfig
BOOT_USAGE = """%s bootconfig -- how the machine boots and logs in (Linux)

  spark bootconfig              what is set
  spark bootconfig quiet        no distro notice, no kernel line, no GRUB menu
  spark bootconfig loud         all of them back (Debian's defaults)
  spark bootconfig login yes|no
  spark bootconfig boot yes|no
""" % MARK


def cmd_bootconfig(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(BOOT_USAGE.rstrip())
        return 0
    if shell_off("bootconfig"):
        return 2
    cfg = config.load()
    if IS_MAC:
        say("%s bootconfig -- macOS has no motd and no GRUB -- nothing to set" % MARK)
        return 0
    if not args:
        say("%s bootconfig -- login %s, boot %s" % (MARK, "quiet" if cfg.quiet_login else "loud", "quiet" if cfg.quiet_boot else "loud"))
        return 0
    if args[0] == "quiet":
        set_keys(SITE_QUIET_LOGIN="yes", SITE_QUIET_BOOT="yes")
    elif args[0] == "loud":
        set_keys(SITE_QUIET_LOGIN="no", SITE_QUIET_BOOT="no")
    elif len(args) == 2 and args[0] in ("login", "boot") and args[1] in ("yes", "no"):
        set_keys(**{"SITE_QUIET_LOGIN" if args[0] == "login" else "SITE_QUIET_BOOT": args[1]})
    else:
        say(BOOT_USAGE.rstrip())
        return 2
    return apply(["quiet-login", "quiet-boot"])


# --------------------------------------------------------------- headless
HEADLESS_USAGE = """%s headless -- a machine that is the brain

  spark headless                what is set, and what is in effect here
  spark headless on             the FORGE up from boot, nobody logged in, never
                                asleep. Linux: linger, the render group, sleep
                                masked, the lid ignored. macOS: LaunchDaemons in
                                system/, pmset never sleeps, wake on LAN
  spark headless off            a workstation again (macOS: pmset untouched)
""" % MARK
HEADLESS_ROWS = ["headless", "linger", "render", "sleep", "lid", "daemons", r"spark\.(serve|forge|check)"]
SLEEP_TARGETS = ("sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target")
LOGIND_DROPIN = "/etc/systemd/logind.conf.d/spark.conf"
PMSET_WANT = (("sleep", "0"), ("disksleep", "0"), ("womp", "1"), ("autorestart", "1"))


def headless_facts(cfg):
    """What is in effect on this machine, read-only: [(piece, good, detail)].
    The check row and `spark headless` read it; bootstrap.sh changes it."""
    from . import engine, run
    facts = []
    if IS_MAC:
        for unit, wanted in (("serve", cfg.service == "auto"), ("forge", cfg.forge != "off"), ("check", True)):
            dom = engine.service_domain(cfg, unit)
            facts.append(("%s daemon" % unit, dom == "system" or not wanted,
                          "system/ (from boot)" if dom == "system" else ("gui/ (a login agent)" if engine.service_state(cfg, unit) == "loaded" else "absent")))
        rc, out = run(["pmset", "-g"], timeout=10)
        pm = {}
        for line in out.splitlines():
            f = line.split()
            if len(f) >= 2:
                pm[f[0]] = f[1]
        for key, want in PMSET_WANT:
            cur = pm.get(key)
            good = cur is None or cur == want
            facts.append(({"sleep": "never sleeps", "disksleep": "disks stay awake", "womp": "wake on LAN",
                           "autorestart": "restarts after power loss"}[key], good,
                          "pmset %s %s" % (key, cur if cur is not None else "(not on this hardware)")))
        return facts
    rc, out = run(["loginctl", "show-user", os.environ.get("USER") or cfg.user, "-p", "Linger", "--value"], timeout=10)
    facts.append(("linger", out.strip() == "yes", "units run from boot" if out.strip() == "yes" else "units stop at logout"))
    if os.path.exists("/dev/dri/renderD128"):
        rc, out = run(["id", "-nG"], timeout=10)
        member = "render" in out.split()
        facts.append(("render group", member, "the units see the GPU from boot" if member else "the GPU needs a login session"))
    masked = []
    for t in SLEEP_TARGETS:
        rc, out = run(["systemctl", "is-enabled", t], timeout=10)
        if out.strip() == "masked":
            masked.append(t)
    facts.append(("sleep masked", len(masked) == len(SLEEP_TARGETS), "%d of %d targets masked" % (len(masked), len(SLEEP_TARGETS))))
    try:
        with open(LOGIND_DROPIN, encoding="utf-8") as f:
            lid = "HandleLidSwitch=ignore" in f.read()
    except OSError:
        lid = False
    facts.append(("lid ignored", lid, LOGIND_DROPIN if lid else "no logind drop-in"))
    return facts


def cmd_headless(args):
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(HEADLESS_USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        say("%s headless -- SITE_HEADLESS=%s: %s" % (MARK, "yes" if cfg.headless else "no",
                                                    "a brain (the FORGE up from boot, never asleep)" if cfg.headless
                                                    else "a workstation (spark headless on for a brain)"))
        for piece, good, detail in headless_facts(cfg):
            say("  %s %-26s %s" % (glyph("ok") if good else ("!" if cfg.headless else glyph("na")), piece, detail))
        return 0
    if args[0] not in ("on", "off"):
        say(HEADLESS_USAGE.rstrip())
        return 2
    set_keys(SITE_HEADLESS="yes" if args[0] == "on" else "no")
    if args[0] == "off":
        os.environ["SPARK_HEADLESS_UNDO"] = "1"    # only this verb unmasks sleep and frees the lid
    return apply(HEADLESS_ROWS)


# ------------------------------------------------------------------ model
MODEL_USAGE = """%s model -- which model this machine serves

  spark model                   the table: size, RAM, downloaded, serving, tok/s
                                the spark pick marked *, the ember +, the
                                source ? community, u yours (auto is curated
                                only); spark ember list adds the ember rows
  spark model NAME              choose it: any list, by name; site.env,
                                download, server restart (a community or
                                your own row asks first, naming its license)
  spark model auto | none       auto: the largest curated row that fits
                                (smallest beside an ember); none: no model here
  spark model budget [N]        percent of RAM+GPU auto may use (10-95)
  spark model rm NAME           delete a downloaded file that is not in use
  spark model add URL           add your own: --sha256 HEX (non-HF URLs need
                                it), --license "NAME URL" (required); writes
                                ~/.config/spark/models.env, downloads it
  spark model verify            sha256 every downloaded file now; exit 1 on
                                a mismatch (spark check's models row is the
                                cached, daily version of this)
""" % MARK


def _restart_server(cfg):
    from . import engine, wire
    st = engine.service_state(cfg)
    if st == "loaded":
        if IS_MAC and engine.service_domain(cfg) == "system":
            say(engine.daemon_note(cfg))
            return
        say("ok     server       restarting -- the model loads again (about 30 s) ...")
        engine.service_stop(noreload=False)
        engine.wait_gone(engine.server_pids(cfg.port), 30)
        engine.kickstart(cfg)
        url = wire.serve_url() or cfg.loopback_url()
        end = time.time() + 180
        while time.time() < end and wire.health(url) != "ok":
            time.sleep(2)
        if wire.health(url) == "ok":
            say("ok     server       ready")
        else:
            say("todo   server       not ready yet -- spark check --watch 5 follows it")
        from . import check
        check.refresh()
    elif engine.pidfile_pid():
        from . import serve
        serve.cmd_stop([])
        serve.cmd_serve([])
    else:
        say("ok     server       not running -- the next spark serve uses it")


SOURCE_MARKS = {"curated": " ", "community": "?", "ember": "e", "user": "u"}


def model_rows(cfg, serving=None):
    """The model table as data: [{name, gb, ram_gb, fits, downloaded,
    chosen, role, serving, speed, speed_kind, source, mark, purpose,
    license, note}] in model_tables() order (curated first). `role` is
    "spark", "ember" or "" from engine.chosen_rows. `source` is "curated",
    "ember", "community" or "user"; `mark` is the second column's glyph
    (SOURCE_MARKS). `serving` is the model name a brain answers with; None
    asks the brain (the FORGE passes its own). `speed` is tok/s and
    `speed_kind` "measured" or "estimate" (engine.speed_of)."""
    from . import engine, wire
    budget = mem_total_gb() * cfg.ai_budget / 100.0
    pair = engine.chosen_rows(cfg)
    chosen = pair["spark"][1] if pair.get("spark") else ""
    role_of = {}
    for role in engine.ROLES:
        r = pair.get(role)
        if r and r[1] not in role_of:
            role_of[r[1]] = role
    if serving is None:
        serving = ""
        try:
            serving = wire.resolve_brain(cfg).model
        except wire.BrainError:
            pass
    out = []
    for row in config.model_tables():
        name, fname, _url, nbytes, _sha, ram, source, purpose, license_, note = row
        speed, kind = engine.speed_of(cfg, row)
        out.append({"name": name, "gb": round(nbytes / 2**30, 1), "ram_gb": ram, "fits": ram <= budget,
                    "downloaded": os.path.isfile(os.path.join(cfg.models_dir, fname)),
                    "chosen": fname == chosen, "role": role_of.get(fname, ""),
                    "serving": bool(serving) and fname.replace(".gguf", "") == serving,
                    "speed": speed, "speed_kind": kind, "source": source,
                    "mark": SOURCE_MARKS.get(source, " "), "purpose": purpose,
                    "license": license_, "note": note})
    return out


def model_line(r, marks=None, width=13):
    """One table row: the pick mark (spark *, ember +), the source mark
    (blank curated, `?` community, `e` embers, `u` yours), the name, the
    file size, the RAM verdict, downloaded, serving, and the speed --
    `~N tok/s` an estimate, `N tok/s` measured; nothing for a row that
    does not fit. `width` pads the name column (the caller widens it past
    13 for a longer ember name). Every row stays within 80 columns."""
    marks = marks or {"spark": "*", "ember": "+"}
    state = "serving" if r["serving"] else ("downloaded" if r["downloaded"] else "")
    speed = ("%s%d tok/s" % ("~" if r["speed_kind"] == "estimate" else "", r["speed"])) if r["fits"] else ""
    # padded columns, right-aligned numbers: the eye reads a table, not a
    # sentence; 60 + width columns, so a 16-char ember name still fits 80
    return ("  %s%s %-*s %5.1f GB file %3.0f GB RAM %-7s %-10s %9s"
            % (marks.get(r["role"], " "), r["mark"], width, r["name"], r["gb"], r["ram_gb"],
               "fits" if r["fits"] else "too big", state, speed)).rstrip()


def print_model_table(cfg, embers=False):
    """The table `spark model list` (embers=False: curated, community and
    yours -- no purpose, no ember source) and `spark ember list`
    (embers=True: the same rows plus the embers.env rows, each followed
    by its purpose line, indented) share: every row with its RAM verdict,
    the spark pick marked * and the ember pick + (the marks bootstrap.sh
    --list-models draws), a second mark naming the source, and a last
    column with the generation speed: `~N tok/s` an estimate for this
    backend, `N tok/s` measured here (spark bench, or a real turn);
    nothing for a row that does not fit. Every row stays within 80
    columns. `spark model list` ends with a line pointing at `spark ember
    list` when there is a purpose to show."""
    from . import engine
    budget = mem_total_gb() * cfg.ai_budget / 100.0
    say("%s model%sSITE_AI_MODEL=%s SITE_EMBER_MODEL=%s%s%.0f GB for models (RAM + GPU), budget %.0f GB (%d%%), %s" % (
        MARK, glyph("sep"), cfg.model_choice, cfg.ember_model, glyph("sep"), mem_total_gb(), budget, cfg.ai_budget, engine.backend(cfg)))
    note = engine.cap_note(cfg)
    if note:
        say("  " + note)
    all_rows = model_rows(cfg)
    rows = all_rows if embers else [r for r in all_rows if r["source"] != "ember"]
    width = max([13] + [len(r["name"]) for r in rows])
    for r in rows:
        say(model_line(r, width=width))
        if embers and r["source"] == "ember" and r["purpose"]:
            say("      " + r["purpose"])
    known = {row[1] for row in config.model_tables()}
    others = [f for f in os.listdir(cfg.models_dir) if f.endswith(".gguf") and f not in known] if os.path.isdir(cfg.models_dir) else []
    for f in others:
        say("    %-13s %5.1f GB file   (not in models.env; SPARK_MODEL=%s serves it)" % (
            "-", os.path.getsize(os.path.join(cfg.models_dir, f)) / 2**30, f))
    say("  * = spark (the prompt line), + = ember (conversations)")
    say("  ? = community (untested), e = embers (a purpose), u = yours")
    if not embers:
        n = sum(1 for r in all_rows if r["source"] == "ember")
        if n:
            say("  spark ember list -- %d model%s with a purpose" % (n, "" if n == 1 else "s"))
    return 0


def _license_ok(row, verb):
    """A community/user row (never curated or ember) prints its license
    line -- and its note, when there is one -- and gets a yes before the
    download: SPARK_YES=1 in the environment, or stdin not a tty (a
    script, a pipe), counts as yes without asking."""
    name, source, license_, note = row[0], row[6], row[8], row[9]
    if source not in ("community", "user"):
        return True
    say("%s license: %s" % (name, license_ or "none on file"))
    if note:
        say("  " + note)
    if os.environ.get("SPARK_YES") == "1" or not sys.stdin.isatty():
        return True
    try:
        ans = input("download it? [y/N] ").strip().lower()
    except EOFError:
        ans = ""
    if ans not in ("y", "yes"):
        say("spark %s: cancelled" % verb)
        return False
    return True


# ------------------------------------------------------------------ add
QUANT_RE = re.compile(r"-(q4-k-m|q5-k-m|q8-0|f16|bf16|iq[0-9][a-z0-9-]*)$")
CATALOG_FILE = {"curated": "models.env", "ember": "embers.env", "community": "community.env"}
USER_MODELS_FILE = os.path.join(CONFIG_DIR, "models.env")


def _short(path):
    return "~" + path[len(HOME):] if path.startswith(HOME + "/") else path


def _source_file(source):
    return USER_MODELS_FILE if source == "user" else os.path.join(REPO, CATALOG_FILE[source])


def _model_name(fname):
    """The file stem, lowercased, dots and underscores to dashes, a
    trailing quantization token stripped: Qwen_Qwen3-4B-Q4_K_M.gguf ->
    qwen-qwen3-4b."""
    stem = os.path.splitext(fname)[0].lower().replace(".", "-").replace("_", "-")
    return QUANT_RE.sub("", stem)


def _head(url, extra_headers=None):
    """(headers, error) -- a HEAD request through urllib, redirects
    followed, headers of the final response; error is a one-line reason,
    or None."""
    req = Request(url, method="HEAD", headers=dict(extra_headers or {}, **{"User-Agent": "spark"}))
    try:
        with urlopen(req, timeout=20) as resp:
            return resp.headers, None
    except (URLError, OSError) as e:
        return None, "could not reach %s -- %s" % (url, e)


def _probe_model_url(url, sha):
    """(bytes, sha256, error) for `spark model add URL`: huggingface.co is
    auto-verified from its LFS headers (x-linked-size, x-linked-etag);
    any other host needs --sha256 and its size from a plain HEAD."""
    host = urlsplit(url).hostname or ""
    if host == "huggingface.co":
        hurl = url + ("&download=true" if "?" in url else "?download=true")
        headers, err = _head(hurl)
        if err:
            return None, None, err
        size = headers.get("x-linked-size")
        etag = (headers.get("x-linked-etag") or "").strip('"').lower()
        if not size or not re.match(r"^[0-9a-f]{64}$", etag):
            return None, None, "not an LFS file -- add --sha256 HEX"
        return int(size), etag, None
    if not sha:
        return None, None, "%s is not huggingface.co -- add --sha256 HEX" % host
    if not re.match(r"^[0-9a-fA-F]{64}$", sha):
        return None, None, "--sha256 needs 64 hex characters"
    headers, err = _head(url)
    if err:
        return None, None, err
    size = headers.get("Content-Length")
    if not size:
        return None, None, "%s answered no Content-Length" % url
    return int(size), sha.lower(), None


def _model_add(args):
    url = sha = license_ = None
    it = iter(args)
    for a in it:
        if a == "--sha256":
            sha = next(it, None)
        elif a == "--license":
            license_ = next(it, None)
        elif url is None:
            url = a
        else:
            say(MODEL_USAGE.rstrip())
            return 2
    if not url:
        say(MODEL_USAGE.rstrip())
        return 2
    if not license_:
        say('spark model add: --license "NAME URL" is required -- your own row states its license too')
        return 2
    nbytes, sha256, err = _probe_model_url(url, sha)
    if err:
        say("spark model add: %s" % err)
        return 2
    fname = os.path.basename(urlsplit(url).path)
    if not fname:
        say("spark model add: %s has no file name" % url)
        return 2
    name = _model_name(fname)
    if not name:
        say("spark model add: %s has no name once the quantization is stripped" % fname)
        return 2
    existing = {r[0]: r[6] for r in config.model_tables()}
    if name in existing:
        say("spark model add: %s is already in %s" % (name, _short(_source_file(existing[name]))))
        return 2
    ram_gb = math.ceil(nbytes / 2**30 * 1.1 + 1.5)
    stem = name.upper().replace("-", "_")
    set_keys(_file=USER_MODELS_FILE, _quiet=True, **{
        "MODEL_" + stem: '"%s %s %d %s %d"' % (fname, url, nbytes, sha256, ram_gb),
        "MODEL_" + stem + "_LICENSE": '"%s"' % license_})
    say("ok     model        added %s (%.1f GB, ram %d GB) -- %s" % (
        name, nbytes / 2**30, ram_gb, _short(USER_MODELS_FILE)))
    return cmd_model([name])


def cmd_model(args):
    from . import engine
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(MODEL_USAGE.rstrip())
        return 0
    if args[0:1] == ["add"]:
        return _model_add(args[1:])
    if args[0:1] == ["verify"]:
        from . import verify
        rows = verify.verify_all(cfg, force=True)
        if not rows:
            say("spark model verify: no downloaded model")
            return 0
        bad = False
        width = max(12, max(len(r["name"]) for r in rows))
        for r in rows:
            if r["status"] == "ok":
                say("%-7s%-*s sha256 ok (%.1f GB)" % ("ok", width, r["name"], r["bytes"] / 2**30))
            else:
                bad = True
                say("%-7s%-*s sha256 MISMATCH -- spark model rm %s; spark model %s" % (
                    "bad", width, r["name"], r["name"], r["name"]))
        return 1 if bad else 0
    rows = config.model_tables()
    if not args or args[0] == "list":
        return print_model_table(cfg)
    if args[0] == "budget":
        if len(args) == 1:
            gb = mem_total_gb() * cfg.ai_budget / 100.0
            say("%s model budget%s%d%% of %.0f GB = %.0f GB" % (MARK, glyph("sep"), cfg.ai_budget, mem_total_gb(), gb))
            return print_model_table(cfg)
        if len(args) != 2 or not args[1].isdigit() or not 10 <= int(args[1]) <= 95:
            say(MODEL_USAGE.rstrip())
            return 2
        set_keys(SITE_AI_BUDGET=args[1])
        pend = [] if os.environ.get("SPARK_NO_APPLY") else _downloads_pending(config.load())
        _announce_downloads(pend)
        rc = apply(["model", "ember"], stream=bool(pend))
        if rc != 0:
            return rc
        if not os.environ.get("SPARK_NO_APPLY"):
            cfg = config.load()
            if engine.model_file(cfg):
                _restart_server(cfg)
            else:
                say("ok     server       nothing to serve -- left as it is")
        return print_model_table(config.load())
    if args[0] == "rm":
        if len(args) != 2:
            say(MODEL_USAGE.rstrip())
            return 2
        match = [r for r in rows if r[0] == args[1]]
        fname = match[0][1] if match else args[1]
        path = os.path.join(cfg.models_dir, fname)
        if not os.path.isfile(path):
            say("spark model: %s is not downloaded -- nothing to remove" % fname)
            return 1
        if fname == engine.chosen_model_name(cfg) or path == engine.model_file(cfg):
            say("spark model: %s is in use -- choose another first" % fname)
            return 1
        os.remove(path)
        say("ok     removed      %s" % path)
        return 0
    name = args[0]
    match = [r for r in rows if r[0] == name]
    if name not in ("auto", "none") and not match:
        say("spark model: no model named %s -- one of: auto none %s" % (name, " ".join(r[0] for r in rows)))
        return 2
    if match and not _license_ok(match[0], "model"):
        return 1
    set_keys(SITE_AI_MODEL=name)
    pend = [] if os.environ.get("SPARK_NO_APPLY") else _downloads_pending(config.load())
    _announce_downloads(pend)
    rc = apply(["model"], stream=bool(pend))
    if rc != 0:
        return rc
    if os.environ.get("SPARK_NO_APPLY"):
        return 0
    cfg = config.load()
    if name == "none" or not engine.model_file(cfg):
        say("ok     server       nothing to serve -- left as it is")
        return 0
    _restart_server(cfg)
    return 0


# ------------------------------------------------------------------ ember
EMBER_USAGE = """%s ember -- the conversational model

  spark ember                   the two roles: model, file, loaded or not
  spark ember NAME              choose it: site.env, download, server restart
  spark ember auto              the largest that fits beside the spark model
  spark ember none              no second model -- spark answers everything
  spark ember list              the table plus embers.env's rows, purpose
                                shown, the spark pick marked *, the ember +
""" % MARK


def cmd_ember(args):
    from . import engine, wire
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(EMBER_USAGE.rstrip())
        return 0
    if args and args[0] == "list":
        return print_model_table(cfg, embers=True)
    if not args:
        pair = engine.chosen_rows(cfg)
        files = engine.roles(cfg)
        url = wire.serve_url()
        status = engine.models_status(cfg, url) if url and wire.health(url) == "ok" else {}
        say("%s ember%sSITE_EMBER_MODEL=%s" % (MARK, glyph("sep"), cfg.ember_model))
        for role in engine.ROLES:
            f, r = files[role], pair.get(role)
            if not f and not r:
                say("  %-5s  none -- %s" % (role, "spark answers everything (spark ember NAME adds one)"
                                            if role == "ember" else "no model (./bootstrap.sh downloads one)"))
            elif f:
                say(("  %-5s  %-14s %5.1f GB  %s" % (role, engine.model_stem(f),
                                                     os.path.getsize(f) / 2**30, status.get(role, ""))).rstrip())
            else:
                say("  %-5s  %-14s not downloaded (./bootstrap.sh)" % (role, r[1].replace(".gguf", "")))
        return 0
    name = args[0]
    rows = config.model_tables()
    match = [r for r in rows if r[0] == name]
    if name not in ("auto", "none") and not match:
        say("spark ember: no model named %s -- one of: auto none %s   (spark ember list)" % (name, " ".join(r[0] for r in rows)))
        return 2
    if match and not _license_ok(match[0], "ember"):
        return 1
    set_keys(SITE_EMBER_MODEL=name)
    pend = [] if os.environ.get("SPARK_NO_APPLY") else _downloads_pending(config.load())
    _announce_downloads(pend)
    rc = apply(["model", "ember"], stream=bool(pend))
    if rc != 0:
        return rc
    if os.environ.get("SPARK_NO_APPLY"):
        return 0
    cfg = config.load()
    if not engine.model_file(cfg):
        say("ok     server       nothing to serve -- left as it is")
        return 0
    _restart_server(cfg)
    return 0


# --------------------------------------------------------------------- rc
# The core rc hook: bootstrap's `rc` row appends one marked line to the
# login shell's rc file; `spark shell on` may replace that file with spark's
# own symlink; `spark shell off` hands it back (restore_rc). Pure functions:
# the callers print the rows.
RC_MARKER = "config/spark/hook."
RC_LINE = {"bash": "[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt",
           "zsh": "[[ -r ~/.config/spark/hook.zsh ]] && source ~/.config/spark/hook.zsh   # spark: the AI at the prompt"}
RC_FILES = (".zshrc", ".zprofile") if IS_MAC else (".bashrc", ".bash_profile")


def login_shell():
    """The login shell's basename: $SHELL, else the passwd entry."""
    s = os.environ.get("SHELL") or ""
    if not s:
        try:
            s = pwd.getpwuid(os.getuid()).pw_shell
        except KeyError:
            s = ""
    return os.path.basename(s) or "sh"


def rc_file(shell):
    """The rc file the `rc` row hooks for this shell (bash, zsh), else None."""
    name = {"bash": ".bashrc", "zsh": ".zshrc"}.get(shell)
    return os.path.join(HOME, name) if name else None


def _spark_link(path):
    """True when path is a symlink into the repository (spark's own file)."""
    if not os.path.islink(path):
        return False
    try:
        target = os.readlink(path)
    except OSError:
        return False
    return target.startswith(REPO + "/") or os.path.realpath(path).startswith(os.path.realpath(REPO) + "/")


def rc_hook_state(shell):
    """("link" | "hook" | "missing", path): the rc file is spark's own
    symlink, sources the hook (the marker line), or lacks it (path None
    for a shell without an rc file to hook)."""
    path = rc_file(shell)
    if not path:
        return ("missing", None)
    if _spark_link(path):
        return ("link", path)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            if RC_MARKER in f.read():
                return ("hook", path)
    except OSError:
        pass
    return ("missing", path)


def restore_rc():
    """spark shell off: every rc file of this OS that is spark's symlink goes
    back to the user -- the link removed, <file>.bak moved back when it
    exists, else an empty file. Returns [(path, what)]."""
    done = []
    for name in RC_FILES:
        path = os.path.join(HOME, name)
        if not _spark_link(path):
            continue
        os.unlink(path)
        bak = path + ".bak"
        if os.path.lexists(bak):
            os.rename(bak, path)
            done.append((path, "restored from %s.bak" % name))
        else:
            open(path, "a", encoding="utf-8").close()
            done.append((path, "empty file (no %s.bak to restore)" % name))
    return done


# ------------------------------------------------------------------ shell
SHELL_USAGE = """%s shell -- spark's own shell: tmux, starship, micro, fzf, eza, bat, btop

  spark shell                   the state: off (the prompt widget only) or on
  spark shell on                SITE_SHELL=on: the tools, the Nerd Font, the
                                console; the rc files become spark's (yours
                                move to .bak)
  spark shell off               SITE_SHELL=off: the rc files come back (.bak);
                                the packages stay installed
""" % MARK
# the bootstrap rows the switch flips (bootstrap.sh gates them on SITE_SHELL)
SHELL_ROWS = ["identity", "hostname", "dir", "apt", "brew", "starship", "font", "micro-aspell", "pinned",
              "configs", "rc", "theme", "terminfo", "console", "quiet-login", "quiet-boot", "quiet"]
SHELL_TOOLS = "tmux, starship, micro, fzf, zoxide, eza, bat, btop"


def rc_state(path):
    """"spark's" (the repo's symlink), "hook" (the marked line), "yours"
    (anything else), or "absent" -- for one rc file of RC_FILES."""
    if _spark_link(path):
        return "spark's"
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "hook" if RC_MARKER in f.read() else "yours"
    except OSError:
        return "absent"


def cmd_shell(args):
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(SHELL_USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        if not cfg.shell:
            say("%s shell -- SITE_SHELL=off -- the prompt widget only" % MARK)
            say("  spark shell on adds %s," % SHELL_TOOLS)
            say("  the Nerd Font, and makes the rc files spark's")
            return 0
        say("%s shell -- SITE_SHELL=on -- the shell layer is spark's" % MARK)
        say("  rc files: " + ", ".join("~/%s (%s)" % (n, rc_state(os.path.join(HOME, n))) for n in RC_FILES))
        say("  " + ", ".join("%s %s" % (t, "yes" if shutil.which(t) else "no") for t in ("starship", "tmux")))
        return 0
    if args[0] not in ("on", "off"):
        say(SHELL_USAGE.rstrip())
        return 2
    if args[0] == "on":
        set_keys(SITE_SHELL="on")
        rc = apply(SHELL_ROWS, stream=True)
        if rc == 0:
            say("open a new shell (exec $SHELL)")
        return rc
    set_keys(SITE_SHELL="off")
    for path, what in restore_rc():
        say("ok     restore      ~%s -- %s" % (path[len(HOME):], what))
    rc = apply(["configs", "rc"])
    say("packages stay installed -- apt or brew removes them if you want")
    return rc


def main(sub, args):
    if sub == "shell":
        return cmd_shell(args)
    if sub == "model":
        return cmd_model(args)
    if sub == "ember":
        return cmd_ember(args)
    if sub == "headless":
        return cmd_headless(args)
    return cmd_font(args) if sub == "font" else cmd_bootconfig(args)
