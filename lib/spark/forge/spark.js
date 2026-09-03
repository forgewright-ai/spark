/* spark FORGE page. Vanilla ES2017, no build, no external resource, ASCII
   only. Modules by convention, top to bottom:
     dom     - element helpers (textContent only, never innerHTML)
     api     - fetch wrappers: get/post/del, SSE over POST, 401 -> login card
     theme   - palette -> CSS custom properties; browser-only override
     auth    - the login card; reload + reconnect after a login
     me      - GET /api/me: the role behind the cookie; .adm/.usr rendering
     events  - GET /api/events (EventSource) -> header bar, check tally, serve
     run     - POST /api/run: one verb's output streamed into #output
     monitor, chat, doView, config, help - the five views
     route   - hash routes and the keyboard map
   Contract: the route table in CLAUDE.md contract 9. Any 404 on a route
   that lands in a later step shows "not available yet" in place. */
(function () {
  "use strict";

  /* ----------------------------------------------------------- dom */
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }
  function fact(dl, k, v) {
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", null, v === undefined || v === null || v === "" ? "-" : v));
  }
  function fmtTs(ts) {
    if (typeof ts === "number") {
      var d = new Date(ts * 1000);
      return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
    }
    return ts ? String(ts) : "-";
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function num(x, d) { return typeof x === "number" ? x.toFixed(d === undefined ? 1 : d) : "-"; }
  function keyOf(s) {
    if (!s) return "-";
    if (typeof s === "string") return s;
    return "ngl=" + s.ngl + " fa=" + s.fa + " kv=" + s.kv + " t=" + (s.t || "auto");
  }
  /* text with `code` spans in backticks, nothing else rendered */
  function codeSpans(node, text) {
    var parts = String(text).split("`");
    for (var i = 0; i < parts.length; i++) {
      if (!parts[i]) continue;
      node.appendChild(i % 2 ? el("code", null, parts[i]) : document.createTextNode(parts[i]));
    }
    return node;
  }
  function notYet(node, what) {
    clear(node).appendChild(el("p", "muted", (what || "this") + " is not available yet on this FORGE"));
  }
  function fail(node, e) {
    clear(node).appendChild(el("p", e && e.quiet ? "muted" : "err", String(e && e.message || e)));
  }

  /* ----------------------------------------------------------- api */
  var api = {
    headers: { "X-Spark": "1", "Content-Type": "application/json" },
    check: function (r) {
      if (r.status === 401) { auth.lost(); throw new Error("login needed"); }
      if (r.status === 403) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          var role = j && j.error && j.error.kind === "role";
          var e = new Error(role ? "this needs the admin token" : "HTTP 403");
          e.status = 403; e.quiet = role;
          throw e;
        });
      }
      if (r.status === 404) { var e = new Error("not available yet"); e.status = 404; throw e; }
      if (!r.ok) { var f = new Error("HTTP " + r.status); f.status = r.status; throw f; }
      return r;
    },
    get: function (path) {
      return fetch(path, { credentials: "same-origin" }).then(api.check).then(function (r) { return r.json(); });
    },
    post: function (path, body) {
      return fetch(path, { method: "POST", headers: api.headers, body: JSON.stringify(body || {}), credentials: "same-origin" })
        .then(api.check).then(function (r) { return r.status === 204 ? null : r.json(); });
    },
    del: function (path) {
      return fetch(path, { method: "DELETE", headers: api.headers, credentials: "same-origin" })
        .then(api.check).then(function (r) { return r.status === 204 ? null : r.json(); });
    },
    /* POST that answers with text/event-stream; on = {event: fn(data)} */
    stream: function (path, body, on) {
      return fetch(path, { method: "POST", headers: api.headers, body: JSON.stringify(body || {}), credentials: "same-origin" })
        .then(api.check).then(function (r) {
          var reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
          function block(b) {
            var ev = "message", data = [];
            b.split("\n").forEach(function (l) {
              if (l.indexOf("event:") === 0) ev = l.slice(6).trim();
              else if (l.indexOf("data:") === 0) data.push(l.slice(5).replace(/^ /, ""));
            });
            if (!data.length) return;
            var d = data.join("\n");
            try { d = JSON.parse(d); } catch (x) { /* plain text stays text */ }
            if (on[ev]) on[ev](d);
          }
          function pump() {
            return reader.read().then(function (x) {
              if (x.done) { if (buf.trim()) block(buf); return; }
              buf += dec.decode(x.value, { stream: true }).replace(/\r/g, "");
              var parts = buf.split("\n\n");
              buf = parts.pop();
              parts.forEach(block);
              return pump();
            });
          }
          return pump();
        });
    }
  };

  /* ----------------------------------------------------------- theme */
  var theme = {
    KEY: "spark.palette",
    /* copied from themes/*.env: bg fg accent muted, then ansi 0..15 */
    builtin: {
      "catppuccin-mocha": ["#1e1e2e", "#cdd6f4", "#cba6f7", "#6c7086", "#45475a", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#bac2de", "#585b70", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#a6adc8"],
      "gruvbox-dark": ["#282828", "#ebdbb2", "#fe8019", "#928374", "#282828", "#cc241d", "#98971a", "#d79921", "#458588", "#b16286", "#689d6a", "#a89984", "#928374", "#fb4934", "#b8bb26", "#fabd2f", "#83a598", "#d3869b", "#8ec07c", "#ebdbb2"],
      "selenized-dark": ["#103c48", "#adbcbc", "#4695f7", "#72898f", "#184956", "#fa5750", "#75b938", "#dbb32d", "#4695f7", "#f275be", "#41c7b9", "#72898f", "#2d5b69", "#ff665c", "#84c747", "#ebc13d", "#58a3ff", "#ff84cd", "#53d6c7", "#cad8d9"],
      "solarized-light": ["#fdf6e3", "#657b83", "#268bd2", "#93a1a1", "#073642", "#dc322f", "#859900", "#b58900", "#268bd2", "#d33682", "#2aa198", "#eee8d5", "#002b36", "#cb4b16", "#586e75", "#657b83", "#839496", "#6c71c4", "#93a1a1", "#fdf6e3"]
    },
    machine: null,      /* {name, palette} from /api/theme, or null = neutral */
    names: [],
    fromEnv: function (p) {   /* THEME_* dict -> the flat array above */
      var a = [p.THEME_BG, p.THEME_FG, p.THEME_ACCENT, p.THEME_MUTED];
      for (var i = 0; i < 16; i++) a.push(p["THEME_ANSI_" + i]);
      return a;
    },
    hex: function (h) { return [1, 3, 5].map(function (i) { return parseInt(h.substr(i, 2), 16); }); },
    mix: function (a, b, w) {   /* w = the share of a */
      var A = theme.hex(a), B = theme.hex(b);
      return "#" + [0, 1, 2].map(function (i) { return pad2(Math.round(A[i] * w + B[i] * (1 - w))); }).join("");
      function pad2(n) { return (n < 16 ? "0" : "") + n.toString(16); }
    },
    set: function (a) {   /* apply a flat array, or null to fall back to CSS */
      var st = document.documentElement.style, k;
      var names = ["--bg", "--fg", "--accent", "--muted"];
      for (k = 0; k < 16; k++) names.push("--ansi-" + k);
      names.push("--muted-text", "--line", "--tint");
      if (!a || a.length < 20 || a.some(function (c) { return !/^#[0-9a-fA-F]{6}$/.test(c || ""); })) {
        names.forEach(function (n) { st.removeProperty(n); });
        return;
      }
      for (k = 0; k < 20; k++) st.setProperty(names[k], a[k]);
      st.setProperty("--muted-text", theme.mix(a[1], a[0], 0.72));   /* readable, unlike THEME_MUTED */
      st.setProperty("--line", theme.mix(a[3], a[0], 0.4));
      st.setProperty("--tint", theme.mix(a[1], a[0], 0.05));
    },
    override: function () { try { return localStorage.getItem(theme.KEY) || ""; } catch (e) { return ""; } },
    apply: function () {
      var want = theme.override();
      if (want && theme.builtin[want]) return theme.set(theme.builtin[want]);
      if (want && theme.machine && theme.machine.name === want) return theme.set(theme.fromEnv(theme.machine.palette));
      if (theme.machine && theme.machine.palette) return theme.set(theme.fromEnv(theme.machine.palette));
      theme.set(null);
    },
    menu: function () {
      var cur = theme.override();
      var all = Object.keys(theme.builtin);
      theme.names.forEach(function (n) { if (all.indexOf(n) < 0) all.push(n); });
      all.sort();
      ["palette", "palette2"].forEach(function (id) {
        var sel = clear($(id));
        var o = el("option", null, "follow the machine"); o.value = "";
        sel.appendChild(o);
        all.forEach(function (n) {
          var op = el("option", null, n); op.value = n;
          if (!theme.builtin[n] && !(theme.machine && theme.machine.name === n)) op.disabled = true;
          sel.appendChild(op);
        });
        sel.value = cur;
      });
    },
    load: function () {
      return api.get("/api/theme").then(function (t) {
        theme.machine = t.palette ? { name: t.name, palette: t.palette } : null;
        theme.names = t.palettes || [];
        try { localStorage.setItem("spark.machine", JSON.stringify(theme.machine)); } catch (e) { /* fine */ }
        theme.menu(); theme.apply();
      }).catch(function () { /* before login: keep what we have */ });
    },
    init: function () {
      try { theme.machine = JSON.parse(localStorage.getItem("spark.machine") || "null"); } catch (e) { theme.machine = null; }
      theme.menu(); theme.apply();
      ["palette", "palette2"].forEach(function (id) {
        $(id).addEventListener("change", function () {
          try { if (this.value) localStorage.setItem(theme.KEY, this.value); else localStorage.removeItem(theme.KEY); } catch (e) { /* fine */ }
          theme.menu(); theme.apply();
        });
      });
    }
  };

  /* ----------------------------------------------------------- me */
  var me = {
    role: "admin", name: "",
    load: function () {
      return api.get("/api/me").then(function (m) {
        me.role = m.role === "user" ? "user" : "admin";
        me.name = m.name || "";
      }).catch(function () { me.role = "admin"; });   /* older FORGE: one token, one role */
    },
    apply: function () {
      var admin = me.role === "admin";
      $("role").textContent = me.role;
      $("role").hidden = false;
      $("token-role").textContent = "you are " + me.role;
      document.querySelectorAll(".adm").forEach(function (n) { n.hidden = !admin; });
      document.querySelectorAll(".usr").forEach(function (n) { n.hidden = admin; });
      document.querySelector(".tabs a[data-view=do]").hidden = !admin;
    }
  };

  /* ----------------------------------------------------------- auth */
  var auth = {
    ok: false,
    lost: function () {
      if (!auth.ok && !$("login").hidden) return;
      auth.ok = false;
      events.stop();
      document.querySelectorAll(".view").forEach(function (v) { v.hidden = true; });
      $("logout").hidden = true;
      $("role").hidden = true;
      $("login").hidden = false;
      $("token").focus();
    },
    gained: function () {
      auth.ok = true;
      $("login").hidden = true;
      $("login-error").textContent = "";
      $("token").value = "";
      $("logout").hidden = false;
      me.load().then(function () {
        me.apply();
        theme.load();
        events.start();
        route.show(route.current(), true);
      });
    },
    init: function () {
      $("login-form").addEventListener("submit", function (ev) {
        ev.preventDefault();
        var tok = $("token").value;
        if (!tok) return;
        $("login-error").textContent = "";
        fetch("/api/login", { method: "POST", headers: api.headers, body: JSON.stringify({ token: tok }), credentials: "same-origin" })
          .then(function (r) {
            if (r.status === 204 || r.ok) return auth.gained();
            $("login-error").textContent = r.status === 401 ? "wrong token" : r.status === 429 ? "too many tries, wait a minute" : "HTTP " + r.status;
          }).catch(function (e) { $("login-error").textContent = String(e.message || e); });
      });
      $("logout").addEventListener("click", function () {
        api.post("/api/logout").catch(function () { /* the cookie is gone either way */ }).then(auth.lost);
      });
    }
  };

  /* ----------------------------------------------------------- events */
  var events = {
    src: null,
    start: function () {
      events.stop();
      var s = new EventSource("/api/events");
      s.addEventListener("bar", function (e) { try { $("bar").textContent = JSON.parse(e.data).line || ""; } catch (x) { /* skip */ } });
      s.addEventListener("check", function (e) {
        try { monitor.tally(JSON.parse(e.data)); } catch (x) { return; }
        if (route.current() === "monitor") monitor.loadCheck();
      });
      s.addEventListener("serve", function (e) {
        try { var d = JSON.parse(e.data); monitor.serveLive(d); } catch (x) { /* skip */ }
      });
      s.onerror = function () { if (s.readyState === 2) events.src = null; };
      events.src = s;
    },
    stop: function () { if (events.src) { events.src.close(); events.src = null; } }
  };

  /* ----------------------------------------------------------- run */
  var run = {
    busy: false,
    go: function (verb, args) {
      if (run.busy) return Promise.resolve();
      run.busy = true;
      var out = $("output");
      $("output-title").textContent = "output: spark " + [verb].concat(args || []).join(" ");
      out.textContent = "";
      out.scrollIntoView({ block: "nearest" });
      function line(s) { out.textContent += s + "\n"; out.scrollTop = out.scrollHeight; }
      return api.stream("/api/run", { verb: verb, args: args || [] }, {
        line: function (d) { line(typeof d === "string" ? d : (d.s === undefined ? JSON.stringify(d) : d.s)); },
        done: function (d) { line("[exit " + (d && d.rc !== undefined ? d.rc : "?") + "]"); }
      }).catch(function (e) {
        line(e.quiet ? String(e.message) : e.status === 404 ? "spark " + verb + " is not available yet on this FORGE" : "error: " + (e.message || e));
      }).then(function () { run.busy = false; config.load(); });
    },
    init: function () {
      document.addEventListener("click", function (ev) {
        var b = ev.target.closest ? ev.target.closest("button[data-run]") : null;
        if (!b) return;
        var args = b.getAttribute("data-args");
        run.go(b.getAttribute("data-run"), args ? args.split(" ") : []);
      });
      $("output-clear").addEventListener("click", function () { $("output").textContent = ""; $("output-title").textContent = "output"; });
    }
  };

  /* ----------------------------------------------------------- monitor */
  var GLYPH = { ok: "+", fail: "x", warn: "!", na: "-" };
  var CATS = ["SOFTWARE", "CAPABILITY", "NONFUNCTIONAL"];
  var monitor = {
    ts: 0, days: "1",
    load: function () {
      monitor.loadCheck();
      monitor.loadStats();
      if (me.role !== "admin") return;   /* serve/gpu/bench are admin cards */
      api.get("/api/serve").then(monitor.serve).catch(function (e) { fail($("serve-facts"), e); });
      api.get("/api/gpu").then(monitor.gpu).catch(function () { $("gpu-card").hidden = true; });
      api.get("/api/bench").then(monitor.bench).catch(function (e) { fail($("bench-facts"), e); });
    },
    loadCheck: function () {
      api.get("/api/check").then(function (c) {
        monitor.tally(c);
        var t = clear($("check-table")), rows = c.rows || [];
        CATS.concat(rows.map(function (r) { return r.category; }).filter(function (x, i, a) { return CATS.indexOf(x) < 0 && a.indexOf(x) === i; }))
          .forEach(function (cat) {
            var rs = rows.filter(function (r) { return r.category === cat; });
            if (!rs.length) return;
            t.appendChild(el("div", "cat", cat));
            rs.forEach(function (r) {
              var d = el("div", "r " + r.status);
              d.appendChild(el("span", "g " + r.status, GLYPH[r.status] || "?")).setAttribute("title", r.status);
              d.appendChild(el("span", "n", r.name));
              d.appendChild(el("span", "v", r.value));
              if (r.remedy && r.status !== "ok") d.appendChild(el("span", "rem", r.remedy));
              t.appendChild(d);
            });
          });
      }).catch(function (e) { fail($("check-table"), e); });
    },
    tally: function (c) {
      var k = c.counts || {};
      $("check-tally").textContent = (k.ok || 0) + " ok  " + (k.fail || 0) + " fail  " + (k.warn || 0) + " warn  " + (k.na || 0) + " na";
      monitor.ts = c.ts || 0;
      monitor.age();
    },
    age: function () {
      if (!monitor.ts) return;
      $("check-age").textContent = "age " + Math.max(0, Math.round(Date.now() / 1000 - monitor.ts)) + " s";
    },
    loadStats: function () {
      api.get("/api/stats?days=" + monitor.days).then(function (s) {
        var t = clear($("stats-tiles"));
        function tile(k, v, sub) {
          var d = el("div", "tile");
          d.appendChild(el("div", "k", k)); d.appendChild(el("div", "v", v));
          if (sub) d.appendChild(el("div", "s", sub));
          t.appendChild(d);
        }
        tile("turns", s.turns || 0);
        tile("generate tok/s", num(s.tg_mean), "p50 " + num(s.tg_p50) + "  p05 " + num(s.tg_p05));
        tile("prompt tok/s", num(s.pp_mean), "cache " + num(s.cache, 0) + " %");
        tile("latency ms", num(s.ms_p50, 0), "p95 " + num(s.ms_p95, 0));
        var b = s.baseline;
        tile("of baseline", b && b.tg && s.tg_mean ? num(100 * s.tg_mean / b.tg, 0) + " %" : "-", b ? "tg " + num(b.tg) + " " + (b.settings || "") : "no bench yet");
        var r = s.running || {};
        tile("running", r.ngl !== undefined ? keyOf(r) : "-", r.ngl !== undefined ? "" : "no server here");
      }).catch(function (e) { fail($("stats-tiles"), e); });
    },
    serve: function (s) {
      var dl = clear($("serve-facts"));
      fact(dl, "url", s.url); fact(dl, "health", s.health); fact(dl, "model", s.model);
      fact(dl, "service", s.service); fact(dl, "pids", (s.pids || []).join(" "));
      fact(dl, "mem free", s.mem_free_gb !== undefined && s.mem_free_gb !== null ? num(s.mem_free_gb) + " GB" : "-");
      var log = $("serve-log");
      log.textContent = (s.log || []).slice(-40).join("\n");
      log.scrollTop = log.scrollHeight;
    },
    serveLive: function (d) {
      var dds = $("serve-facts").querySelectorAll("dd");
      if (dds.length >= 2) { dds[0].textContent = d.url || "-"; dds[1].textContent = d.health || "-"; }
    },
    gpu: function (g) {
      var card = $("gpu-card");
      if (!g || !Object.keys(g).length) { card.hidden = true; return; }
      card.hidden = false;
      var dl = clear($("gpu-facts"));
      fact(dl, "name", g.name); fact(dl, "busy", g.busy !== undefined ? g.busy + " %" : "-");
      fact(dl, "vram", g.vram_total ? num(g.vram_used) + " / " + num(g.vram_total) + " GB" : "-");
      fact(dl, "gtt", g.gtt_total ? num(g.gtt_used) + " / " + num(g.gtt_total) + " GB" : "-");
    },
    bench: function (b) {
      var dl = clear($("bench-facts")), base = b.baseline, t = b.tune, box = clear($("tune-table"));
      if (base) {
        fact(dl, "baseline", "pp " + num(base.pp) + "  tg " + num(base.tg) + " tok/s");
        fact(dl, "settings", keyOf(base.settings)); fact(dl, "model", base.model);
        fact(dl, "size", base.size); fact(dl, "when", fmtTs(base.ts));
      } else fact(dl, "baseline", "none yet (spark bench)");
      if (!t || !t.table) { box.appendChild(el("p", "muted", "no tune run yet (spark bench --tune)")); return; }
      var now = keyOf(b.now || t.current), win = keyOf(t.winner);
      var tb = el("table"), tr = el("tr");
      ["settings", "pp", "tg", ""].forEach(function (h, i) { tr.appendChild(el("th", i && i < 3 ? "num" : null, h)); });
      tb.appendChild(tr);
      t.table.forEach(function (r) {
        var k = keyOf(r.settings), row = el("tr", k === win ? "win" : null);
        row.appendChild(el("td", "mono", k));
        row.appendChild(el("td", "num", num(r.pp))); row.appendChild(el("td", "num", num(r.tg)));
        row.appendChild(el("td", "muted", (k === win ? "winner " : "") + (k === now ? "now" : "")));
        tb.appendChild(row);
      });
      var wrap = el("div", "tbl"); wrap.appendChild(tb); box.appendChild(wrap);
      box.appendChild(el("p", "muted small", "tune " + fmtTs(t.ts) + ", " + t.model + " -- winner tg " + num(t.winner_tg) + ", pp " + num(t.winner_pp)));
    },
    init: function () {
      $("stats-days").addEventListener("change", function () { monitor.days = this.value; monitor.loadStats(); });
      $("check-refresh").addEventListener("click", function () {
        api.post("/api/check/refresh").catch(function () { /* older server: just re-read */ }).then(monitor.loadCheck);
      });
      setInterval(monitor.age, 1000);
    }
  };

  /* ----------------------------------------------------------- chat */
  var chat = {
    thread: null, busy: false,
    load: function () {
      api.get("/api/threads?n=30").then(function (d) {
        var ul = clear($("thread-list"));
        (d.threads || []).forEach(function (t) {
          var li = el("li"), b = el("button", "pick", t.title || t.id);
          b.type = "button"; b.setAttribute("data-id", t.id); b.setAttribute("aria-current", t.id === chat.thread ? "true" : "false");
          b.addEventListener("click", function () { chat.open(t.id); });
          li.appendChild(b);
          li.appendChild(el("span", "meta", (t.turns || 0) + " turns  " + fmtTs(t.ts)));
          ul.appendChild(li);
        });
        if (!(d.threads || []).length) ul.appendChild(el("li", "muted", "no threads yet"));
      }).catch(function (e) { e.status === 404 ? notYet($("thread-list"), "the thread list") : fail($("thread-list"), e); });
      if (chat.thread) chat.open(chat.thread);
    },
    open: function (id) {
      chat.thread = id;
      $("threads-toggle").setAttribute("aria-expanded", "false");
      $("view-chat").classList.remove("drawer");
      document.querySelectorAll("#thread-list .pick").forEach(function (b) {
        b.setAttribute("aria-current", b.getAttribute("data-id") === id ? "true" : "false");
      });
      api.get("/api/threads/" + encodeURIComponent(id)).then(function (d) {
        var tr = clear($("transcript"));
        (d.messages || []).forEach(function (m) { chat.msg(m.role, m.text, m.ms); });
        tr.scrollTop = tr.scrollHeight;
        $("chat-status").textContent = "thread " + id;
      }).catch(function (e) { fail($("transcript"), e); });
    },
    fresh: function () {
      chat.thread = null; clear($("transcript"));
      $("chat-status").textContent = "new thread";
      document.querySelectorAll("#thread-list .pick").forEach(function (b) { b.setAttribute("aria-current", "false"); });
      $("chat-text").focus();
    },
    msg: function (role, text, ms) {
      var d = el("div", "msg " + role);
      d.appendChild(el("div", "who", role));
      codeSpans(d.appendChild(el("div", "txt")), text || "");
      if (ms !== undefined) d.appendChild(el("div", "ms", ms + " ms"));
      var tr = $("transcript"); tr.appendChild(d); tr.scrollTop = tr.scrollHeight;
      return d;
    },
    send: function () {
      var ta = $("chat-text"), text = ta.value.trim();
      if (!text || chat.busy) return;
      chat.busy = true; ta.value = ""; chat.size();
      chat.msg("user", text);
      var d = chat.msg("assistant", ""), txt = d.querySelector(".txt"), acc = "", t0 = Date.now();
      $("chat-status").textContent = "sending";
      api.stream("/api/chat", chat.thread ? { thread: chat.thread, text: text } : { text: text }, {
        queued: function () { $("chat-status").textContent = "queued"; },
        delta: function (x) { acc += (x && x.t !== undefined) ? x.t : String(x); txt.textContent = acc; $("transcript").scrollTop = 1e9; $("chat-status").textContent = "answering"; },
        done: function (x) {
          codeSpans(clear(txt), acc);
          d.appendChild(el("div", "ms", (x && x.ms !== undefined ? x.ms : Date.now() - t0) + " ms" + (x && x.model ? "  " + x.model : "")));
          if (x && x.thread) chat.thread = x.thread;
          $("chat-status").textContent = "thread " + (chat.thread || "");
          chat.load();
        },
        error: function (x) { txt.textContent = "error: " + (x && (x.hint || x.kind) || x); $("chat-status").textContent = "error"; }
      }).catch(function (e) {
        txt.textContent = e.status === 404 ? "chat is not available yet on this FORGE" : "error: " + (e.message || e);
        $("chat-status").textContent = "";
      }).then(function () { chat.busy = false; ta.focus(); });
    },
    size: function () {
      var ta = $("chat-text"); ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight + 2, 192) + "px";
    },
    init: function () {
      var ta = $("chat-text");
      $("chat-form").addEventListener("submit", function (ev) { ev.preventDefault(); chat.send(); });
      ta.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); chat.send(); }
      });
      ta.addEventListener("input", chat.size);
      $("thread-new").addEventListener("click", chat.fresh);
      $("threads-toggle").addEventListener("click", function () {
        var on = $("view-chat").classList.toggle("drawer");
        this.setAttribute("aria-expanded", on ? "true" : "false");
      });
    }
  };

  /* ----------------------------------------------------------- do */
  var doView = {
    thread: null, busy: false, named: false,
    load: function () { /* nothing to fetch: a goal starts it */ },
    reset: function () { doView.thread = null; doView.named = false; clear($("do-steps")); },
    propose: function (text) {
      if (doView.busy) return;
      doView.busy = true;
      $("do-status").textContent = "thinking";
      var body = doView.thread ? { thread: doView.thread, text: text } : { text: text };
      api.post("/api/do/propose", body).then(function (d) {
        if (d.thread) doView.thread = d.thread;
        if (d.driver && !doView.named) {
          doView.named = true;
          $("do-steps").appendChild(el("div", "muted small", "driving with " + d.driver));
        }
        $("do-status").textContent = (d.ms !== undefined ? d.ms + " ms" : "") + (doView.thread ? "  thread " + doView.thread : "");
        doView.step(d.reply || {}, d.unchecked || []);
      }).catch(function (e) {
        $("do-status").textContent = e.quiet ? String(e.message) : e.status === 404 ? "do is not available yet on this FORGE" : "error: " + (e.message || e);
      }).then(function () { doView.busy = false; });
    },
    step: function (r, bad) {
      var box = $("do-steps"), n = box.querySelectorAll(".step").length + 1;
      if (r.kind === "done" || !r.command) {
        var dn = el("div", "step done");
        dn.appendChild(el("div", "cmd" + (bad && bad.length ? " warn" : ""), "done"));
        dn.appendChild(el("div", "hint", r.hint || ""));
        if (bad && bad.length) dn.appendChild(el("div", "muted small",
          "unchecked: no command produced " + bad.join(", ") + " -- believe the outputs above"));
        box.appendChild(dn);
        return;
      }
      var s = el("div", "step" + (r.danger ? " danger" : ""));
      var cmd = el("div", "cmd"); cmd.appendChild(el("span", "muted", n + "  ")); cmd.appendChild(el("code", null, r.command));
      s.appendChild(cmd);
      s.appendChild(el("div", "hint", r.hint || ""));
      var ctl = el("div", "ctl"), b = el("button", r.danger ? "danger" : null, r.danger ? "Run anyway" : "Run");
      b.type = "button"; ctl.appendChild(b);
      var note = el("span", "muted small", ""); ctl.appendChild(note);
      s.appendChild(ctl);
      var armed = 0;
      b.addEventListener("click", function () {
        if (r.danger && Date.now() - armed > 5000) {
          armed = Date.now(); b.classList.add("confirm"); note.textContent = "click again to confirm";
          setTimeout(function () { if (Date.now() - armed >= 5000) { b.classList.remove("confirm"); note.textContent = ""; } }, 5100);
          return;
        }
        b.disabled = true; note.textContent = "running";
        api.post("/api/do/run", { command: r.command }).then(function (d) {
          note.textContent = "";
          ctl.appendChild(el("span", "rc " + (d.rc === 0 ? "ok" : "fail"), "exit " + d.rc));
          var pre = el("pre", "log", d.tail || ""); s.appendChild(pre);
          var next = el("button", null, "next step"); next.type = "button";
          next.addEventListener("click", function () {
            next.disabled = true;
            doView.propose("Output of `" + r.command + "` (exit " + d.rc + "):\n" + (d.tail || ""));
          });
          s.appendChild(next); next.focus();
        }).catch(function (e) { b.disabled = false; note.textContent = e.quiet ? String(e.message) : "error: " + (e.message || e); });
      });
      box.appendChild(s); b.focus();
    },
    init: function () {
      $("do-form").addEventListener("submit", function (ev) {
        ev.preventDefault();
        var g = $("do-goal").value.trim();
        if (!g) return;
        doView.reset();
        doView.propose(g);
      });
    }
  };

  /* ----------------------------------------------------------- config */
  var config = {
    load: function () {
      if (me.role === "admin") api.get("/api/config").then(function (c) {
        var sel = clear($("theme-pick")), cur = (c.effective || {}).SITE_THEME || (c.site || {}).SITE_THEME || "";
        ["none"].concat(c.themes || []).forEach(function (n) { var o = el("option", null, n); o.value = n; sel.appendChild(o); });
        sel.value = cur || "none";
        var eff = c.effective || {};
        if (!$("font-face").value) $("font-face").value = eff.SITE_FONT_FACE || "";
        if (!$("font-size").value) $("font-size").value = eff.SITE_FONT_SIZE || "";
        var box = clear($("model-table")), tb = el("table"), tr = el("tr");
        ["model", "GB", "needs RAM", "fits", "downloaded", "state", ""].forEach(function (h, i) { tr.appendChild(el("th", i === 1 || i === 2 ? "num" : null, h)); });
        tb.appendChild(tr);
        (c.models || []).forEach(function (m) {
          var row = el("tr", m.chosen ? "chosen" : null);
          row.appendChild(el("td", "mono", (m.role === "spark" ? "* " : m.role === "ember" ? "+ " : "") + m.name));
          row.appendChild(el("td", "num", num(m.gb))); row.appendChild(el("td", "num", num(m.ram_gb, 0)));
          row.appendChild(el("td", m.fits ? "ok" : "warn", m.fits ? "yes" : "no"));
          row.appendChild(el("td", null, m.downloaded ? "yes" : "-"));
          row.appendChild(el("td", null, (m.serving ? "serving " : "") + (m.chosen ? "chosen" : "")));
          var td = el("td"), b = el("button", "quiet", "choose"); b.type = "button";
          b.setAttribute("data-run", "model"); b.setAttribute("data-args", m.name);
          td.appendChild(b); row.appendChild(td); tb.appendChild(row);
        });
        var wrap = el("div", "tbl"); wrap.appendChild(tb); box.appendChild(wrap);
        if ((c.models || []).some(function (m) { return m.role; }))
          box.appendChild(el("p", "muted small", "marks: * the spark (prompt line), + the ember (conversations)"));
        var ep = clear($("ember-pick"));
        ["auto", "none"].concat((c.models || []).map(function (m) { return m.name; })).forEach(function (n) {
          var o = el("option", null, n); o.value = n; ep.appendChild(o);
        });
        ep.value = eff.SITE_EMBER_MODEL || "auto";
        var dl = clear($("config-facts"));
        fact(dl, "prompt", c.off ? "off" : "on"); fact(dl, "service", c.service);
        fact(dl, "model", eff.SITE_AI_MODEL); fact(dl, "ember", eff.SITE_EMBER_MODEL || "auto");
        fact(dl, "theme", cur || "none");
        fact(dl, "quiet boot", eff.SITE_QUIET_BOOT); fact(dl, "quiet login", eff.SITE_QUIET_LOGIN);
      }).catch(function (e) { fail($("model-table"), e); });
      api.get("/api/soul").then(function (s) {
        $("soul-text").value = typeof s === "string" ? s : (s.text || "");
        $("soul-status").textContent = "";
      }).catch(function (e) { $("soul-status").textContent = e.status === 404 ? "the soul editor is not available yet" : "error: " + (e.message || e); });
      config.memory();
    },
    memory: function () {
      api.get("/api/memory").then(function (m) {
        var ul = clear($("memory-list"));
        (m.facts || []).forEach(function (f, i) {
          var li = el("li"), x = el("button", "x", "x"), n = (typeof f === "object" && f.n !== undefined) ? f.n : i + 1;
          x.type = "button"; x.setAttribute("aria-label", "forget " + n);
          x.addEventListener("click", function () { api.del("/api/memory/" + n).then(config.memory).catch(function (e) { fail(ul, e); }); });
          li.appendChild(el("span", "meta", n));
          li.appendChild(el("span", "pick", typeof f === "object" ? (f.text || f.fact || JSON.stringify(f)) : f));
          li.appendChild(x); ul.appendChild(li);
        });
        if (!(m.facts || []).length) ul.appendChild(el("li", "muted", "nothing remembered"));
      }).catch(function (e) { e.status === 404 ? notYet($("memory-list"), "memory") : fail($("memory-list"), e); });
    },
    init: function () {
      $("theme-form").addEventListener("submit", function (ev) { ev.preventDefault(); run.go("theme", [$("theme-pick").value]).then(theme.load); });
      $("ember-pick").addEventListener("change", function () { run.go("ember", [this.value]); });
      $("font-form").addEventListener("submit", function (ev) {
        ev.preventDefault();
        var f = $("font-face").value.trim(), s = $("font-size").value.trim();
        if (f === "none" || (f && !s)) run.go("font", [f]); else if (f && s) run.go("font", [f, s]);
      });
      $("soul-save").addEventListener("click", function () {
        $("soul-status").textContent = "saving";
        api.post("/api/soul", { text: $("soul-text").value }).then(function () { $("soul-status").textContent = "saved"; })
          .catch(function (e) { $("soul-status").textContent = "error: " + (e.message || e); });
      });
      $("memory-form").addEventListener("submit", function (ev) {
        ev.preventDefault();
        var t = $("memory-text").value.trim();
        if (!t) return;
        api.post("/api/memory", { text: t }).then(function () { $("memory-text").value = ""; config.memory(); })
          .catch(function (e) { fail($("memory-list"), e); });
      });
    }
  };

  /* ----------------------------------------------------------- help */
  var help = {
    load: function () { $("help-health").textContent = location.origin + "/api/health"; },
    init: function () { }
  };

  /* ----------------------------------------------------------- route */
  var VIEWS = { monitor: monitor, chat: chat, "do": doView, config: config, help: help };
  var ORDER = ["monitor", "chat", "do", "config", "help"];
  var route = {
    current: function () {
      var h = location.hash.replace(/^#\/?/, "").split("/")[0];
      return VIEWS[h] ? h : "monitor";
    },
    show: function (name, load) {
      document.querySelectorAll(".tabs a").forEach(function (a) {
        if (a.getAttribute("data-view") === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
      });
      if (!auth.ok) return;
      ORDER.forEach(function (v) { $("view-" + v).hidden = v !== name; });
      if (load !== false) VIEWS[name].load();
    },
    go: function (name) { location.hash = "#/" + name; },
    keys: function (ev) {
      var t = ev.target, typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if (ev.key === "Escape") { if (typing) t.blur(); return; }
      if (typing || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      var n = parseInt(ev.key, 10);
      if (n >= 1 && n <= 5) {
        if (me.role === "admin" || ORDER[n - 1] !== "do") route.go(ORDER[n - 1]);
        ev.preventDefault(); return;
      }
      if (ev.key === "/") {
        var v = $("view-" + route.current()), inp = v && v.querySelector("[data-main]");
        if (inp) { inp.focus(); ev.preventDefault(); }
        return;
      }
      if (ev.key === "r") { route.show(route.current()); ev.preventDefault(); return; }
      if (ev.key === "?") { route.go("help"); ev.preventDefault(); }
    },
    init: function () {
      window.addEventListener("hashchange", function () { route.show(route.current()); });
      document.addEventListener("keydown", route.keys);
    }
  };

  /* ----------------------------------------------------------- boot */
  function boot() {
    theme.init(); auth.init(); run.init(); route.init();
    ORDER.forEach(function (v) { VIEWS[v].init(); });
    api.get("/api/health").then(function (h) {
      var mm = h.model ? "  " + h.model : "";
      if (h.roles) {
        var rk = ["spark", "ember"].concat(Object.keys(h.roles).filter(function (k) { return k !== "spark" && k !== "ember"; }));
        var rr = rk.filter(function (k) { return h.roles[k]; }).map(function (k) { return k + " " + h.roles[k]; });
        if (rr.length) mm = "  " + rr.join(" \u00b7 ");
      }
      $("site").textContent = (h.name || "") + (h.version ? "  v" + h.version : "") + mm;
      document.title = "spark" + (h.name ? " " + h.name : "");
    }).catch(function () { $("site").textContent = "no FORGE answers"; });
    api.get("/api/bar").then(function (b) { $("bar").textContent = b.line || ""; auth.gained(); })
      .catch(function () { /* 401 already showed the login card */ });
    route.show(route.current(), false);
  }
  boot();
})();
