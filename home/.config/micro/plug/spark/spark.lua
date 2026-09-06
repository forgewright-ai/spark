VERSION = "1.2.0"

-- spark.lua -- spark in micro (the first smart tool). One key, Alt-s, opens
-- the `spark> ` prompt; Enter alone completes at the cursor, words rewrite
-- the selection (or write at the cursor when nothing is selected), `? words`
-- asks in a pane on the right, `?` alone reviews, `?? words` goes on in the
-- newest pane's thread. Every run is one call to `spark edit` (contract 10)
-- with the text on stdin: the plugin never speaks HTTP, never sees a token,
-- never sends the file's path -- spark owns all of that. Solicited only:
-- nothing runs until you ask.
--
-- In a spark pane, keys are caught by callbacks (the pane is read-only, so
-- a rune would go nowhere anyway): q and Escape close it, Enter jumps to
-- the quote on the line, a applies the code block under the cursor, d
-- declines the note under the cursor (spark edit --decline: not raised
-- again for this file).
--
-- The plugin binds NO key itself: a rebind from inside the editor makes micro
-- rewrite bindings.json, which replaces the tracked symlink with a plain
-- file. The key lives in the tracked ~/.config/micro/bindings.json:
--     "Alt-s": "lua:spark.prompt"
-- micro's own switch turns it off: `set spark false`.

local micro  = import("micro")
local config = import("micro/config")
local shell  = import("micro/shell")
local buffer = import("micro/buffer")
local util   = import("micro/util")

local pending = false      -- one run at a time
local current = nil        -- the state of the run in flight
local noticed = 0          -- a notice is on the infobar: 1 = just posted, 2 = shown

-- The panes: each gets its own name (micro shares one text between two
-- buffers opened under the same path, so two panes named `spark` would
-- show one answer). name -> {origin, pbp, buf, file, sel_a, sel_b,
-- sel_text, thread}; `newest` is the one `??` goes on in.
local panes = {}
local npanes = 0
local newest = nil

local function pane_of(bp)
    local ok, path = pcall(function() return bp.Buf.Path end)
    if ok and path ~= nil then return panes[path], path end
    return nil, nil
end

-- ------------------------------------------------------------- helpers --
local function trim(s)
    return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function basename(p)
    return (p:gsub("^.*/", ""))
end

local function readable(p)
    local f = io.open(p, "r")
    if f == nil then return false end
    f:close()
    return true
end

-- The binary: SPARK_BIN (tests), the spark.bin option, ~/.local/bin/spark
-- (micro under a desktop session may never have sourced the rc files that
-- put it on PATH), then whatever PATH answers to.
local function bin()
    local env = os.getenv("SPARK_BIN")
    if env ~= nil and env ~= "" then return env end
    local opt = config.GetGlobalOption("spark.bin")
    if opt ~= nil and opt ~= "" then return opt end
    local home = os.getenv("HOME") or ""
    if home ~= "" and readable(home .. "/.local/bin/spark") then
        return home .. "/.local/bin/spark"
    end
    return "spark"
end

-- Runes and bytes: micro's Loc.X counts runes; spark's --at counts bytes.
local UTF8 = "[%z\1-\127\194-\244][\128-\191]*"

local function runes(s)
    local n = 0
    for _ in s:gmatch(UTF8) do n = n + 1 end
    return n
end

local function bytes_of_runes(line, x)
    local n, b = 0, 0
    for ch in line:gmatch(UTF8) do
        if n >= x then break end
        n = n + 1
        b = b + #ch
    end
    return b
end

local function byte_offset(buf, loc)
    local off = 0
    for y = 0, loc.Y - 1 do
        off = off + #buf:Line(y) + 1
    end
    return off + bytes_of_runes(buf:Line(loc.Y), loc.X)
end

-- Where the cursor lands after `text` is inserted at `loc`.
local function advance(loc, text)
    local x, y = loc.X, loc.Y
    local last = text:match("([^\n]*)$")
    local nl = select(2, text:gsub("\n", ""))
    if nl > 0 then
        return buffer.Loc(runes(last), y + nl)
    end
    return buffer.Loc(x + runes(last), y)
end

local function before(a, b)
    return a.Y < b.Y or (a.Y == b.Y and a.X <= b.X)
end

local function ordered(c)
    local a, b = c.CurSelection[1], c.CurSelection[2]
    if before(a, b) then return a, b end
    return b, a
end

local function select_region(bp, a, b)
    local c = bp.Buf:GetActiveCursor()
    c:GotoLoc(b)
    c:SetSelectionStart(a)
    c:SetSelectionEnd(b)
end

-- Is loc still inside buf? The buffer may have shrunk while spark thought.
local function inside(buf, loc)
    if loc.Y < 0 or loc.Y >= buf:LinesNum() then return false end
    return loc.X >= 0 and loc.X <= runes(buf:Line(loc.Y))
end

-- What the buffer holds now between a and b, or nil when the range is gone.
local function text_at(buf, a, b)
    if not inside(buf, a) or not inside(buf, b) then return nil end
    return util.String(buf:Substr(a, b))
end

-- A new pane on the right, registered under its own name. `sel` is the
-- selection the pane's question was about (nil for the whole file).
local function open_pane(bp, text, sel)
    npanes = npanes + 1
    local name = "spark:" .. npanes
    local pane = buffer.NewBuffer(text, name)
    -- buffer.BTScratch reaches Lua as a number, so set the fields: Scratch
    -- never nags on quit; Readonly only once a stream is over (Insert
    -- refuses a readonly buffer)
    pane.Type.Scratch = true
    -- a narrow pane of prose: wrap on screen, between words
    pane:SetOptionNative("softwrap", true)
    pane:SetOptionNative("wordwrap", true)
    local pbp = bp:VSplitBuf(pane)
    local path = bp.Buf.Path
    local entry = {origin = bp, pbp = pbp, buf = pane, file = (path ~= nil and path ~= "") and basename(path) or "",
                   thread = string.format("edit-%d-%04d", os.time(), math.random(0, 9999))}
    if sel then
        entry.sel_a, entry.sel_b, entry.sel_text = sel.a, sel.b, sel.text
    end
    panes[name] = entry
    newest = name
    return entry
end

-- An answer that cannot be spliced is still an answer: a read-only pane.
local function show_pane(bp, text)
    local entry = open_pane(bp, text, nil)
    entry.buf.Type.Readonly = true
end

local function forget_pane(name)
    panes[name] = nil
    if newest == name then newest = nil end
end

local function argv(bp, extra)
    local args = {"edit", "--type", bp.Buf:FileType()}
    local path = bp.Buf.Path
    if path ~= nil and path ~= "" then
        args[#args + 1] = "--name"
        args[#args + 1] = basename(path)
    end
    local about = bp.Buf.Settings["spark.about"]
    if about ~= nil and about ~= "" then
        args[#args + 1] = "--about"
        args[#args + 1] = about
    end
    for _, w in ipairs(extra) do args[#args + 1] = w end
    return args
end

local function words_of(s)
    local t = {}
    for w in s:gmatch("%S+") do t[#t + 1] = w end
    return t
end

-- ---------------------------------------------------------------- jobs --
-- state: { kind, bp, buf, loc, start, sel_a, sel_b, sel_text, acc, err, got }
-- A job callback gets (output, userargs): userargs is the Go slice of what
-- spawn passed after the callbacks, so the state is args[1], never args.
local function on_out(chunk, args)
    local state = args[1]
    if chunk == nil or chunk == "" then return end
    state.got = true
    if state.kind == "rewrite" or state.kind == "decline" then
        state.acc = state.acc .. chunk      -- spliced only once it is whole
        return
    end
    state.buf:Insert(state.loc, chunk)
    state.loc = advance(state.loc, chunk)
end

local function on_err(chunk, args)
    local state = args[1]
    state.err = state.err .. (chunk or "")
end

local function notice(msg)
    micro.InfoBar():Message(msg)
    noticed = 1
end

local ASK_KEYS = "spark: q closes; Enter jumps to a quote, a applies code, d declines a note, ?? goes on"

local function on_exit(_, args)
    local state = args[1]
    pending = false
    current = nil
    local ib = micro.InfoBar()
    if state.kind == "decline" then
        -- silence and exit 0 is success; a refusal comes on stdout, a die on stderr
        local why = trim(state.err ~= "" and state.err or state.acc)
        if why ~= "" then
            ib:Error(why)
            return
        end
        local pane = state.buf
        pane.Type.Readonly = false
        pane:Remove(state.from, state.to)
        pane.Type.Readonly = true
        notice("spark: declined -- not raised again for " .. state.file)
        return
    end
    if not state.got then
        local why = trim(state.err)
        if why == "" then why = "spark: nothing came back" end
        ib:Error(why)
        return
    end
    if state.kind == "rewrite" then
        if state.acc == state.sel_text then
            notice("spark: unchanged")
            return
        end
        -- the text it rewrote must still be there: an edit meanwhile moved
        -- or shrank it, and a splice over a stale range corrupts the file
        if text_at(state.buf, state.sel_a, state.sel_b) ~= state.sel_text then
            show_pane(state.bp, state.acc)
            notice("spark: the text changed while it thought -- the answer is in the pane, Ctrl-q closes")
            return
        end
        state.buf:Remove(state.sel_a, state.sel_b)
        state.buf:Insert(state.sel_a, state.acc)
        if state.whole then
            state.buf:GetActiveCursor():GotoLoc(state.sel_a)
            notice("spark: the file is rewritten -- Ctrl-z undoes")
        else
            select_region(state.bp, state.sel_a, advance(state.sel_a, state.acc))
            notice("spark: rewritten -- Backspace discards, Ctrl-z undoes")
        end
    elseif state.kind == "ask" then
        state.buf.Type.Readonly = true
        if state.anchor then
            state.buf:GetActiveCursor():GotoLoc(state.anchor)
            if state.pbp then pcall(function() state.pbp:Relocate() end) end
        end
        notice(ASK_KEYS)
    else
        select_region(state.bp, state.start, state.loc)
        notice("spark: done -- Backspace discards, Ctrl-z undoes")
    end
end

-- micro keeps an infobar message until another replaces it; a notice about
-- a finished run is stale the moment you type, so the next key clears it.
-- The job's own completion event reaches this hook right after the notice
-- is posted (that is event one, which must not clear it); the next is yours.
function onAnyEvent()
    if noticed == 1 then
        noticed = 2
    elseif noticed == 2 then
        noticed = 0
        micro.InfoBar():Message("")
    end
end

-- A Lua error inside a job callback ends micro with a stack trace (2.0.14):
-- each callback runs protected, and an error becomes an infobar line.
local function guarded(fn)
    return function(out, args)
        local fine, err = pcall(fn, out, args)
        if not fine then
            pending = false
            micro.InfoBar():Error("spark: " .. tostring(err))
        end
    end
end

local function spawn(bp, args, stdin, state)
    state.err, state.got = "", false
    pending = true
    current = state
    local job = shell.JobSpawn(bin(), args, guarded(on_out), guarded(on_err), guarded(on_exit), state)
    if job == nil then
        pending = false
        current = nil
        micro.InfoBar():Error("spark: could not start " .. bin())
        return
    end
    shell.JobSend(job, stdin)
    job.Stdin:Close()
    micro.InfoBar():Message("spark: thinking")
end

-- --------------------------------------------------------------- kinds --
local function complete(bp)
    local buf = bp.Buf
    local loc = buf:GetActiveCursor().Loc
    local at = byte_offset(buf, loc)
    local state = {kind = "complete", bp = bp, buf = buf, loc = buffer.Loc(loc.X, loc.Y),
                   start = buffer.Loc(loc.X, loc.Y)}
    spawn(bp, argv(bp, {"--at", tostring(at)}), util.String(buf:Bytes()), state)
end

-- The selection is what gets rewritten; nothing selected means the whole
-- file, replaced in place (the brief asks for the whole rewritten text, so
-- inserting it at the cursor would double the file). A selection travels
-- with --part: a fragment must come back as exactly that fragment.
local function rewrite(bp, words)
    local buf = bp.Buf
    local c = buf:GetActiveCursor()
    local a, b, text, extra
    if c:HasSelection() then
        a, b = ordered(c)
        text = util.String(c:GetSelection())
        extra = {"--part"}
        for _, w in ipairs(words) do extra[#extra + 1] = w end
    else
        -- the whole buffer: (0,0) to the end of the last line, computed
        -- here (buf:End() misbehaves on micro 2.0.14)
        local last = buf:LinesNum() - 1
        a = buffer.Loc(0, 0)
        b = buffer.Loc(runes(buf:Line(last)), last)
        text = util.String(buf:Bytes())
        extra = words
    end
    local state = {kind = "rewrite", bp = bp, buf = buf, acc = "", sel_text = text,
                   sel_a = buffer.Loc(a.X, a.Y), sel_b = buffer.Loc(b.X, b.Y),
                   whole = not c:HasSelection()}
    spawn(bp, argv(bp, extra), text, state)
end

-- A question: the WHOLE buffer goes on stdin; a selection travels as
-- --sel A B (byte offsets), so spark sees the file around it. `follow`
-- (?? words) goes on in the newest pane's thread: the same --thread id,
-- the answer under the question at the pane's end.
local function ask(bp, words, follow)
    local buf = bp.Buf
    local c = buf:GetActiveCursor()
    local text = util.String(buf:Bytes())
    if trim(text) == "" then
        micro.InfoBar():Message("spark: nothing to ask about")
        return
    end
    local extra, sel = {}, nil
    if c:HasSelection() then
        local a, b = ordered(c)
        sel = {a = buffer.Loc(a.X, a.Y), b = buffer.Loc(b.X, b.Y), text = util.String(c:GetSelection())}
        extra = {"--sel", tostring(byte_offset(buf, a)), tostring(byte_offset(buf, b))}
    end
    for _, w in ipairs(words) do extra[#extra + 1] = w end
    local entry = follow and newest and panes[newest] or nil
    local state
    if entry then
        local pane = entry.buf
        pane.Type.Readonly = false
        local last = pane:LinesNum() - 1
        local at = buffer.Loc(runes(pane:Line(last)), last)
        local asked = {}
        for i = 2, #words do asked[#asked + 1] = words[i] end
        local q = "\n\n> " .. (#asked > 0 and table.concat(asked, " ") or "?") .. "\n\n"
        pane:Insert(at, q)
        if sel then
            entry.sel_a, entry.sel_b, entry.sel_text = sel.a, sel.b, sel.text
        end
        local loc = advance(at, q)
        state = {kind = "ask", bp = bp, buf = pane, pbp = entry.pbp, loc = loc, anchor = buffer.Loc(loc.X, loc.Y)}
    else
        entry = open_pane(bp, "", sel)
        state = {kind = "ask", bp = bp, buf = entry.buf, pbp = entry.pbp, loc = buffer.Loc(0, 0)}
    end
    extra[#extra + 1] = "--thread"
    extra[#extra + 1] = entry.thread
    spawn(bp, argv(bp, extra), text, state)
end

-- ----------------------------------------------------------- the pane --
-- The first quoted span on a line: "..." or the curly pair or `...`.
local function first_quote(line)
    local best, span = nil, nil
    for _, pat in ipairs({'"([^"]+)"', "“([^”]+)”", "`([^`]+)`"}) do
        local s, _, m = line:find(pat)
        if s and (best == nil or s < best) then best, span = s, m end
    end
    return span
end

-- A Go regexp that matches `s` literally, any run of whitespace in it
-- matching any run (the quote may cross a line break in the file).
local function loose_regex(s)
    local esc = s:gsub("[%^%$%(%)%.%[%]%*%+%-%?%{%}%|\\]", "\\%0")
    return (esc:gsub("%s+", "\\s+"))
end

local function origin_of(entry)
    if entry.origin == nil then return nil end
    local ok, gone = pcall(function() return entry.origin.Buf == nil end)
    if not ok or gone then return nil end
    return entry.origin
end

local function activate(bp, target)
    local tab = bp:Tab()
    tab:SetActive(tab:GetPane(target:ID()))
end

-- Enter: the origin's cursor goes to the quote on this line, selected.
local function jump(bp, entry)
    local span = first_quote(bp.Buf:Line(bp.Buf:GetActiveCursor().Loc.Y))
    if span == nil then
        micro.InfoBar():Message("spark: no quote on this line")
        return
    end
    local origin = origin_of(entry)
    if origin == nil then
        micro.InfoBar():Message("spark: the file's pane is closed")
        return
    end
    local ob = origin.Buf
    local last = ob:LinesNum() - 1
    local locs, found = ob:FindNext(loose_regex(span), buffer.Loc(0, 0), buffer.Loc(runes(ob:Line(last)), last),
                                    buffer.Loc(0, 0), true, true)
    if not found then
        micro.InfoBar():Message("spark: not in the text as written")
        return
    end
    local a, b = locs[1], locs[2]
    local c = ob:GetActiveCursor()
    c:GotoLoc(b)
    c:SetSelectionStart(a)
    c:SetSelectionEnd(b)
    activate(bp, origin)
    origin:Relocate()
end

-- The code block under the cursor: the lines indented four spaces around
-- it (the brief's shape), dedented; else the fenced block the cursor is
-- in. nil when there is none.
local function code_block(buf, y)
    local n = buf:LinesNum()
    local function indented(i) return buf:Line(i):match("^    ") ~= nil end
    local function blank(i) return trim(buf:Line(i)) == "" end
    if indented(y) then
        local top, bot = y, y
        while top > 0 and (indented(top - 1) or (blank(top - 1) and top > 1 and indented(top - 2))) do top = top - 1 end
        while bot < n - 1 and (indented(bot + 1) or (blank(bot + 1) and bot + 2 < n and indented(bot + 2))) do bot = bot + 1 end
        local out = {}
        for i = top, bot do out[#out + 1] = (buf:Line(i):gsub("^    ", "")) end
        return table.concat(out, "\n") .. "\n"
    end
    local function fence(i) return buf:Line(i):match("^%s*```") ~= nil end
    local top = y
    while top >= 0 and not fence(top) do top = top - 1 end
    if top < 0 then return nil end
    local bot = y + 1
    if fence(y) then bot = y + 1 end
    while bot < n and not fence(bot) do bot = bot + 1 end
    if bot >= n or bot <= top + 1 then return nil end
    local out = {}
    for i = top + 1, bot - 1 do out[#out + 1] = buf:Line(i) end
    return table.concat(out, "\n") .. "\n"
end

-- a: the code block under the cursor replaces the selection the question
-- was about when it is still there, else lands at the origin's cursor.
local function apply_block(bp, entry)
    local text = code_block(bp.Buf, bp.Buf:GetActiveCursor().Loc.Y)
    if text == nil then
        micro.InfoBar():Message("spark: no code here -- a block is indented four spaces, or fenced")
        return
    end
    local origin = origin_of(entry)
    if origin == nil then
        micro.InfoBar():Message("spark: the file's pane is closed")
        return
    end
    local ob = origin.Buf
    local at
    if entry.sel_text ~= nil and text_at(ob, entry.sel_a, entry.sel_b) == entry.sel_text then
        ob:Remove(entry.sel_a, entry.sel_b)
        at = buffer.Loc(entry.sel_a.X, entry.sel_a.Y)
    else
        local l = ob:GetActiveCursor().Loc
        at = buffer.Loc(l.X, l.Y)
    end
    ob:Insert(at, text)
    entry.sel_a, entry.sel_b, entry.sel_text = at, advance(at, text), text
    select_region(origin, at, advance(at, text))
    activate(bp, origin)
    origin:Relocate()
    notice("spark: applied -- Backspace discards, Ctrl-z undoes")
end

-- d: the note under the cursor (the numbered paragraph, or the paragraph)
-- goes to the ledger; it leaves the pane when spark has kept it.
local function decline_note(bp, entry)
    if entry.file == "" then
        micro.InfoBar():Message("spark: an unnamed buffer keeps no ledger -- save it first")
        return
    end
    if pending then
        micro.InfoBar():Message("spark: still working -- one at a time")
        return
    end
    local buf = bp.Buf
    local n = buf:LinesNum()
    local y = buf:GetActiveCursor().Loc.Y
    local function numbered(i) return buf:Line(i):match("^%d+[%.%)]%s") ~= nil end
    local function blank(i) return trim(buf:Line(i)) == "" end
    if blank(y) then
        micro.InfoBar():Message("spark: no note here")
        return
    end
    local top = y
    while top > 0 and not numbered(top) and not blank(top - 1) do top = top - 1 end
    local bot = y
    while bot + 1 < n and not blank(bot + 1) and not numbered(bot + 1) do bot = bot + 1 end
    local lines = {}
    for i = top, bot do lines[#lines + 1] = buf:Line(i) end
    local from = top > 0 and buffer.Loc(runes(buf:Line(top - 1)), top - 1) or buffer.Loc(0, 0)
    local to = buffer.Loc(runes(buf:Line(bot)), bot)
    local state = {kind = "decline", bp = bp, buf = buf, from = from, to = to, file = entry.file, acc = ""}
    spawn(bp, {"edit", "--decline", "--name", entry.file}, table.concat(lines, "\n") .. "\n", state)
end

local function close_pane(bp, name)
    if pending and current and current.buf ~= nil and current.buf.Path == name then
        micro.InfoBar():Message("spark: still writing here -- a moment")
        return
    end
    forget_pane(name)
    bp:Quit()
end

-- The pane's keys: only when the active pane is one of ours; a rune in a
-- read-only buffer goes nowhere anyway, and false keeps micro from trying.
function preRune(bp, r)
    local entry, name = pane_of(bp)
    if entry == nil then return true end
    if r == "q" then
        close_pane(bp, name)
    elseif r == "a" then
        apply_block(bp, entry)
    elseif r == "d" then
        decline_note(bp, entry)
    end
    return false
end

function preEscape(bp)
    local entry, name = pane_of(bp)
    if entry == nil then return true end
    close_pane(bp, name)
    return false
end

function preInsertNewline(bp)
    local entry = pane_of(bp)
    if entry == nil then return true end
    jump(bp, entry)
    return false
end

-- Ctrl-q on a pane forgets it; on a file, its panes lose their origin.
function preQuit(bp)
    local entry, name = pane_of(bp)
    if entry ~= nil then
        forget_pane(name)
        return true
    end
    local ok, id = pcall(function() return bp:ID() end)
    if ok then
        for _, e in pairs(panes) do
            local fine, same = pcall(function() return e.origin ~= nil and e.origin:ID() == id end)
            if fine and same then e.origin = nil end
        end
    end
    return true
end

-- ------------------------------------------------------------- the key --
local function run(bp, line)
    line = trim(line or "")
    if pending then
        micro.InfoBar():Message("spark: still working -- one at a time")
        return
    end
    -- from inside a spark pane, the file it belongs to is meant
    local entry = pane_of(bp)
    if entry ~= nil then
        bp = origin_of(entry)
        if bp == nil then
            micro.InfoBar():Message("spark: the file's pane is closed")
            return
        end
    end
    if bp.Buf.Type.Readonly then
        micro.InfoBar():Error("spark: this buffer is read-only")
        return
    end
    if line == "" then
        complete(bp)
    elseif line:sub(1, 2) == "??" then
        local words = words_of(line:sub(3))
        table.insert(words, 1, "?")
        ask(bp, words, true)
    elseif line:sub(1, 1) == "?" then
        local words = words_of(line:sub(2))
        table.insert(words, 1, "?")
        ask(bp, words, false)
    elseif line == "lua" then
        -- the one word that is not an instruction: the shell has it
        micro.InfoBar():Message("spark lua -- this one runs in the dark; ask your shell")
    else
        rewrite(bp, words_of(line))
    end
end

function prompt(bp)
    if pending then
        micro.InfoBar():Message("spark: still working -- one at a time")
        return
    end
    micro.InfoBar():Prompt("spark> ", "", "spark", nil, function(resp, canceled)
        if not canceled then run(bp, resp) end
    end)
end

function command(bp, args)
    local t = {}
    for i = 1, #args do t[#t + 1] = args[i] end
    run(bp, table.concat(t, " "))
end

function init()
    math.randomseed(os.time())
    config.RegisterCommonOption("spark", "bin", "")
    config.RegisterCommonOption("spark", "about", "")
    config.MakeCommand("spark", command, config.NoComplete)
    config.AddRuntimeFile("spark", config.RTHelp, "help/spark.md")
end
