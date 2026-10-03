# spark.model -- the AI-infrastructure verb: `spark model` (which model
# this machine serves: the table, a choice, budget, rm, add, verify) and
# `spark model --chat` (the conversational model, the second role from
# the same table; `spark ember` is its older spelling). Each writes the site.env key, then applies it (site.set_keys,
# site.apply) and restarts the server that must follow.

import json
import math
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from . import CONFIG_DIR, HOME, IS_MAC, MARK, REPO, config, confirm, mem_total_gb, paged, say
from .site import apply, set_keys
from .text import pulse as _pulse   # each file's hash in spark model verify


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
        say("ok     download     %s (%.1f GB)" % (r[0], r[3] / 2**30))


# ------------------------------------------------------------------ model
MODEL_USAGE = """%s model -- which model this machine serves

  spark model                   the list (* the prompt line, + the chat,
                                u = yours)
  spark model list --porcelain  the same, tab separated, for a program
  spark model NAME              download and serve it (asks first when its
                                licence is not open)
  spark model auto | none       the first tested model that fits, or none
  spark model budget [N]        the share of memory models may use (10-95)
  spark model rm NAME           delete a downloaded model not in use
  spark model add URL           add your own: --license "NAME URL", and
                                --sha256 HEX unless it is on Hugging Face
  spark model verify            check every downloaded model is intact
  spark model --chat [NAME]     a second model for chat (-h)

  On a client, the list is the other machine's: choose there.
""" % MARK


def _client_no(cfg, what):
    """The one line a client answers to a model choice: nothing is served
    here, so a budget, a model or a chat model chosen here would silently
    make this machine a server (that is spark client off, by name)."""
    say("%s %s -- a client of %s serves nothing: choose there, or spark client off"
        % (MARK, what, cfg.peer_ai_url))
    return 2


def peer_models(cfg):
    """The peer's own model table: GET /api/models on the FORGE, with the
    login token (any role). None when the peer is down, a bare
    llama-server, or a FORGE older than this route."""
    from . import wire
    try:
        req = Request(cfg.peer_ai_url.rstrip("/") + "/api/models", headers=wire._headers(cfg, forge=True))
        with urlopen(req, timeout=wire.HEALTH_TIMEOUT) as r:
            d = json.load(r)
        return d if isinstance(d, dict) and isinstance(d.get("models"), list) else None
    except (HTTPError, URLError, OSError, ValueError):
        return None


def _restart_server(cfg):
    from . import engine, wire
    st = engine.service_state(cfg)
    if st == "loaded":
        if IS_MAC and engine.service_domain(cfg) == "system":
            say(engine.daemon_note(cfg))
            return
        say("ok     server       restarting")
        engine.service_stop(noreload=False)
        # a server spark started by hand beside the unit goes too: left on
        # the port, the restarted unit stood down (78) and the OLD model
        # answered the wait below with "ready"
        left = engine.clear_port(cfg, 30)
        if left:
            say("todo   server       another server holds port %d -- spark serve off --force, then spark serve on"
                % cfg.port)
            return
        if not engine.kickstart(cfg):
            return
        # the brain cache names the model that WAS served (60 s): the next
        # `spark status` after a swap must resolve afresh, not say the old stem
        wire.drop_cache()
        # the server binds to the LAN ip (serve.py does the same), and
        # a just-restarted server has not written serve-url yet: falling
        # back to 127.0.0.1 probed a host the server never binds to, so
        # the wait timed out with "not ready" while the server was up on
        # the LAN. Re-read serve-url each poll (the server writes it when
        # ready), else the LAN url it will bind to.
        from . import lan_ip
        def _up():
            url = wire.serve_url() or "http://%s:%d" % (cfg.serve_host or lan_ip() or "127.0.0.1", cfg.port)
            return wire.health(url) == "ok"
        if engine.wait_load(cfg, "", _up, 180, 2):
            say("ok     server       ready")
        else:
            say("todo   server       not ready yet -- spark check --watch 5")
        from . import check
        check.refresh()
    elif engine.pidfile_pid():
        from . import serve
        serve.cmd_stop([])
        serve.cmd_serve([], by_hand=True)
    else:
        say("ok     server       not running -- spark serve on starts it")


SOURCE_MARKS = {"repo": " ", "user": "u"}


def serving_stems(cfg):
    """{file stem} of every model the answering server holds loaded: the
    router lists both roles with a status, a single server its one model
    (wire.models, the listing the FORGE's /api/health reads too). The
    brain's own model when the listing says nothing; {} when nothing
    answers."""
    from . import wire
    try:
        b = wire.resolve_brain(cfg)
    except wire.BrainError:
        return set()
    try:
        held = {stem for _alias, stem, loaded in wire.models(cfg, b.url, forge=b.forge) if loaded and stem}
    except wire.BrainError:
        held = set()
    return held or {b.model}


def model_rows(cfg, serving=None):
    """The model table as data: [{name, gb, ram_gb, fits, downloaded,
    chosen, role, serving, speed, speed_kind, source, mark, tested,
    license, open, note}] in model_tables() order (the list, then yours).
    `role` is "spark", "ember" or "" from engine.chosen_rows. `source` is
    "repo" or "user"; `mark` is the second column's glyph (SOURCE_MARKS:
    blank, `u` yours); `tested` says the row was proven on the line and
    `open` that its license is one auto may take (config.is_open).
    `serving` is the model name a brain answers with, or a set of them;
    None asks the brain (the FORGE passes its own): every model the
    server holds loaded (serving_stems). `speed` is tok/s and
    `speed_kind` "measured" or "estimate" (engine.speed_of)."""
    from . import engine, wire
    # a client serves nothing: its own RAM is no budget, so `fits` is None
    budget = None if cfg.client else mem_total_gb() * cfg.ai_budget / 100.0
    pair = engine.chosen_rows(cfg)
    chosen = pair["spark"][1] if pair.get("spark") else ""
    role_of = {}
    for role in engine.ROLES:
        r = pair.get(role)
        if r and r[1] not in role_of:
            role_of[r[1]] = role
    if serving is None:
        serving = serving_stems(cfg)
    serving = {serving} if isinstance(serving, str) else set(serving)
    serving.discard("")
    out = []
    for row in config.model_tables():
        name, fname, _url, nbytes, _sha, ram, source, tested, license_, note, ground = row
        speed, kind = engine.speed_of(cfg, row)
        out.append({"name": name, "gb": round(nbytes / 2**30, 1), "ram_gb": ram, "fits": (ram <= budget) if budget is not None else None,
                    "downloaded": os.path.isfile(os.path.join(cfg.models_dir, fname)),
                    "chosen": fname == chosen, "role": role_of.get(fname, ""),
                    "serving": fname.replace(".gguf", "") in serving,
                    "speed": speed, "speed_kind": kind, "source": source,
                    "mark": SOURCE_MARKS.get(source, " "), "tested": tested,
                    "license": license_, "open": config.is_open(license_), "note": note,
                    "ground": ground})
    return out


def license_word(license_, width=10):
    """The license's first word within `width` columns: whole parts
    between hyphens (`Llama-3.2`, never `Llama-3.2-`), a hard cut only
    when the first part alone is wider."""
    word = ((license_ or "").split() or [""])[0]
    if len(word) <= width:
        return word
    parts = word.split("-")
    out = parts[0]
    for p in parts[1:]:
        if len(out) + 1 + len(p) > width:
            break
        out += "-" + p
    return out[:width]


# the table's columns besides the name and the license: the marks, the
# file size, the RAM, the proof, the state and the speed, with the
# spaces between them
_FIXED_COLS = 48


def table_widths(rows):
    """(name, license) column widths for these rows: the name as wide as
    the widest name (13 at least), the license as wide as the widest
    first word within what 80 columns leave (10 at least, Apache-2.0)."""
    width = max([13] + [len(r["name"]) for r in rows])
    widest = max([10] + [len(((r["license"] or "").split() or [""])[0]) for r in rows])
    return width, max(10, min(widest, 80 - _FIXED_COLS - width))


def model_line(r, marks=None, width=13, lic_width=10):
    """One table row: the pick mark (spark *, ember +), the source mark
    (blank the list, `u` yours), the name, the file size, the RAM verdict,
    the license's first word, the proof column (`line` for the line proof,
    or the grounding audition's kept/run score when the row carries
    MODEL_<NAME>_GROUND), downloaded / serving, and the speed --
    `~N tok/s` an estimate, `N tok/s` measured; nothing for a row that
    does not fit. `width` pads the name column and `lic_width` the
    license's (table_widths sizes both from the rows). Every row stays
    within 80 columns."""
    marks = marks or {"spark": "*", "ember": "+"}
    state = "serving" if r["serving"] else ("downloaded" if r["downloaded"] else "")
    if r["fits"] is None:
        speed = ""                       # a client: the peer's business
    else:
        speed = ("%s%d tok/s" % ("~" if r["speed_kind"] == "estimate" else "", r["speed"])) if r["fits"] else "too big"
    lic = license_word(r["license"], lic_width)
    # the proof column: the ground score (kept/run of the grounding
    # audition) when the row has one, else `line` for the line proof
    proof = (r.get("ground") or "").split()[0] if r.get("ground") else ("line" if r["tested"] else "")
    # padded columns, right-aligned numbers: the eye reads a table, not a
    # sentence; _FIXED_COLS + width + lic_width columns in all
    return ("  %s%s %-*s %5.1f GB %2.0f GB %-*s %-5s %-10s %9s"
            % (marks.get(r["role"], " "), r["mark"], width, r["name"], r["gb"], r["ram_gb"],
               lic_width, lic, proof, state, speed)).rstrip()


def print_model_table(cfg):
    """The one table `spark model list` and `spark model --chat list` share:
    every row of models.env and yours with its RAM verdict, the spark pick
    marked * and the ember pick + (the marks bootstrap.sh --list-models
    draws), a second mark `u` for your own rows, the license's first word,
    `line` on a row proven on the line (auto reads only those, under an
    open license), and a last column with the generation speed: `~N
    tok/s` an estimate for this backend, `N tok/s` measured here (spark
    bench, or a real turn); nothing for a row that does not fit. A row's
    note follows it, indented. Every row stays within 80 columns."""
    from . import engine
    if cfg.client:
        # a client: never this machine's RAM. The peer's table when its
        # FORGE answers /api/models (the box's RAM, budget, picks,
        # speeds); else the rows alone, no verdict
        peer = peer_models(cfg)
        if peer:
            say("%s model -- the other machine's table: %.0f GB for models, budget %.0f GB (%d%%)" % (
                MARK, peer.get("total_gb", 0), peer.get("budget_gb", 0), peer.get("budget_pct", 0)))
            say("  a client of %s" % cfg.peer_ai_url)
            if peer.get("cap_note"):
                say("  " + peer["cap_note"])
            rows = peer["models"]
        else:
            say("%s model -- a client of %s: run spark model there to see what fits" % (MARK, cfg.peer_ai_url))
            rows = model_rows(cfg)
    else:
        budget = mem_total_gb() * cfg.ai_budget / 100.0
        say("%s model -- %.0f GB for models, budget %.0f GB (%d%%)" % (
            MARK, mem_total_gb(), budget, cfg.ai_budget))
        note = engine.cap_note(cfg)
        if note:
            say("  " + note)
        rows = model_rows(cfg)
    width, lic_width = table_widths(rows)
    say("     %-*s %8s %5s %-*s %-5s %-10s %9s" % (width, "model", "file", "RAM", lic_width, "licence", "line", "", "fits"))
    for r in rows:
        say(model_line(r, width=width, lic_width=lic_width))
        if r["note"]:
            say("      " + r["note"])
    known = {row[1] for row in config.model_tables()}
    others = [f for f in os.listdir(cfg.models_dir) if f.endswith(".gguf") and f not in known] if os.path.isdir(cfg.models_dir) else []
    for f in others:
        say("    %-13s %5.1f GB file   (%s, not in models.env)" % (
            "-", os.path.getsize(os.path.join(cfg.models_dir, f)) / 2**30, f))
    say("  * the prompt line, + the chat, u = yours")
    say("  auto: the first tested row that fits, %s" % " or ".join(config.OPEN_LICENSES))
    return 0


def _license_ok(row, verb):
    """A row under a license auto would not take (config.is_open: not
    Apache-2.0 or MIT) prints its license line -- and its note, when
    there is one -- and gets a yes before the download: SPARK_YES=1 in
    the environment, or stdin not a tty (a script, a pipe), counts as yes
    without asking. An open-license row downloads without a question."""
    name, license_, note = row[0], row[8], row[9]
    if config.is_open(license_):
        return True
    say("%s licence: %s" % (name, license_ or "none on file"))
    if note:
        say("  " + note)
    if os.environ.get("SPARK_YES") == "1" or not sys.stdin.isatty():
        return True
    if not confirm("download it"):
        say("* nothing changed")
        return False
    return True


# ------------------------------------------------------------------ add
QUANT_RE = re.compile(r"-(q4-k-m|q5-k-m|q8-0|f16|bf16|iq[0-9][a-z0-9-]*)$")
USER_MODELS_FILE = os.path.join(CONFIG_DIR, "models.env")


def _short(path):
    return "~" + path[len(HOME):] if path.startswith(HOME + "/") else path


def _source_file(source):
    return USER_MODELS_FILE if source == "user" else os.path.join(REPO, "models.env")


def _model_name(fname):
    """The file stem, lowercased, dots and underscores to dashes, a
    trailing quantization token stripped: Qwen_Qwen3-4B-Q4_K_M.gguf ->
    qwen-qwen3-4b."""
    stem = os.path.splitext(fname)[0].lower().replace(".", "-").replace("_", "-")
    return QUANT_RE.sub("", stem)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _head(url, extra_headers=None, follow=True):
    """(headers, error) -- a HEAD request through urllib; redirects
    followed and the final response's headers returned, or, with
    follow=False, the FIRST response's headers even when it is a 3xx
    (huggingface.co puts the file's size and sha256 on its redirect, and
    the CDN it points at knows neither). error is a one-line reason, or
    None."""
    req = Request(url, method="HEAD", headers=dict(extra_headers or {}, **{"User-Agent": "spark"}))
    opener = urlopen if follow else build_opener(_NoRedirect()).open
    try:
        with opener(req, timeout=20) as resp:
            return resp.headers, None
    except HTTPError as e:
        if not follow and 300 <= e.code < 400:
            return e.headers, None
        return None, "could not reach %s -- %s" % (url, e)
    except (URLError, OSError) as e:
        return None, "could not reach %s -- %s" % (url, e)


def _probe_model_url(url, sha):
    """(bytes, sha256, error) for `spark model add URL`: huggingface.co is
    auto-verified from its LFS headers (x-linked-size, x-linked-etag, on
    the redirect it answers with); any other host needs --sha256 and its
    size from a plain HEAD."""
    host = urlsplit(url).hostname or ""
    if host == "huggingface.co":
        hurl = url + ("&download=true" if "?" in url else "?download=true")
        headers, err = _head(hurl, follow=False)
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
        say('spark model add -- add --license "NAME URL"')
        return 2
    bad = re.search(r"[;`$()|&<>]", license_)
    if bad:
        # contract 3 refuses the whole file over one such character, and
        # then every verb dies with exit 2 -- refuse it before it lands
        say("spark model add -- a licence cannot hold %s; use - or , instead" % bad.group(0))
        return 2
    nbytes, sha256, err = _probe_model_url(url, sha)
    if err:
        say("spark model add -- %s" % err)
        return 2
    fname = os.path.basename(urlsplit(url).path)
    if not fname:
        say("spark model add -- %s has no file name" % url)
        return 2
    name = _model_name(fname)
    if not name:
        say("spark model add -- %s gives no name" % fname)
        return 2
    existing = {r[0]: r[6] for r in config.model_tables()}
    if name in existing:
        say("spark model add -- %s is already in %s" % (name, _short(_source_file(existing[name]))))
        return 2
    ram_gb = math.ceil(nbytes / 2**30 * 1.1 + 1.5)
    stem = name.upper().replace("-", "_")
    set_keys(_file=USER_MODELS_FILE, _quiet=True, **{
        "MODEL_" + stem: '"%s %s %d %s %d"' % (fname, url, nbytes, sha256, ram_gb),
        "MODEL_" + stem + "_LICENSE": '"%s"' % license_})
    say("ok     model        added %s (%.1f GB, needs %d GB)" % (name, nbytes / 2**30, ram_gb))
    return cmd_model([name])


def cmd_model(args):
    from . import engine
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(MODEL_USAGE.rstrip())
        return 0
    if args[0:1] == ["--chat"]:
        return cmd_ember(args[1:])
    if args[0:1] == ["add"]:
        return _model_add(args[1:])
    if args[0:1] == ["verify"]:
        from . import verify
        with _pulse():
            rows = verify.verify_all(cfg, force=True)
        if not rows:
            say("spark model verify -- no model downloaded")
            return 0
        bad = False
        width = max(12, max(len(r["name"]) for r in rows))
        for r in rows:
            if r["status"] == "ok":
                say("%-7s%-*s intact (%.1f GB)" % ("ok", width, r["name"], r["bytes"] / 2**30))
            else:
                bad = True
                say("%-7s%-*s damaged -- spark model rm %s; spark model %s" % (
                    "bad", width, r["name"], r["name"], r["name"]))
        return 1 if bad else 0
    rows = config.model_tables()
    if not args or args[0] in ("list", "status", "--porcelain"):
        if "--porcelain" in args:
            for r in model_rows(cfg):
                say("\t".join([r["name"], r["source"], "%.1f" % r["gb"], "%.0f" % r["ram_gb"],
                               (r["license"].split() or [""])[0],
                               "line" if r["tested"] else "-", r["ground"] or "-",
                               "serving" if r["serving"] else ("downloaded" if r["downloaded"] else "-")]))
            return 0
        return paged(lambda: print_model_table(cfg))
    if args[0] == "budget":
        if len(args) == 1:
            return print_model_table(cfg)
        if len(args) != 2 or not args[1].isdigit() or not 10 <= int(args[1]) <= 95:
            say(MODEL_USAGE.rstrip())
            return 2
        if cfg.client:
            return _client_no(cfg, "model budget")
        set_keys(SITE_AI_BUDGET=args[1])
        pend = [] if os.environ.get("SPARK_NO_APPLY") else _downloads_pending(config.load())
        _announce_downloads(pend)
        rc = apply(["engine", "model", "ember"], stream=bool(pend))
        if rc != 0:
            return rc
        if not os.environ.get("SPARK_NO_APPLY"):
            cfg = config.load()
            if engine.model_file(cfg):
                _restart_server(cfg)
        return print_model_table(config.load())
    if args[0] == "rm":
        if len(args) != 2:
            say(MODEL_USAGE.rstrip())
            return 2
        if cfg.client:
            return _client_no(cfg, "model rm")
        match = [r for r in rows if r[0] == args[1]]
        fname = match[0][1] if match else args[1]
        path = os.path.join(cfg.models_dir, fname)
        if not os.path.isfile(path):
            say("spark model -- %s is not downloaded" % args[1])
            return 2
        if fname == engine.chosen_model_name(cfg) or path == engine.model_file(cfg):
            say("spark model -- %s is in use: choose another first" % args[1])
            return 1
        os.remove(path)
        say("ok     removed      %s" % args[1])
        return 0
    name = args[0]
    match = [r for r in rows if r[0] == name]
    if name not in ("auto", "none") and not match:
        say("spark model -- no model named %s; spark model lists them" % name)
        return 2
    if cfg.client:
        return _client_no(cfg, "model")
    if match and not _license_ok(match[0], "model"):
        return 1
    set_keys(SITE_AI_MODEL=name)
    pend = [] if os.environ.get("SPARK_NO_APPLY") else _downloads_pending(config.load())
    _announce_downloads(pend)
    rc = apply(["engine", "model"], stream=bool(pend))
    if rc != 0:
        return rc
    if os.environ.get("SPARK_NO_APPLY"):
        return 0
    cfg = config.load()
    if name == "none" or not engine.model_file(cfg):
        return 0
    _restart_server(cfg)
    return 0


# ------------------------------------------------------------------ ember
EMBER_USAGE = """%s model --chat -- the chat model

  spark model --chat            the two models, and whether they are loaded
  spark model --chat NAME       download and use NAME for chat
  spark model --chat auto       the first model that fits beside the other
  spark model --chat none       no chat model: one model answers everything
  spark model --chat list       the list of models
""" % MARK


# the two roles as a person reads them: the prompt line's model, the chat's
ROLE_WORDS = {"spark": "line", "ember": "chat"}


def cmd_ember(args):
    from . import engine, wire
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(EMBER_USAGE.rstrip())
        return 0
    if args and args[0] == "list":
        return paged(lambda: print_model_table(cfg))
    if not args or args[0] == "status":
        pair = engine.chosen_rows(cfg)
        files = engine.roles(cfg)
        url = wire.serve_url()
        status = engine.models_status(cfg, url) if url and wire.health(url) == "ok" else {}
        say("%s model --chat -- the chat model: %s" % (MARK, cfg.ember_model))
        for role in engine.ROLES:
            f, r = files[role], pair.get(role)
            label = ROLE_WORDS.get(role, role)
            if not f and not r:
                say("  %-5s  none -- %s" % (label, "spark answers everything (spark model --chat NAME adds one)"
                                             if role == "ember" else "spark model NAME picks one"))
            elif f:
                say(("  %-5s  %-14s %5.1f GB  %s" % (label, config.model_name(f),
                                                     os.path.getsize(f) / 2**30, status.get(role, ""))).rstrip())
            else:
                say("  %-5s  %-14s not downloaded -- spark update fetches it" % (label, r[0]))
        return 0
    name = args[0]
    rows = config.model_tables()
    match = [r for r in rows if r[0] == name]
    if name not in ("auto", "none") and not match:
        say("spark model --chat -- no model named %s; spark model --chat list shows them" % name)
        return 2
    if cfg.client:
        return _client_no(cfg, "model --chat")
    if match and not _license_ok(match[0], "model --chat"):
        return 1
    set_keys(SITE_EMBER_MODEL=name)
    pend = [] if os.environ.get("SPARK_NO_APPLY") else _downloads_pending(config.load())
    _announce_downloads(pend)
    rc = apply(["engine", "model", "ember"], stream=bool(pend))
    if rc != 0:
        return rc
    if os.environ.get("SPARK_NO_APPLY"):
        return 0
    cfg = config.load()
    if not engine.model_file(cfg):
        return 0
    _restart_server(cfg)
    return 0
