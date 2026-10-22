/* spark FORGE page. Vanilla ES2017, no build, no external resource, ASCII
   only (Unicode via \u escapes). Chat is the front door for every role;
   activity, do, settings and help sit beside it. Modules by convention,
   top to bottom:
     dom     - element helpers (textContent only, never innerHTML)
     api     - get/post/del/stream, one shape; 401 -> login
     theme   - night or day: the system's choice, or the viewer's,
               kept in this browser (the colors live in tokens.css)
     face    - spark's face in the bar: the machine's own frames,
               asleep, awake, thinking, pleased, alarmed
     auth    - the login card (the cookie);
               /login#t=<token> signs in once from the URL fragment, which
               is stripped before routing and never reaches the server
     me      - GET /api/me: the role behind the cookie; .adm/.usr rendering
     events  - GET /api/events (EventSource) -> live cards
     run     - POST /api/run: one verb's output streamed into #output
     chat, monitor, doView, config, help - the five views
     route   - hash routes and the keyboard map (chat is the default)
   Contract: the route table in CLAUDE.md contract 9. Any 404 on a route
   that lands in a later step shows "not available yet" in place. */
(function () {
  "use strict";

  /* the login link's token rides the URL fragment (#t=...): read it and
     strip it before anything else can observe location -- the fragment
     never reaches the server, and replaceState keeps it out of history.
     ANY #t= fragment is stripped, whatever its shape: a short
     operator-chosen token must not stay in the address bar and history.
     A non-empty one gets its one login attempt (auth.fromLink shows
     "the link's token was refused" when it does not take). */
  var linkToken = "";
  if (location.hash.slice(0, 3) === "#t=") {
    linkToken = location.hash.slice(3);
    history.replaceState(null, "", location.pathname + location.search);
  }

  /* ----------------------------------------------------------- dom */
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }
  /* a stream follows the end only while the reader is there: one who
     scrolled up to read stays where they are, one who comes back is
     followed again */
  function atEnd(node) { return node.scrollHeight - node.scrollTop - node.clientHeight < 24; }
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
  /* fenced block: pre.fence with a copy button; textContent only */
  function fenceBlock(code) {
    var pre = el("pre", "fence"), b = el("button", "quiet copy", "copy");
    b.type = "button";
    b.addEventListener("click", function () {
      function done() { b.textContent = "copied"; setTimeout(function () { b.textContent = "copy"; }, 1500); }
      if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(code).then(done, done); return; }
      var ta = document.createElement("textarea");   /* LAN http: no async clipboard */
      ta.value = code; ta.setAttribute("readonly", "");
      ta.style.position = "fixed"; ta.style.left = "-999px";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch (x) { /* nothing to do */ }
      document.body.removeChild(ta); done();
    });
    pre.appendChild(b);
    pre.appendChild(el("code", null, code));
    return pre;
  }
  /* prose + ``` fences; the split is on lines, textContent everywhere */
  function rich(node, text) {
    var lines = String(text).split("\n"), buf = [], fence = false, i;
    function flush() { if (buf.length) codeSpans(node, buf.join("\n")); buf = []; }
    for (i = 0; i < lines.length; i++) {
      if (lines[i].slice(0, 3) === "```") {
        if (fence) { node.appendChild(fenceBlock(buf.join("\n"))); buf = []; }
        else flush();
        fence = !fence;
        continue;
      }
      buf.push(lines[i]);
    }
    if (fence) node.appendChild(fenceBlock(buf.join("\n")));   /* unclosed fence still renders */
    else flush();
    return node;
  }
  /* a QR matrix (rows of 0 light / 1 dark) as an SVG: one square per
     dark module, the spec's quiet zone of 4; black on the white box
     .qr gives it, in either theme, so a phone's camera reads it */
  function qrSvg(m) {
    var NS = "http://www.w3.org/2000/svg", n = m.length, q = 4, x, y, r;
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + (n + 2 * q) + " " + (n + 2 * q));
    svg.setAttribute("shape-rendering", "crispEdges");
    for (y = 0; y < n; y++) {
      for (x = 0; x < n; x++) {
        if (!m[y][x]) continue;
        r = document.createElementNS(NS, "rect");
        r.setAttribute("x", x + q); r.setAttribute("y", y + q);
        r.setAttribute("width", 1); r.setAttribute("height", 1);
        r.setAttribute("fill", "#000000");
        svg.appendChild(r);
      }
    }
    return svg;
  }
  function notYet(node, what) {
    clear(node).appendChild(el("p", "muted", (what || "this") + " is not available yet on this server"));
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
      if (r.status === 400 || r.status === 409) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          var h = new Error((j && j.error && (j.error.hint || j.error.kind)) || "HTTP " + r.status);
          h.status = r.status; throw h;
        });
      }
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
    /* POST that answers with text/event-stream; on = {event: fn(data)}.
       ctl, when given, gains .abort(); an abort resolves quietly. */
    stream: function (path, body, on, ctl) {
      var c = typeof AbortController === "function" ? new AbortController() : null;
      if (ctl && c) ctl.abort = function () { c.abort(); };
      return fetch(path, { method: "POST", headers: api.headers, body: JSON.stringify(body || {}), credentials: "same-origin", signal: c ? c.signal : undefined })
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
        })
        .catch(function (e) { if (e && e.name === "AbortError") return; throw e; });
    }
  };

  /* ----------------------------------------------------------- theme */
  /* night or day: the system's choice until the viewer picks one with
     the bar's button; the pick is kept in this browser (theme.js reads
     it before first paint). The colors themselves live in tokens.css. */
  var theme = {
    KEY: "spark-theme",
    dark: function () {
      var t = document.documentElement.getAttribute("data-theme");
      if (t === "light" || t === "dark") return t === "dark";
      return !(window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches);
    },
    label: function () { $("theme").textContent = theme.dark() ? "light" : "dark"; },
    init: function () {
      theme.label();
      $("theme").addEventListener("click", function () {
        var next = theme.dark() ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        try { localStorage.setItem(theme.KEY, next); } catch (e) { /* fine */ }
        theme.label();
      });
      if (window.matchMedia) {
        var mq = window.matchMedia("(prefers-color-scheme: light)");
        if (mq.addEventListener) mq.addEventListener("change", theme.label);
      }
    }
  };

  /* ----------------------------------------------------------- face */
  /* spark's face in the bar: the machine's own frames (/api/me), the
     prompt's blink and glance (look.Busy.face), a tick of 0.12 s.
     Asleep until a login and after 30 s of nothing; thinking while an
     answer streams or a verb runs; pleased for a moment when it lands,
     alarmed for a moment on an error. Face only: no words, no sound. */
  var FACES = { asleep: "(-.-)z", waking: "(-o-)", idle: "(o.o)", thinking: "(o.O)", pleased: "(^.^)",
                puzzled: "(o.?)", alarmed: "(O.O)", listening: "(o.o)~", blink: "(-.-)", glance: "(.o.)" };
  var face = {
    faces: FACES, blink: 14, mood: "asleep", i: 0, until: 0, last: 0, busy: 0,
    NAP: 30000, TICK: 120,
    still: function () { return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); },
    set: function (m, ms) { face.mood = m; face.i = 0; face.until = ms ? Date.now() + ms : 0; face.draw(); },
    frame: function () {
      var f = face.faces, m = face.mood, b = face.still() ? 0 : face.blink, i = face.i;
      if (m === "waking") return i < 8 ? f.asleep : f.waking;
      if (b && i && (m === "idle" || m === "thinking")) {
        if (i % (3 * b) === 0 || (b > 2 && i > 1 && (i - 1) % (3 * b) === 0)) return f.glance;
        if (i % b === 0) return f.blink;
      }
      return f[m] || f.idle;
    },
    draw: function () {
      var n = $("face");
      n.textContent = face.frame();
      n.className = "face " + face.mood;
    },
    tick: function () {
      face.i++;
      if (face.mood === "waking" && face.i >= 16) face.set(face.busy ? "thinking" : "idle");
      else if (face.until && Date.now() >= face.until) face.set(face.busy ? "thinking" : "idle");
      else if (face.mood === "idle" && !face.busy && Date.now() - face.last > face.NAP) face.set("asleep");
      else face.draw();
    },
    touch: function () {   /* a key or a tap anywhere: stay awake, or wake up */
      face.last = Date.now();
      if (auth.ok && face.mood === "asleep") face.set("waking");
    },
    sleep: function () { face.busy = 0; face.set("asleep"); },
    think: function () { face.busy++; face.last = Date.now(); if (!face.until) face.set("thinking"); },
    done: function (ok) {
      face.busy = Math.max(0, face.busy - 1); face.last = Date.now();
      face.set(ok ? "pleased" : "alarmed", 2200);
    },
    load: function (m) {   /* the machine's own faces, from /api/me; the kit's until then */
      var f = {}, k;
      for (k in FACES) f[k] = (m && m.faces && typeof m.faces[k] === "string" && m.faces[k]) ? m.faces[k] : FACES[k];
      face.faces = f;
      if (m && typeof m.blink === "number" && m.blink >= 0) face.blink = m.blink;
      face.draw();
    },
    init: function () {
      face.draw();
      setInterval(face.tick, face.TICK);
      ["keydown", "pointerdown"].forEach(function (ev) { document.addEventListener(ev, face.touch, true); });
    }
  };

  /* ----------------------------------------------------------- me */
  var me = {
    role: "admin", name: "", user: "", newest: "",
    load: function () {
      return api.get("/api/me").then(function (m) {
        me.role = m.role === "user" ? "user" : "admin";
        me.name = m.name || "";
        me.user = m.user || "";
        me.newest = typeof m.newest === "string" ? m.newest : "";
        face.load(m);
      }).catch(function () { me.role = "admin"; });   /* older FORGE: one token, one role */
    },
    apply: function () {
      var admin = me.role === "admin";
      $("role").textContent = me.user ? me.user + " (user)" : me.role;
      $("token-role").textContent = "you are " + (me.user ? me.user + " (user)" : me.role);
      $("account-name").textContent = me.user;
      $("hello-hi").textContent = "hi" + (me.user ? ", " + me.user : "");
      siteLine();
      help.keys();
      document.querySelectorAll(".adm").forEach(function (n) { n.hidden = !admin; });
      document.querySelectorAll(".usr").forEach(function (n) { n.hidden = admin; });
      /* a guest's page is the chat: the menu offers only their account
         and help; activity and do are the admin's */
      ["monitor", "do"].forEach(function (v) {
        document.querySelector(".tabs a[data-view=" + v + "]").hidden = !admin;
      });
      /* what left this machine is every role's to read: a user has no
         activity page, so the card sits under their settings */
      var sends = $("sends-card"), home = admin ? $("view-monitor") : $("view-config");
      if (sends.parentNode !== home) {
        if (admin) home.insertBefore(sends, $("serve-facts").closest(".two"));
        else home.insertBefore(sends, $("account-card").nextSibling);
      }
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
      $("nav-btn").hidden = true;
      route.menu(false);
      $("login").hidden = false;
      $("login-wait").hidden = true;
      document.body.classList.add("logged-out");
      face.sleep();
      siteLine();
      $("token").focus();
    },
    gained: function () {
      auth.ok = true;
      $("login").hidden = true;
      $("login-error").textContent = "";
      $("token").value = "";
      $("logout").hidden = false;
      $("nav-btn").hidden = false;
      document.body.classList.remove("logged-out");
      me.load().then(function () {
        me.apply();
        face.touch();
        events.start();
        route.show(route.current(), true);
      });
    },
    /* one web login attempt; resolves true on success, else writes the
       error line and resolves false (the form and the link share it) */
    submit: function (tok) {
      $("login-error").textContent = "";
      return fetch("/api/login", { method: "POST", headers: api.headers, body: JSON.stringify({ token: tok }), credentials: "same-origin" })
        .then(function (r) {
          if (r.status === 204 || r.ok) { auth.gained(); return true; }
          $("login-error").textContent = r.status === 401 ? "wrong token"
            : r.status === 429 ? "too many tries -- wait a minute" : "HTTP " + r.status;
          return false;
        }).catch(function (e) { $("login-error").textContent = String(e.message || e); return false; });
    },
    /* the QR / login link: exactly ONE attempt, never retried -- a
       stale link is one 401, not a lockout spiral */
    fromLink: function (tok) {
      auth.lost();
      $("login-wait").hidden = false;
      auth.submit(tok).then(function (okay) {
        $("login-wait").hidden = true;
        if (!okay && $("login-error").textContent === "wrong token")
          $("login-error").textContent = "the link's token was refused -- paste a token instead";
      });
    },
    init: function () {
      $("login-form").addEventListener("submit", function (ev) {
        ev.preventDefault();
        var tok = $("token").value;
        if (!tok) return;
        auth.submit(tok);
      });
      $("token-show").addEventListener("click", function () {
        var t = $("token"), show = t.type === "password";
        t.type = show ? "text" : "password";
        this.textContent = show ? "hide" : "show";
        this.setAttribute("aria-pressed", show ? "true" : "false");
        this.setAttribute("aria-label", (show ? "hide" : "show") + " the token");
        t.focus();
      });
      $("logout").addEventListener("click", function () {
        api.post("/api/logout").catch(function () { /* the cookie is gone either way */ }).then(auth.lost);
      });
    }
  };

  /* ----------------------------------------------------------- events */
  var events = {
    src: null,
    handle: function (ev, d) {
      if (ev === "check") {
        try { monitor.tally(d); } catch (x) { return; }
        if (route.current() === "monitor") monitor.loadCheck();
      } else if (ev === "serve") monitor.serveLive(d || {});
    },
    start: function () {
      events.stop();
      var s = new EventSource("/api/events");
      ["check", "serve"].forEach(function (ev) {
        s.addEventListener(ev, function (e) {
          var d; try { d = JSON.parse(e.data); } catch (x) { return; }
          events.handle(ev, d);
        });
      });
      s.onerror = function () { if (s.readyState === 2) events.src = null; };
      events.src = s;
    },
    stop: function () { if (events.src) { events.src.close(); events.src = null; } }
  };

  /* ----------------------------------------------------------- run */
  var run = {
    busy: false, ctl: null, stopping: false,
    /* Esc while a verb streams: abort settles the stream quietly on
       both hosts, so busy can never stick on a dead connection */
    stop: function () {
      if (!run.busy || !run.ctl || !run.ctl.abort) return;
      run.stopping = true;
      run.ctl.abort();
    },
    go: function (verb, args) {
      if (run.busy) return Promise.resolve();
      run.busy = true; run.stopping = false;
      var restarts = verb === "update" || (verb === "serve" && (args || [])[0] === "https"), ended = false;
      var out = $("output");
      $("output-title").textContent = "output: spark " + [verb].concat(args || []).join(" ");
      out.textContent = "";
      face.think();
      out.scrollIntoView({ block: "nearest" });
      /* append, never replace: #output is aria-live, and a rewrite
         makes AT re-announce the whole log on every line */
      function line(s) { var follow = atEnd(out); out.appendChild(document.createTextNode(s + "\n")); if (follow) out.scrollTop = out.scrollHeight; }
      run.ctl = {};
      return api.stream("/api/run", { verb: verb, args: args || [] }, {
        line: function (d) { line(typeof d === "string" ? d : (d.s === undefined ? JSON.stringify(d) : d.s)); },
        done: function (d) { ended = true; line("[exit " + (d && d.rc !== undefined ? d.rc : "?") + "]"); },
        error: function (d) { ended = true; line("error: " + ((d && (d.hint || d.kind)) || d)); }   /* the desktop core reports as an error pair */
      }, run.ctl).catch(function (e) {
        if (restarts && !ended && !run.stopping) return;   /* the server went down under the stream: expected */
        line(e.quiet ? String(e.message) : e.status === 404 ? "spark " + verb + " is not available yet on this server" : "error: " + (e.message || e));
      }).then(function () {
        if (run.stopping) { run.stopping = false; line("[stopped]"); }
        face.done(true);
        run.busy = false; run.ctl = null;
        if (restarts && !ended) run.back(verb, line);
        else config.load();
      });
    },
    /* the page's server restarted under the verb (update; serve https own):
       the sessions went with it. Over https the address changed too, and
       this http page cannot ask the new server anything, so it says
       where to go; after an update it waits for /api/health and shows the
       login with the version that came back */
    back: function (verb, line) {
      var host = location.hostname, port = parseInt(location.port, 10) || (location.protocol === "https:" ? 443 : 80);
      if (verb === "serve") {
        line("the page restarts over https. Open https://" + host + ":" + port + "/login and log in again.");
        line("Each phone installs the root first: open http://" + host + ":" + (port + 1) + "/ca there.");
        return;
      }
      line("the page restarts -- waiting for it");
      var tries = 0;
      (function poll() {
        api.get("/api/health").then(function (h) {
          siteLine(h);
          auth.lost();
          var w = $("login-wait");
          w.textContent = "spark " + (h.version || "") + " is back. Log in again.";
          w.hidden = false;
        }).catch(function () {
          if (++tries < 60) setTimeout(poll, 2000);
          else line("the page did not come back in two minutes -- spark serve on the machine says why");
        });
      })();
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
  var GLYPH = { ok: "\u2713", fail: "\u2717", warn: "!", na: "\u2013" };
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
        monitor.sends(s.sends || [], s.days);
      }).catch(function (e) { fail($("stats-tiles"), e); });
    },
    /* what left this machine: the rows of `spark stats --sends` for the
       window, bytes out by destination and day, never a word of it */
    sends: function (rows, days) {
      var box = clear($("sends-table"));
      if (!rows.length) {
        box.appendChild(el("p", "muted", "nothing sent " + (days === 1 ? "today" : days === 7 ? "this week" : "yet")));
        return;
      }
      var tb = el("table"), tr = el("tr");
      ["day", "destination", "kB", "turns"].forEach(function (h, i) { tr.appendChild(el("th", i >= 2 ? "num" : null, h)); });
      tb.appendChild(tr);
      rows.forEach(function (r) {
        var row = el("tr");
        row.appendChild(el("td", "mono", r.day)); row.appendChild(el("td", "mono", r.dest));
        row.appendChild(el("td", "num", num(r.bytes / 1000))); row.appendChild(el("td", "num", String(r.turns)));
        tb.appendChild(row);
      });
      var wrap = el("div", "tbl"); wrap.appendChild(tb); box.appendChild(wrap);
    },
    loadSends: function (days) {   /* a user's settings page: the week, as the terminal prints it */
      api.get("/api/stats?days=" + days).then(function (s) { monitor.sends(s.sends || [], s.days); })
        .catch(function (e) { fail($("sends-table"), e); });
    },
    serve: function (s) {
      var dl = clear($("serve-facts"));
      fact(dl, "url", s.url); fact(dl, "health", s.health); fact(dl, "model", s.model);
      fact(dl, "service", s.service); fact(dl, "pids", (s.pids || []).join(" "));
      fact(dl, "mem free", s.mem_free_gb !== undefined && s.mem_free_gb !== null ? num(s.mem_free_gb) + " GB" : "-");
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
      if (!t || !t.table) { box.appendChild(el("p", "muted", "no tune yet (spark bench tune)")); return; }
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
    thread: null, busy: false, ctl: null, stopping: false,
    listHead: undefined,   /* newest thread id from the last completed list load; undefined = never loaded, null = loaded and empty */
    titles: {},            /* id -> title, from the last list load: the status line names a chat by it */
    /* the status line: one writer, so the error color never lingers.
       unchanged text writes nothing: the line is aria-live, and even a
       same-string textContent swap is a mutation AT re-announces (the
       per-delta "answering" lands here) */
    status: function (text, isErr) {
      var p = $("chat-status");
      if (p.textContent === text && p.classList.contains("err") === !!isErr) return;
      p.textContent = text;
      p.classList.toggle("err", !!isErr);
    },
    load: function () {
      chat.list();
      if (chat.thread) chat.open(chat.thread);
      else chat.hello(!$("transcript").firstChild);
    },
    /* the greeting and its suggestion chips: shown on an empty chat,
       gone the moment a message lands */
    hello: function (on) { $("hello").hidden = !on; },
    /* refresh the thread list only: the open transcript stays as it is */
    list: function () {
      api.get("/api/threads?n=30").then(function (d) {
        chat.listHead = (d.threads || []).length ? d.threads[0].id : null;
        chat.titles = {};
        var ul = clear($("thread-list"));
        (d.threads || []).forEach(function (t) {
          chat.titles[t.id] = t.title || "";
          var li = el("li"), b = el("button", "pick", t.title || t.id);
          b.type = "button"; b.setAttribute("data-id", t.id); b.setAttribute("aria-current", t.id === chat.thread ? "true" : "false");
          b.addEventListener("click", function () { chat.open(t.id); });
          li.appendChild(b);
          li.appendChild(el("span", "meta", (t.turns || 0) + " turns  " + fmtTs(t.ts)));
          ul.appendChild(li);
        });
        if (!(d.threads || []).length) ul.appendChild(el("li", "muted", "no chats yet"));
      }).catch(function (e) { e.status === 404 ? notYet($("thread-list"), "the chat list") : fail($("thread-list"), e); });
    },
    /* open and fresh no-op while an answer streams: they would detach
       the live row and swap the thread out from under the stream (n,
       j/k, r and the thread picks all land here) -- Esc stops first */
    open: function (id) {
      if (chat.busy) return;
      chat.thread = id;
      chat.drawer(false);
      document.querySelectorAll("#thread-list .pick").forEach(function (b) {
        b.setAttribute("aria-current", b.getAttribute("data-id") === id ? "true" : "false");
      });
      api.get("/api/threads/" + encodeURIComponent(id)).then(function (d) {
        var tr = clear($("transcript"));
        (d.messages || []).forEach(function (m) { chat.msg(m.role, m.text, m.ms); });
        tr.scrollTop = tr.scrollHeight;
        chat.status(chat.titles[id] || "chat");
      }).catch(function (e) { fail($("transcript"), e); });
    },
    fresh: function () {
      if (chat.busy) return;
      chat.thread = null; clear($("transcript"));
      chat.hello(true);
      chat.status("new chat");
      document.querySelectorAll("#thread-list .pick").forEach(function (b) { b.setAttribute("aria-current", "false"); });
      $("chat-text").focus();
    },
    drawer: function (on) {
      /* closing must not strand focus on a hidden node: hand it back
         to the toggle, the disclosure pattern's trigger */
      if (!on && $("view-chat").classList.contains("drawer") && $("threads").contains(document.activeElement))
        $("threads-toggle").focus();
      $("view-chat").classList.toggle("drawer", !!on);
      $("threads-toggle").setAttribute("aria-expanded", on ? "true" : "false");
    },
    /* one transcript row: avatar mark + bubble; the role stays for AT */
    msg: function (role, text, ms) {
      chat.hello(false);
      var d = el("div", "msg " + role);
      var mk = el("span", "m", role === "assistant" ? "*" : role === "user" ? ">" : "!");
      mk.setAttribute("aria-hidden", "true");
      d.appendChild(mk);
      d.appendChild(el("span", "vh", role));
      rich(d.appendChild(el("div", "txt")), text || "");
      if (ms !== undefined) d.appendChild(el("div", "ms", ms + " ms"));
      var tr = $("transcript"); tr.appendChild(d); tr.scrollTop = tr.scrollHeight;
      return d;
    },
    streamOn: function (on) { $("chat-stop").hidden = !on; $("chat-send").hidden = on; },
    stop: function () {
      if (!chat.busy || !chat.ctl || !chat.ctl.abort) return;
      chat.stopping = true;
      chat.ctl.abort();
    },
    /* the server's forge._title, byte for byte: a thread's title is
       its first user line, whitespace collapsed, capped at 60 */
    title: function (s) {
      s = String(s || "").split(/\s+/).filter(Boolean).join(" ");
      return s.length <= 60 ? s : s.slice(0, 57) + "...";
    },
    /* after stopping the first turn of a new thread the FORGE usually
       kept nothing -- adopt the newest thread only when it is not the
       head the last completed list load saw before sending AND its
       title matches the text this send opened with (the FORGE is
       multi-client: a head that merely differs could be another
       client's new thread -- the prompt, a phone -- and adopting it
       would append our next message there; `before` is null only when
       that load answered empty -- while the list has never loaded the
       caller skips adoption instead, so a pre-existing thread is
       never mistaken for ours); no wall-clock compare: the server's
       ts is its local time, not ours. the list alone is refreshed,
       keeping the stopped partial on screen */
    adopt: function (before, text) {
      api.get("/api/threads?n=1").then(function (d) {
        if (chat.busy) return;   /* a newer send owns the thread and the status now */
        var t = (d.threads || [])[0];
        if (t && t.id !== before && t.title === chat.title(text)) chat.thread = t.id;
        chat.status(chat.thread ? chat.title(text) : "new chat");
        chat.list();
      }).catch(function () {
        if (!chat.busy) chat.status(chat.thread ? chat.title(text) : "new chat");
        chat.list();
      });
    },
    send: function () {
      var ta = $("chat-text"), text = ta.value.trim();
      if (!text || chat.busy) return;
      chat.busy = true; chat.stopping = false; ta.value = ""; chat.size();
      var wasNew = !chat.thread;
      var before = chat.listHead;   /* undefined while the list has never loaded */
      chat.msg("user", text);
      var d = chat.msg("assistant", ""), txt = d.querySelector(".txt"), acc = "", t0 = Date.now(), fin = false;
      d.classList.add("streaming");
      chat.streamOn(true);
      chat.ctl = {};
      chat.status("answering");
      face.think();
      api.stream("/api/chat", chat.thread ? { thread: chat.thread, text: text } : { text: text }, {
        queued: function () { chat.status("waiting for another chat to finish"); },
        /* append the fragment, never rewrite: #transcript is
           aria-live, and a rewrite re-announces the whole answer per
           token; rich() re-renders once, on done */
        delta: function (x) {
          var t = (x && x.t !== undefined) ? x.t : String(x), tr = $("transcript"), follow = atEnd(tr);
          acc += t; txt.appendChild(document.createTextNode(t));
          if (follow) tr.scrollTop = tr.scrollHeight;
          chat.status("answering");
        },
        done: function (x) {
          var tr = $("transcript"), follow = atEnd(tr);
          rich(clear(txt), acc);
          d.appendChild(el("div", "ms", (x && x.ms !== undefined ? x.ms : Date.now() - t0) + " ms" + (x && x.model ? "  " + x.model : "")));
          if (follow) tr.scrollTop = tr.scrollHeight;
          if (x && x.thread) chat.thread = x.thread;
          chat.status(chat.titles[chat.thread] || chat.title(text));
          fin = true;   /* reload after busy clears: open is guarded while streaming */
        },
        error: function (x) {
          /* a cut still landed the partial: adopt the thread the error
             names, so the next message continues it instead of opening
             a new one */
          if (x && x.thread) { chat.thread = x.thread; fin = true; }
          d.classList.add("error"); mkBang(d);
          txt.textContent = "error: " + (x && (x.hint || x.kind) || x);
          chat.status("error", true);
        }
      }, chat.ctl).catch(function (e) {
        d.classList.add("error"); mkBang(d);
        txt.textContent = e.status === 404 ? "chat is not available yet on this server" : "error: " + (e.message || e);
        chat.status("error", true);
      }).then(function () {
        d.classList.remove("streaming");
        chat.streamOn(false);
        face.done(!d.classList.contains("error"));
        chat.busy = false; chat.ctl = null;
        if (fin) chat.load();
        if (chat.stopping) {
          chat.stopping = false;
          if (acc) rich(clear(txt), acc);
          d.appendChild(el("div", "stopped", "(stopped)"));
          if (wasNew && !chat.thread && before !== undefined) chat.adopt(before, text);
          else { chat.status(chat.thread ? (chat.titles[chat.thread] || chat.title(text)) : "new chat"); chat.list(); }
        }
        ta.focus();
      });
    },
    /* raw llama-server: in-memory history, chat_openai on the core */
    next: function (dir) {   /* j/k: open the next/previous thread */
      var picks = Array.prototype.slice.call(document.querySelectorAll("#thread-list .pick"));
      if (!picks.length) return;
      var i = -1;
      picks.forEach(function (b, k) { if (b.getAttribute("data-id") === chat.thread) i = k; });
      var n = i < 0 ? (dir > 0 ? 0 : picks.length - 1) : Math.min(picks.length - 1, Math.max(0, i + dir));
      if (picks[n] && n !== i) chat.open(picks[n].getAttribute("data-id"));
    },
    size: function () {
      var ta = $("chat-text"); ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight + 2, 192) + "px";
    },
    init: function () {
      var ta = $("chat-text");
      $("chat-form").addEventListener("submit", function (ev) { ev.preventDefault(); chat.send(); });
      ta.addEventListener("keydown", function (ev) {
        if (ev.isComposing || ev.keyCode === 229) return;   /* IME: this Enter commits the candidate */
        if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); chat.send(); }
      });
      ta.addEventListener("input", chat.size);
      $("chat-stop").addEventListener("click", chat.stop);
      $("thread-new").addEventListener("click", chat.fresh);
      $("threads-toggle").addEventListener("click", function () {
        chat.drawer(!$("view-chat").classList.contains("drawer"));
      });
      $("scrim").addEventListener("click", function () { chat.drawer(false); });
      document.querySelectorAll(".chip").forEach(function (c) {
        c.addEventListener("click", function () {
          ta.value = c.getAttribute("data-chip") || c.textContent;
          chat.size();
          chat.send();
        });
      });
    }
  };
  function mkBang(d) { var mk = d.querySelector(".m"); if (mk) mk.textContent = "!"; }

  /* ----------------------------------------------------------- do */
  var doView = {
    thread: null, busy: false,
    load: function () { /* nothing to fetch: a goal starts it */ },
    reset: function () { doView.thread = null; clear($("do-steps")); },
    propose: function (text) {
      if (doView.busy) return;
      doView.busy = true;
      $("do-status").textContent = "thinking";
      var body = doView.thread ? { thread: doView.thread, text: text } : { text: text };
      api.post("/api/do/propose", body).then(function (d) {
        if (d.thread) doView.thread = d.thread;
        $("do-status").textContent = d.ms !== undefined ? d.ms + " ms" : "";
        doView.step(d.reply || {}, d.unchecked || []);
      }).catch(function (e) {
        $("do-status").textContent = e.quiet ? String(e.message) : e.status === 404 ? "do is not available yet on this server" : "error: " + (e.message || e);
      }).then(function () { doView.busy = false; });
    },
    step: function (r, bad) {
      var box = $("do-steps"), n = box.querySelectorAll(".step").length + 1;
      if (r.kind === "done" || !r.command) {
        var dn = el("div", "step done");
        dn.appendChild(el("div", "cmd" + (bad && bad.length ? " warn" : ""), "done"));
        dn.appendChild(el("div", "hint", r.hint || ""));
        if (bad && bad.length) dn.appendChild(el("div", "muted small",
          "unchecked: no step printed " + bad.join(", ") + " -- trust the outputs above"));
        box.appendChild(dn);
        return;
      }
      var s = el("div", "step" + (r.danger ? " danger" : ""));
      /* a line is <code>; a block (several lines, a here-document) is a
         <pre> holding every line, shown whole before Run */
      var block = r.command.indexOf("\n") >= 0;
      var cmd = el("div", "cmd"); cmd.appendChild(el("span", "muted", n + "  "));
      if (block) {
        cmd.appendChild(el("span", "muted", r.command.split("\n").length + " lines"));
        var pre = el("pre", "block"); pre.appendChild(el("code", null, r.command));
        cmd.appendChild(pre);
      } else {
        cmd.appendChild(el("code", null, r.command));
      }
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
        /* a dangerous step got its second click above; the server runs
           one only when told so (confirmed), and never re-judges the rest */
        api.post("/api/do/run", { command: r.command, confirmed: !!r.danger }).then(function (d) {
          note.textContent = "";
          ctl.appendChild(el("span", "rc " + (d.rc === 0 ? "ok" : "fail"), "exit " + d.rc));
          var pre = el("pre", "log", d.tail || ""); s.appendChild(pre);
          var next = el("button", null, "next step"); next.type = "button";
          next.addEventListener("click", function () {
            next.disabled = true;
            /* a step refused for an option: its man page's lines ride
               the feedback, as they do at the prompt (contract 9's man) */
            var out = d.tail || "";
            if (d.man) out = out.replace(/\n+$/, "") + "\n\n" + d.man;
            doView.propose("Output of `" + r.command + "` (exit " + d.rc + "):\n" + out);
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
        var eff = c.effective || {};
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
          box.appendChild(el("p", "muted small", "* the prompt line's model, + the chat model"));
        var ep = clear($("ember-pick"));
        ["auto", "none"].concat((c.models || []).map(function (m) { return m.name; })).forEach(function (n) {
          var o = el("option", null, n); o.value = n; ep.appendChild(o);
        });
        ep.value = eff.SITE_EMBER_MODEL || "auto";
        var dl = clear($("config-facts"));
        fact(dl, "prompt", c.off ? "off" : "on"); fact(dl, "service", c.service);
        fact(dl, "model", eff.SITE_AI_MODEL); fact(dl, "chat model", eff.SITE_EMBER_MODEL || "auto");
        var hs = c.https || {};
        config.https = hs;
        fact(dl, "https", hs.mode === "own" ? "on, a root of this machine's own" : hs.mode === "pair" ? "on, your pair" : "off, plain http");
        fact(dl, "page", hs.link);
        fact(dl, "spark", "v" + (health.version || "") + (newer() ? ", newest v" + me.newest : ", the newest"));
        var own = hs.mode === "own" && (hs.ca_qr || []).length;
        $("root-box").hidden = !own;
        if (own) {
          $("root-link").textContent = hs.ca || "";
          clear($("root-qr")).appendChild(qrSvg(hs.ca_qr));
        }
      }).catch(function (e) { fail($("model-table"), e); });
      api.get("/api/soul").then(function (s) {
        $("soul-text").value = typeof s === "string" ? s : (s.text || "");
        $("soul-status").textContent = "";
      }).catch(function (e) { $("soul-status").textContent = e.status === 404 ? "the soul editor is not available yet" : "error: " + (e.message || e); });
      config.memory();
      config.users();
      if (me.role !== "admin") monitor.loadSends(7);
    },
    https: {}, armRm: { n: "", t: 0 },
    users: function () {
      if (me.role !== "admin") return;
      api.get("/api/users").then(function (d) {
        var t = clear($("users-table"));
        (d.users || []).forEach(function (u) {
          var tr = el("tr");
          tr.appendChild(el("td", "mono", u.name));
          tr.appendChild(el("td", null, u.threads + (u.threads === 1 ? " chat" : " chats") +
            (u.kept ? " (" + u.kept + " kept)" : "")));
          tr.appendChild(el("td", "muted", u.last || "-"));
          var td = el("td");
          if (u.account) td.appendChild(el("span", "muted small", "this machine"));
          else {
            /* remove: click once to arm, again within 5 s to do; the
               store and every kept chat go, as spark user remove NAME */
            var rm = el("button", "x", "remove"); rm.type = "button";
            rm.setAttribute("aria-label", "remove " + u.name);
            rm.addEventListener("click", function () {
              var st = $("users-status");
              if (config.armRm.n !== u.name || Date.now() - config.armRm.t > 5000) {
                config.armRm = { n: u.name, t: Date.now() }; rm.classList.add("confirm");
                st.textContent = "click again to remove " + u.name + " and every chat they kept";
                setTimeout(function () {
                  if (Date.now() - config.armRm.t >= 5000) { rm.classList.remove("confirm"); st.textContent = ""; }
                }, 5100);
                return;
              }
              config.armRm = { n: "", t: 0 };
              api.del("/api/users/" + encodeURIComponent(u.name)).then(function () {
                st.textContent = u.name + " removed";
                config.users();
              }).catch(function (e) { st.textContent = "error: " + (e.message || e); });
            });
            td.appendChild(rm);
          }
          tr.appendChild(td);
          t.appendChild(tr);
        });
        if (!(d.users || []).length) {
          var tr0 = el("tr"); tr0.appendChild(el("td", "muted", "no users yet"));
          t.appendChild(tr0);
        }
      }).catch(function () {});   /* an older FORGE has no /api/users */
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
      $("ember-pick").addEventListener("change", function () { run.go("model", ["--chat", this.value]); });
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
      /* the account card: click once to arm, again to do (the do view's shape) */
      var armAt = { rotate: 0, clear: 0 };
      function armed(key, b) {
        if (Date.now() - armAt[key] <= 5000) { b.classList.remove("confirm"); return true; }
        armAt[key] = Date.now(); b.classList.add("confirm");
        $("account-note").textContent = "click again to confirm";
        setTimeout(function () {
          if (Date.now() - armAt[key] >= 5000) { b.classList.remove("confirm"); $("account-note").textContent = ""; }
        }, 5100);
        return false;
      }
      $("user-rotate").addEventListener("click", function () {
        if (!armed("rotate", this)) return;
        $("account-note").textContent = "";
        api.post("/api/user/token", {}).then(function (d) {
          $("account-status").textContent = "new token, shown once -- scan it on your phone, or copy it";
          $("account-token").textContent = d.token || "";
          var box = clear($("account-qr"));
          box.hidden = !(d.qr && d.qr.length);
          if (d.qr && d.qr.length) box.appendChild(qrSvg(d.qr));
          $("account-new").hidden = false;
        }).catch(function (e) { $("account-status").textContent = "error: " + (e.message || e); });
      });
      /* a new user from the page: the token once, as a QR for their phone
         and as text, never stored (POST /api/users, the admin's) */
      $("user-add-form").addEventListener("submit", function (ev) {
        ev.preventDefault();
        var inp = $("user-add-name"), name = inp.value.trim(), note = $("user-add-note");
        if (!name) return;
        note.textContent = "minting";
        api.post("/api/users", { name: name }).then(function (d) {
          note.textContent = "";
          inp.value = "";
          $("user-token").textContent = d.token || "";
          var box = clear($("user-qr"));
          box.hidden = !(d.qr && d.qr.length);
          if (d.qr && d.qr.length) box.appendChild(qrSvg(d.qr));
          var own = config.https.mode === "own" && (config.https.ca_qr || []).length;
          $("user-root").hidden = !own;
          if (own) clear($("user-root-qr")).appendChild(qrSvg(config.https.ca_qr));
          $("user-new").hidden = false;
          config.users();
        }).catch(function (e) { note.textContent = e.quiet ? String(e.message) : "error: " + (e.message || e); });
      });
      $("https-own").addEventListener("click", function () { run.go("serve", ["https", "own"]); });
      $("update-btn").addEventListener("click", function () { run.go("update", []); });
      $("user-clear").addEventListener("click", function () {
        if (!armed("clear", this)) return;
        $("account-note").textContent = "";
        api.del("/api/threads").then(function (d) {
          $("account-status").textContent = "cleared " + d.cleared + (d.cleared === 1 ? " chat" : " chats") +
            (d.kept ? "; " + d.kept + " kept " + (d.kept === 1 ? "chat stays" : "chats stay") : "");
        }).catch(function (e) { $("account-status").textContent = "error: " + (e.message || e); });
      });
    }
  };

  /* ----------------------------------------------------------- help */
  var help = {
    /* the pages row of the keys table: the admin's five, a user's three */
    keys: function () {
      var admin = me.role === "admin", k = clear($("keys-pages-k")), v = $("keys-pages");
      if (admin) {
        k.appendChild(el("kbd", null, "1")); k.appendChild(document.createTextNode(" .. ")); k.appendChild(el("kbd", null, "5"));
        v.textContent = "chat, activity, do, settings, help";
      } else {
        ["1", "4", "5"].forEach(function (n, i) { if (i) k.appendChild(document.createTextNode(" ")); k.appendChild(el("kbd", null, n)); });
        v.textContent = "chat, settings, help";
      }
    },
    load: function () {
      $("help-health").textContent = location.origin + "/api/health";
      help.keys();
    },
    init: function () { }
  };

  /* ----------------------------------------------------------- route */
  var VIEWS = { monitor: monitor, chat: chat, "do": doView, config: config, help: help };
  var ORDER = ["chat", "monitor", "do", "config", "help"];
  var route = {
    /* the views a role may open: a guest's page is chat, their account
       and help -- the admin pages redirect to chat rather than 403ing
       (the server refuses the data anyway; the page just never shows
       the empty shell) */
    allowed: function (name) {
      return me.role === "admin" || (name !== "do" && name !== "monitor");
    },
    current: function () {
      var h = location.hash.replace(/^#\/?/, "").split("/")[0];
      return VIEWS[h] && route.allowed(h) ? h : "chat";
    },
    show: function (name, load) {
      if (!route.allowed(name)) name = "chat";
      document.querySelectorAll(".tabs a").forEach(function (a) {
        if (a.getAttribute("data-view") === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
      });
      route.menu(false);
      if (!auth.ok) return;
      ORDER.forEach(function (v) { $("view-" + v).hidden = v !== name; });
      if (load !== false) VIEWS[name].load();
    },
    go: function (name) { location.hash = "#/" + name; },
    /* the header's one menu: open sets focus in, close hands it back */
    menu: function (on) {
      var m = $("menu"), b = $("nav-btn");
      if (on === undefined) on = m.hidden;
      if (!on && !m.hidden && m.contains(document.activeElement)) b.focus();
      m.hidden = !on;
      b.setAttribute("aria-expanded", on ? "true" : "false");
      if (on) { var a = m.querySelector("a:not([hidden])"); if (a) a.focus(); }
    },
    keys: function (ev) {
      var t = ev.target, typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if (ev.key === "Escape") {   /* stop the answer or the running verb, else leave the input, else close the menu, else the drawer */
        if (chat.busy && chat.ctl) { chat.stop(); ev.preventDefault(); return; }
        if (run.busy && run.ctl) { run.stop(); ev.preventDefault(); return; }
        if (typing) { t.blur(); return; }
        if (!$("menu").hidden) { route.menu(false); return; }
        if ($("view-chat").classList.contains("drawer")) chat.drawer(false);
        return;
      }
      if (typing || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      var n = parseInt(ev.key, 10);
      if (n >= 1 && n <= 5) {
        if (route.allowed(ORDER[n - 1])) route.go(ORDER[n - 1]);
        ev.preventDefault(); return;
      }
      if (ev.key === "/") {
        var v = $("view-" + route.current()), inp = v && v.querySelector("[data-main]");
        if (inp) { inp.focus(); ev.preventDefault(); }
        return;
      }
      if (ev.key === "r") { route.show(route.current()); ev.preventDefault(); return; }
      if (ev.key === "n" && route.current() === "chat") { chat.fresh(); ev.preventDefault(); return; }
      if ((ev.key === "j" || ev.key === "k") && route.current() === "chat") {
        chat.next(ev.key === "j" ? 1 : -1); ev.preventDefault(); return;
      }
      if (ev.key === "?") { route.go("help"); ev.preventDefault(); }
    },
    init: function () {
      window.addEventListener("hashchange", function () { route.show(route.current()); });
      document.addEventListener("keydown", route.keys);
      $("nav-btn").addEventListener("click", function (ev) { ev.stopPropagation(); route.menu(); });
      document.addEventListener("click", function (ev) {
        if ($("menu").hidden) return;
        if (!$("menu").contains(ev.target) && ev.target !== $("nav-btn")) route.menu(false);
      });
    }
  };

  /* ----------------------------------------------------------- boot */
  var health = {};
  function siteLine(h) {
    if (h) health = h;
    h = health;
    var mm = "";
    if (auth.ok && me.role === "admin" && h.model) mm = "  " + h.model;
    if (auth.ok && me.role === "admin" && h.roles) {
      var nm = h.names || h.roles, word = { spark: "line", ember: "chat" };
      var rk = ["spark", "ember"].concat(Object.keys(h.roles).filter(function (k) { return k !== "spark" && k !== "ember"; }));
      var rr = rk.filter(function (k) { return h.roles[k]; }).map(function (k) { return (word[k] || k) + " " + (nm[k] || h.roles[k]); });
      if (rr.length) mm = "  " + rr.join(" \u00b7 ");
    }
    var nw = auth.ok && me.role === "admin" && newer() ? ", newest v" + me.newest : "";
    $("site").textContent = (h.name || "") + (h.version ? "  v" + h.version + nw : "") + mm;
    document.title = "spark" + (h.name ? " " + h.name : "");
  }
  /* whether the newest release the machine knows is past the one it runs:
     "1.97" against "1.96" or "1.96+3", by number, never by string */
  function newer() {
    if (!me.newest || !health.version) return false;
    function parts(v) { return String(v).split("+")[0].split(".").map(function (x) { return parseInt(x, 10) || 0; }); }
    var a = parts(me.newest), b = parts(health.version);
    for (var i = 0; i < 3; i++) { if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) > (b[i] || 0); }
    return false;
  }
  function boot() {
    theme.init(); face.init(); auth.init(); run.init(); route.init();
    ORDER.forEach(function (v) { VIEWS[v].init(); });
    api.get("/api/health").then(siteLine).catch(function () { $("site").textContent = "no spark answers"; });
    if (linkToken) {   /* the QR / login link: one attempt, then the form */
      auth.fromLink(linkToken);
      linkToken = "";
    } else {
      api.get("/api/me").then(function () { auth.gained(); })
        .catch(function () { /* 401 already showed the login card */ });
    }
    route.show(route.current(), false);
  }
  boot();
})();
