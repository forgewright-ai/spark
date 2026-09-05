VERSION = "1.0.0"

-- spark.lua -- spark in micro (the first smart tool). One key, Alt-s, opens
-- the `spark> ` prompt; Enter alone completes at the cursor, words rewrite
-- the selection (or write at the cursor when nothing is selected), `? words`
-- asks in a pane on the right, `?` alone reviews. Every run is one call to
-- `spark edit` (contract 10) with the text on stdin: the plugin never speaks
-- HTTP, never sees a token, never sends the file's path -- spark owns all of
-- that. Solicited only: nothing runs until you ask.
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
local noticed = 0          -- a notice is on the infobar: 1 = just posted, 2 = shown

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
    if state.kind == "rewrite" then
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

local function on_exit(_, args)
    local state = args[1]
    pending = false
    local ib = micro.InfoBar()
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
        notice("spark: Ctrl-q closes the pane")
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

local function spawn(bp, args, stdin, state)
    state.err, state.got = "", false
    pending = true
    local job = shell.JobSpawn(bin(), args, on_out, on_err, on_exit, state)
    if job == nil then
        pending = false
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
        a, b = buf:Start(), buf:End()
        text = util.String(buf:Bytes())
        extra = words
    end
    local state = {kind = "rewrite", bp = bp, buf = buf, acc = "", sel_text = text,
                   sel_a = buffer.Loc(a.X, a.Y), sel_b = buffer.Loc(b.X, b.Y),
                   whole = not c:HasSelection()}
    spawn(bp, argv(bp, extra), text, state)
end

local function ask(bp, words)
    local buf = bp.Buf
    local c = buf:GetActiveCursor()
    local text
    if c:HasSelection() then
        text = util.String(c:GetSelection())
    else
        text = util.String(buf:Bytes())
    end
    if trim(text) == "" then
        micro.InfoBar():Message("spark: nothing to ask about")
        return
    end
    local pane = buffer.NewBuffer("", "spark")
    -- buffer.BTScratch reaches Lua as a number, so set the fields: Scratch
    -- never nags on quit; Readonly only once the stream is over (Insert
    -- refuses a readonly buffer)
    pane.Type.Scratch = true
    -- a narrow pane of prose: wrap on screen, between words
    pane:SetOptionNative("softwrap", true)
    pane:SetOptionNative("wordwrap", true)
    bp:VSplitBuf(pane)
    local state = {kind = "ask", bp = bp, buf = pane, loc = buffer.Loc(0, 0)}
    spawn(bp, argv(bp, words), text, state)
end

-- ------------------------------------------------------------- the key --
local function run(bp, line)
    line = trim(line or "")
    if pending then
        micro.InfoBar():Message("spark: still working -- one at a time")
        return
    end
    if bp.Buf.Type.Readonly then
        micro.InfoBar():Error("spark: this buffer is read-only")
        return
    end
    if line == "" then
        complete(bp)
    elseif line:sub(1, 1) == "?" then
        local words = words_of(line:sub(2))
        table.insert(words, 1, "?")
        ask(bp, words)
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
    config.RegisterCommonOption("spark", "bin", "")
    config.RegisterCommonOption("spark", "about", "")
    config.MakeCommand("spark", command, config.NoComplete)
    config.AddRuntimeFile("spark", config.RTHelp, "help/spark.md")
end
