# spark.persona -- what the model is told about this machine and the task
# at hand, built from facts at runtime. No names are hard-coded: the
# workstation and the person come from site.env, the OS and tools from the
# system. Who spark *is* (the soul, the remembered facts) is forge.identity;
# system() below assembles prefix + identity + mode there.
#
# The prefix is byte-stable per machine and shell, so llama-server's prompt
# cache makes every call after the first cheap.

import os
import platform
import re
import shutil

from . import os_pretty, package_manager

PREFERRED = ("fd", "fdfind", "rg", "eza", "bat", "batcat", "dust", "ncdu", "zoxide", "fzf",
             "jq", "btop", "micro", "tmux", "git")

FLAGS = ("Flags that exist (use these, never invented ones): fd -e EXT, -S +1G, --changed-within 7d, "
         "-H, -t f|d, -x CMD; rg -n -i -l -t TYPE -g GLOB; eza -la --sort=size -r --tree -L 2; "
         "du -sh; sort -h; wc -l; find -type f -size +1G -mtime -7. "
         "A correct flag beats a preferred tool: when unsure, use the classic tool.")

# What leaves this machine, by kind: every verb that sends text to the
# brain, and the cap on what one request carries. README's "What leaves
# this machine" section must name every kind here -- tests/docs_test.py
# walks this table, so a new sender fails the docs test until the README
# discloses it.
SENDS = (
    ("line", "the line you typed, with the shell and OS name"),
    ("chat", "the conversation: soul, remembered facts, earlier turns"),
    ("do", "each step's output, last 4 kB -- a span that looks like a secret is held back"),
    # a step refused for an option: spark reads that command's own man
    # page (never runs the tool) and the lines about the option go back
    ("do", "after a step refused for an option, the lines of that command's man page "
           "about it, 1.5 kB at most"),
    ("explain", "the piped text, last 6 kB"),
    ("edit", "the text: 6 kB around the cursor, 12 kB rewrite, 16 kB question -- "
             "in a question about a source (--source), a span that looks like a secret is held back"),
    ("ask", "the text, 12 kB, with the --name/--about hints"),
    ("read", "the source, 16 kB a part -- a span that looks like a secret is held back"),
    ("drill", "the source, 16 kB"),
    ("watch", "each window of the stream, 8 kB at most"),
    ("recall", "the last 400 lines of this shell's history"),
    ("paste", "a multi-line paste at the prompt, 8 kB at most -- and nothing at all when it "
              "looks like a secret (a private key, a token, a credential line)"),
)

_DANGER = [
    r"\brm\s+.*\s/\s*$", r"\brm\s+-[a-zA-Z]*\s+/(\s|$)",
    r"\bdd\s+.*\bof=/dev/",
    r"\bmkfs(\.\w+)?\b", r"\bfdisk\b", r"\bparted\b", r"\bdiskutil\s+(erase|partition|reformat)",
    r">\s*/dev/(sd|nvme|disk|hd)",
    r"\bchmod\s+(-R\s+)?[0-7]*777\b", r"\bchown\s+-R\s+",
    r":\(\)\s*\{\s*:\|:&\s*\};:",
    r"\bgit\s+push\s+.*--force\b", r"\bgit\s+push\s+-f\b", r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-zA-Z]*f", r"\bgit\s+checkout\s+--\s+\.",
    r"\b(shutdown|reboot|halt|poweroff)\b", r"\bkill\s+-9\s+-1\b", r"\bkillall\b", r"\bpkill\s+-9\b",
    r"\bcrontab\s+-r\b", r"\btruncate\s+-s\s*0\b", r"\b(curl|wget)\b.*\|\s*(sudo\s+)?(ba|z)?sh\b",
    r"\bsystemctl\s+(disable|mask|stop)\b", r"\blaunchctl\s+(bootout|unload|disable)\b",
    r"\bsv\s+(down|exit|force-shutdown|force-stop|kill)\b",   # sv down/exit/kill: a runit service stopped, or its runsv gone
    r"\bxbps-remove\b",                                       # xbps-remove: a package gone (apt remove and pacman -R ride under sudo)
    # the ways to delete or destroy that hid from the list before v1.30 --
    # a named line each, so any one can be argued with
    r"\bfind\b.*\s-delete\b",                      # find ... -delete
    r"\brsync\b.*\s--delete",                      # rsync --delete (and -after/-before)
    r"\bgit\s+branch\s+-D\b",                      # git branch -D: drops unmerged work
    r"\bchmod\s+(-[a-zA-Z]*R|--recursive)\b",      # chmod -R: a tree's permissions
    r"(?:^|[;&|]\s*)>(?!>)\s*\S",                  # bare `> file`: truncation, not append
    # v1.35: what the list still let through -- a named line each
    r"(?<![\d&>])>(?![>&])\s*(?!/dev/null(?:\s|$))\S",   # `cmd > file` anywhere: truncation
                                                    # (>> appends, 2> and >& move streams,
                                                    # /dev/null is nothing to lose)
    r"\bsudo\b",                                   # sudo anything: root is the blast radius
    r"\bsed\b(?:\s+\S+)*?\s+(?:-[a-zA-Z]*i\S*|--in-place)(?=\s|=|$)",   # sed -i: rewrites the file
    r"\btee\b(?![^;|&]*\s(?:-[a-zA-Z]*a[a-zA-Z]*|--append)(?=\s|$))",   # tee without -a: truncation
    r"\bshred\b",                                  # shred: gone for good
    r"\bxargs\b[^;|&]*\brm\b",                     # xargs rm: a delete fed by a list
    r"\b(?:mv|cp)\s+(?:-\S+\s+)*(?:-[a-zA-Z]*f[a-zA-Z]*|--force)(?=\s|$)",   # mv -f / cp -f: overwrites unasked
    r"\bhistory\s+-c\b",                           # history -c: the shell's own record
    r"\bgit\s+stash\s+(?:drop|clear)\b",           # git stash drop: unmerged work, gone
]
# rm with a recursive (or force) flag, short or long -- ONE pattern pair,
# shared by is_dangerous and blast, so the danger mark and the blast count
# can never disagree about what "recursive" means
_RM_FLAG = r"(?:-[a-zA-Z]+|--\S+)"
RM_RECURSIVE = re.compile(r"\brm\s+(?:%s\s+)*(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)(?=\s|$)" % _RM_FLAG)
RM_FORCE = re.compile(r"\brm\s+(?:%s\s+)*(?:-[a-zA-Z]*f[a-zA-Z]*|--force)(?=\s|$)" % _RM_FLAG)
DANGER = [re.compile(p) for p in _DANGER] + [RM_RECURSIVE, RM_FORCE]


def is_dangerous(command):
    return any(p.search(command) for p in DANGER)


# A command whose effect cannot be read from the line: what it does is
# decided by text the line does not show (another command's output, a
# string handed to an interpreter, a script on stdin, a word the shell
# rewrites), so neither is_dangerous nor a reader can judge it. Over
# `spark do --porcelain` outside the sandbox nobody reads the line
# before it runs, so such a step is refused (do._Porcelain); at a
# terminal a person reads it, and in the sandbox the kernel holds it.
# A named line each, so any one can be argued with. The patterns read
# the line as the shell does (_shell_text): the inside of '...' is
# plain text and never matches.
_INTERP = (r"(?:^|(?<=[\s;&|(]))(?:\S*/)?"
           r"(?:sh|bash|zsh|dash|ksh|fish|python[\d.]*|perl|ruby|node|php|lua|osascript)(?=$|[\s;&|)<])")
_OPTS = r"(?:\s+-\S*)*"             # the interpreter's options before what it runs
OPAQUE = (
    ("a command substitution", r"\$\("),                # $(cmd): runs what another command prints
    ("a backtick", r"`"),                               # `cmd`: the same, the old spelling
    ("eval", r"(?:^|[\s;&|(])eval(?=\s|$)"),            # eval: runs a string built at run time
    ("a backslash inside a word", r"\\"),               # r\m -rf reads as rm -rf to the shell, not to a regex
    # an interpreter handed its program on the line: sh -c, bash -lc,
    # python3 -c, perl -e / -pi -e, ruby -e, node -e / -p, lua -e, php -r
    ("an interpreter running inline code",
     _INTERP + _OPTS + r"\s+(?:-[A-Za-z]*[ceEipr][A-Za-z]*|--eval|--print|--command)(?=\s|=|$)"),
    ("an interpreter reading a script from a pipe",     # ... | python3, curl ... | sh
     r"\|\s*" + _INTERP + _OPTS + r"\s*(?:$|[;&|)])"),
    ("an interpreter reading a script from stdin",      # bash -s, python3 -
     _INTERP + _OPTS + r"\s+-s?(?=\s|$)"),
    ("an interpreter reading a redirected script",      # python3 <<EOF, sh < x.sh
     _INTERP + _OPTS + r"\s*<"),
    # curl/wget sending data out: what leaves is named elsewhere (a file,
    # a variable), never on the line
    ("an upload", r"\b(?:curl|wget)\b[^;&|]*\s(?:-[A-Za-z]*[dFT]|--data\S*|--form\S*|--json|"
                  r"--upload-file|--post-file|--post-data)(?=\s|=|$)"),
)
_OPAQUE = [(what, re.compile(p)) for what, p in OPAQUE]


def _shell_text(line):
    """`line` as the shell reads its quotes: the inside of '...' dropped
    (plain text to the shell), and inside "..." a backslash dropped with
    the character it escapes kept; an unquoted backslash is kept -- it
    is what "a backslash inside a word" looks for."""
    out, quote, i = [], "", 0
    while i < len(line):
        ch = line[i]
        if quote == "'":
            if ch == "'":
                quote = ""
                out.append(ch)
        elif quote == '"':
            if ch == "\\" and i + 1 < len(line):
                i += 1
                out.append(line[i])
            else:
                if ch == '"':
                    quote = ""
                out.append(ch)
        else:
            if ch in "'\"":
                quote = ch
            out.append(ch)
        i += 1
    return "".join(out)


def opaque(command):
    """The OPAQUE line `command` matches (its name), or '' when its
    effect can be read from the line."""
    text = _shell_text(command or "")
    return next((what for what, p in _OPAQUE if p.search(text)), "")


import shlex as _shlex


def _human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def blast(command, cwd=""):
    """The facts beside a `!` for a recursive `rm`: how many files, how many
    bytes, and how many git-tracked, under the paths it would remove. From
    the command spark already has -- nothing the model proposed is run.

    Only `rm -r...`, because that is the danger a count answers; a glob or
    an option is skipped, a path is resolved against `cwd`, and the walk is
    capped in entries and time so a huge tree cannot hang the prompt (the
    count then ends `+`). A compound line is split on `&&`, `;` and `|`
    first and only the rm segment is counted -- `cd /tmp/x && rm -rf
    build` must not count the `cd` word as an operand -- and a leading
    `cd DIR` moves the base the operands resolve against. `~` expands.
    Returns the one-line string, or `` when there is nothing honest to
    say."""
    base = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()
    rm_seg = None
    for seg in re.split(r"&&|\|\||[;|]", command):
        seg = seg.strip()
        if RM_RECURSIVE.search(seg):
            rm_seg = seg
            break
        try:
            w = _shlex.split(seg)
        except ValueError:
            w = []
        if len(w) >= 2 and w[0] == "cd":
            d = os.path.expanduser(w[1])
            base = d if os.path.isabs(d) else os.path.join(base, d)
    if rm_seg is None:
        return ""
    try:
        words = _shlex.split(rm_seg)
    except ValueError:
        return ""
    paths = []
    for w in words[1:] if words else []:
        if w == "rm" or w.startswith("-"):
            continue
        if any(c in w for c in "*?[]"):     # a glob: spark did not expand it
            return ""
        w = os.path.expanduser(w)
        paths.append(w if os.path.isabs(w) else os.path.join(base, w))
    paths = [p for p in paths if os.path.lexists(p)]
    if not paths:
        return ""
    CAP_ENTRIES, CAP_SECONDS = 200000, 0.2
    import time as _time
    files = total = 0
    capped = False
    deadline = _time.time() + CAP_SECONDS
    for p in paths:
        if os.path.isfile(p) or os.path.islink(p):
            files += 1
            try:
                total += os.lstat(p).st_size
            except OSError:
                pass
            continue
        for root, dirs, names in os.walk(p):
            for n in names:
                files += 1
                try:
                    total += os.lstat(os.path.join(root, n)).st_size
                except OSError:
                    pass
            if files >= CAP_ENTRIES or _time.time() > deadline:
                capped = True
                break
        if capped:
            break
    tracked = _tracked(paths, base)
    n = "%s%s file%s" % ("{:,}".format(files), "+" if capped else "", "" if files == 1 else "s")
    parts = [n, _human_bytes(total) + ("+" if capped else "")]
    if tracked:
        parts.append("%s tracked by git" % "{:,}".format(tracked))
    return ", ".join(parts)


def _tracked(paths, base):
    """How many of the paths git tracks, or 0 when cwd is not a repo (quiet
    on any failure -- the count is a courtesy, never a promise)."""
    import subprocess
    try:
        rel = [os.path.relpath(p, base) for p in paths]
        out = subprocess.run(["git", "-C", base, "ls-files", "-z", "--"] + rel,
                             capture_output=True, timeout=2)
        if out.returncode != 0:
            return 0
        return len([x for x in out.stdout.split(b"\0") if x])
    except (OSError, subprocess.SubprocessError):
        return 0


# The order is the order the model writes them in: llama.cpp's grammar
# follows the properties as listed. kind and danger first, then the
# command -- so `spark line` can print line 1 the moment the command
# closes, its danger already known -- then the hint, then the proof.
LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["cmd", "answer"]},
        "danger": {"type": "boolean"},
        "command": {"type": "string"},
        "hint": {"type": "string"},
        "proof": {"type": "string"},
    },
    "required": ["kind", "danger", "command", "hint", "proof"],
}

MODE_LINE = (
    "The user typed a question at the shell prompt. A question about spark itself -- its model, chat "
    "model, palette, font, engine, page, users, history, memory, speed or version -- is kind=cmd with "
    "one of spark's own commands listed above; never say spark cannot do it. "
    "If it asks for something a shell command can do, "
    "reply kind=cmd. Set danger=true when the command deletes, overwrites, kills, reboots, or changes "
    "permissions or history. Put ONE command line in `command` (no comments, no explanation inside it, "
    "no `sudo` unless unavoidable) and a `hint` of at most 70 characters saying what it does. If the "
    "question is not something a command answers, reply kind=answer, danger=false, an empty `command` "
    "and the answer in `hint` (one line, a sentence or two, at most 250 characters). For kind=cmd also "
    "fill `proof`: "
    "ONE read-only command that shows the change happened (test, ls, stat, grep, git status, "
    "systemctl is-active), or an empty string when nothing needs proving. A proof never writes, "
    "deletes, restarts or pipes."
)
MODE_ANSWER = (
    "Answer the user's question about their shell, tools, files or system. Be terse: a few lines, "
    "no preamble, no summary. Plain text for a terminal -- no markdown marks (no **, no #, no "
    "backticks, no tables); a command goes on its own line, indented four spaces. If output was "
    "pasted, read it before answering."
)
MODE_EXPLAIN = (
    "The user pasted the output of a command that did not do what they wanted. A Command: line, when "
    "present, is the exact command that ran and Exit: its status -- read them first: a typo in the "
    "command is corrected, a permission is named, a service's log is where its own message points. Say "
    "in two or three short lines what happened and what to do next, with the exact command to run on "
    "its own line, indented four spaces, when there is one. Plain text for a terminal -- no markdown "
    "marks. No preamble."
)
MODE_CHAT = (
    "This is a conversation, not the shell prompt. Talk with the user the way they talk to you: answer in "
    "plain words, at the length the question deserves, and build on the earlier turns above. Show a "
    "command only when they ask for one or it is clearly what they want, on its own line indented "
    "four spaces, with a word on what it does. Plain text for a terminal -- no markdown marks (no "
    "**, no #, no tables). If you cannot know something from here, say so."
)
# What spark knows about itself. Two static ASCII constants -- nothing
# dynamic, no version -- so the system prompt stays byte-stable and the
# prompt cache keeps working. KNOW_SHELL is the compressed map for the
# shell modes; KNOW_CHAT the same surface, grouped, for a conversation.
KNOW_SHELL = (
    "spark's own commands -- when the user asks how to change or run spark itself, "
    "answer with these: spark chat [--reveal N|auto|off]; spark do WORDS; spark serve on|off; "
    "spark check; spark update; spark theme NAME; spark model NAME|list; spark ember NAME; "
    "spark font FACE SIZE; spark quiet start|login|boot|audio on|off; spark headless on|off; "
    "spark client URL|off; spark user add|login; spark soul edit; spark memory add WORDS; "
    "spark memory on|off; spark history; spark stats|bench; spark forge on|off; spark setup; "
    "cmd | explain; spark read WORDS < text; spark ask < plan; spark drill < text; "
    "stream | spark watch WORDS; spark edit (a spark app's); spark bar (the status line). "
    "Settings live in ~/.config/spark/spark.env (SPARK_REVEAL, SPARK_MAX_TOKENS, "
    "SPARK_TIMEOUT, SPARK_HISTORY) and site.env."
)
KNOW_CHAT = (
    "You run as spark; when asked how to change or run spark itself, these are "
    "spark's own commands.\n"
    "The AI: spark chat -- a conversation; spark do WORDS -- a task, one command at "
    "a time; spark soul edit -- who it is; spark memory add WORDS -- a fact it keeps; "
    "spark ember NAME -- the chat model; spark forge on|off -- the page's server "
    "on the LAN; spark history -- the threads; spark stats|bench -- the numbers.\n"
    "The machine: spark serve on|off -- the engine; spark model NAME|list -- "
    "the table, or choose one; spark check -- every row; spark update -- "
    "the newest version; spark setup -- the guided first run; spark quiet "
    "start|login|boot|audio on|off -- a quieter machine; spark headless on|off; "
    "spark client URL|off -- another machine's spark; spark user add|login.\n"
    "Reading and writing: cmd | explain; spark read WORDS < text; spark ask < plan; "
    "spark drill < text; stream | spark watch WORDS; spark edit, from a spark app.\n"
    "The pace of a reply: spark chat --reveal N|auto|off, /reveal in a chat, "
    "SPARK_REVEAL in ~/.config/spark/spark.env (the settings file, with "
    "SPARK_MAX_TOKENS, SPARK_TIMEOUT, SPARK_HISTORY).\n"
    "The look: spark theme NAME -- the palette; spark font FACE SIZE -- the "
    "console font; spark bar -- the status line."
)
MODE_DO = (
    "You are completing a task in steps. Propose ONE shell command as kind=cmd with a one-line `hint` "
    "(at most 70 characters) saying what it does, or reply kind=done with the result in `hint` when the "
    "goal is met. Read the output of the previous step before proposing the next; if a step failed, fix "
    "it or say so. Set danger=true when the command deletes, overwrites, kills, reboots, or changes "
    "permissions. Never propose a command that needs interactive input, and never repeat a step whose "
    "output already answers the goal."
)
# A mode is named for what spark DOES. "answer" was called "ask" until
# v1.16, which read backwards beside `spark ask` (contract 12), where
# spark is the one asking. "talk" is the old name for "chat"; both old
# names stay accepted for one version, because thread and turn records
# on disk carry them. Note "ask" is NOT reused as contract 12's mode:
# a string that changes meaning would make old turn records lie.
MODE_PASTE = (
    "The user pasted these lines into their shell prompt but has NOT run them. In one sentence, "
    "say what running them would do -- name the destructive part first when there is one. Set "
    "danger=true when any line deletes, overwrites, downloads-and-runs, kills, reboots, or changes "
    "permissions, credentials or startup files. Never rewrite or repeat the paste."
)
PASTE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "danger": {"type": "boolean"},
    },
    "required": ["summary", "danger"],
}

MODES = {"line": MODE_LINE, "answer": MODE_ANSWER, "explain": MODE_EXPLAIN, "chat": MODE_CHAT,
         "ask": MODE_ANSWER, "talk": MODE_CHAT, "do": MODE_DO, "paste": MODE_PASTE}

# The editor (spark edit, contract 10): three briefs, one per kind. No
# table routes by filetype or genre -- each brief tells the model to read
# what it has in front of it and act as that kind of text deserves; the
# filetype and the file name ride in the user message as hints. Static
# strings, so each system prompt stays byte-stable for the prompt cache.
_READ = ("First read what this is: source code, or prose -- and which kind of prose "
         "(fiction, a poem, an essay, academic writing, an article, a letter, notes, "
         "documentation, a commit message). Then act as that kind deserves: code keeps "
         "its language, indentation, naming and behaviour; fiction keeps the narrator's "
         "person and tense, the dialogue punctuation and the voice; a poem keeps every "
         "line break and stanza; academic writing stays precise and formal and its "
         "citations exact; notes may stay fragments; documentation keeps every command "
         "and path as written. Prose keeps its own language unless asked to translate. "
         "If the user says what the text is, believe them over your reading. ")
MODE_EDIT_COMPLETE = (
    "You are completing text inside an editor; the text before and after the cursor "
    "follows. " + _READ +
    "Write only what goes at the cursor -- the rest of the sentence, statement, paragraph "
    "or block, at most a short paragraph or a few lines -- matching the voice, style and "
    "indentation around it. Begin exactly where the cursor is: when a space or a line "
    "break belongs between the text before the cursor and yours, write it first. No "
    "preamble, no explanation, no code fences, never repeat the text before the cursor.")
MODE_EDIT_REWRITE = (
    "You are editing text inside an editor; the instruction comes first, then the text. "
    + _READ +
    "The text is the author's, not yours: keep their voice, their word choices where the "
    "instruction does not touch them, their language. Reply with the whole rewritten text "
    "and nothing else: no preamble, no explanation, no code fences, no quotation marks "
    "around it. Keep the indentation, the line breaks and the final newline as they are; "
    "change only what the instruction asks; never leave a placeholder. When the label says "
    "a selected part, the text is a fragment of a larger file -- a word, a line, a "
    "paragraph, a function -- and you reply with exactly what replaces that fragment: not a "
    "line before it, not a line after it, nothing the fragment did not cover. If the "
    "instruction cannot be done to this text, return the text exactly as it was.")
MODE_EDIT_ANSWER = (
    "The user asks about the text shown below, inside an editor, their own file as written. " + _READ +
    "You are a good reader in the room, not a report generator: plain text for a narrow "
    "editor pane, no markdown marks (no **, no #, no tables, no headings), a line of code "
    "on its own line indented four spaces. Every note must be impossible to write about a "
    "different draft: point at the text by quoting it between double quotes, character for "
    "character, at most twelve words and never across a line -- every quote is checked "
    "against the text, and a misquote is a fabrication. Your own wording never goes in "
    "double quotes: write it plain, after a colon or an arrow (->). When asked to review: two or three "
    "sentences on the whole, then at most five numbered notes, each a quote and what to "
    "change and why -- bugs and correctness before style in code; voice, pacing, clarity "
    "and structure in prose, grammar only where it gets in the way. Do not open with "
    "praise and do not spend a note on what is fine: the sentences say what the text does "
    "and where it is weakest, every note names a change. When little needs saying, say "
    "little; that you would change nothing is an answer. Do not rewrite unless asked; when asked for wording, offer one "
    "version, theirs to discard. Never claim to remember earlier drafts or turns. Answer "
    "in the text's own language. When the text carries the lines [selection starts] and "
    "[selection ends], the question is about what lies between them and the rest is "
    "context: never quote or comment on the mark lines themselves. In a continued "
    "exchange, the text is the one shown earlier unless a newer one is given.")
# The discuss brief (spark edit ? --source): the same machinery as
# edit-answer -- threads, the ember, quotes checked and MARKED not
# dropped -- but the text is a PUBLISHED source the reader is talking
# about, not their draft. The reading surfaces (spark-w3m, spark-newsboat)
# pass --source; the editors never do. Found 2026-09-14: gemma reviewed a
# priced web page ("Rephrase to...", "Consider adding...") and concluded
# it named no price while it named four -- the editor's posture reading a
# page. This brief forbids the edit posture and answers the question.
MODE_EDIT_DISCUSS = (
    "The reader shows you a PUBLISHED text below -- a web page, an article, a document, a "
    "message -- and asks a question about it. It is not their draft and you are not its "
    "editor: never suggest edits, rephrasings, or improvements to it, never a numbered "
    "list of changes, never 'rephrase', 'consider adding', 'break this into', 'could be "
    "clearer'. " + _READ +
    "Answer the reader's QUESTION from the text: say plainly what it says, and when it "
    "settles the question give the answer first -- if they ask whether it names a price "
    "and it does, the price is the answer, not a note about the pricing table. Support "
    "what you say by quoting the text between double quotes, character for character, at "
    "most twelve words and never across a line -- every quote is checked, and one the "
    "text does not hold is marked where it stands, never invented. Your own wording never "
    "goes in double quotes: write it plain, after a colon or an arrow (->). Take a "
    "position when they ask for one; say what the text does not settle when it does not. "
    "Plain text for a narrow pane, no markdown marks (no **, no #, no tables, no "
    "headings); a few lines, fewer when fewer answer. Never claim to remember earlier "
    "drafts. Answer in the language of the QUESTION. In a continued exchange, the text is "
    "the one shown earlier unless a newer one is given.")
# The reading that precedes a question: the model says what the text is
# (language, kind) from its first 800 chars, and that reading is restated
# in the request. A small model drifts -- an English draft answered in
# Portuguese, an essay reviewed as "the poem" -- until the fact is stated;
# stating the model's own reading keeps the judgment its own.
MODE_EDIT_READ = (
    "Say what this text is, in two short fields: `language` (the natural language it is "
    "written in, or 'code') and `kind` (source code, fiction, poem, essay, academic, "
    "article, letter, notes, documentation, commit message, or your own word). Weigh the "
    "form as well as the content: short lines and stanza breaks mean a poem even when the "
    "sentences read as prose. Nothing else.")
READ_SCHEMA = {
    "type": "object",
    "properties": {"language": {"type": "string"}, "kind": {"type": "string"}},
    "required": ["language", "kind"],
}
REVIEW = "Review this."
# The questioner (spark ask, contract 12). The law is enforced after the
# model, not by it -- a line that is not a question never reaches the
# reader -- but a brief that asks for the right shape wastes fewer
# tokens getting there. It is told what is thrown away, so a small model
# spends its three lines on questions instead of a preamble.
MODE_ASK_QUESTIONS = (
    "The author shows you something they are working on -- a plan, a draft, a decision -- "
    "and you reply with questions about it and nothing else. Every line you write is one "
    "question ending in a question mark: no preamble, no summary, no heading, no numbering, "
    "no markdown marks, no closing line. A line that is not a question is thrown away "
    "before the author sees it, so do not write one. At most three questions, fewer when "
    "fewer are worth asking, none at all when the text answers everything you would ask -- "
    "saying nothing is an answer here. Ask what this text and no other would provoke: a "
    "question that could be asked of any plan is thrown away too. To point at the text, "
    "weave a short piece of it -- character for character, at most twelve words, never "
    "across a line -- into your question between double quotes. The quotes are for the "
    "text's words inside your question, never around the question itself: the last "
    "character of every line is the question mark. Every quote is checked against the "
    "text, and a question whose quotes are not in it is thrown away. Never state a fact, never answer your own "
    "question, never say what you would do or what the author should do: you are the one "
    "who asks. Ask in the text's own language.")
# The reader (spark read, contract 11). The same law as contract 12,
# turned from questions to claims: every line is checked against the
# source and dropped unless a quote in it anchors -- a line that quotes
# nothing is dropped too, because a claim about a source must show the
# source. The brief says what is thrown away so a small model spends its
# lines pointing at the source instead of summarising from memory.
MODE_READ_SOURCE = (
    "The reader hands you a source -- a page, a message, a document -- and asks about "
    "it. You answer from the source and nowhere else: what the source does not say, "
    "you do not say. Every line you write points at the source by weaving a short "
    "piece of it -- character for character, at most twelve words, never across a "
    "line -- between double quotes into your own words. Every quote is checked "
    "against the source: a line whose quotes are not in it is thrown away before the "
    "reader sees it, and so is a line that quotes nothing, so write no preamble, no "
    "heading, no closing line. Plain text, no markdown marks; a few lines, fewer when "
    "fewer answer. Never add what you know from elsewhere, never guess past the "
    "source's edge, never write 'the text does not mention': when the source does not "
    "answer, write nothing at all -- the refusal is composed for you. Answer in the "
    "source's own language.")
RECALL_SCHEMA = {
    "type": "object",
    "properties": {"candidates": {"type": "array", "items": {"type": "string"}}},
    "required": ["candidates"],
}
# intent search (spark recall). The shell hands its history on stdin; the
# model matches intent, not text. Every candidate is checked against the
# history afterwards, so it can only ever return a line that actually ran
# -- the brief asks it to copy lines verbatim, never to compose.
MODE_RECALL = (
    "The user describes a command they ran before, in their own words, and you find it "
    "in their shell history below. Reply with the matching command lines from the history, "
    "copied CHARACTER FOR CHARACTER -- never edited, never composed, never explained. At "
    "most five, best match first, fewer when fewer fit, none when nothing in the history "
    "matches. A line you return that is not in the history verbatim is thrown away, so copy, "
    "do not reconstruct. `candidates` is the list; nothing else.")
DRILL_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
        "required": ["question", "answer"]}}},
    "required": ["items"],
}
# the drill (spark drill, contract 13). Both halves come from the source:
# the answer is a verbatim span of it and the question is one that span
# answers. The grounding is enforced in code -- an item whose answer does
# not anchor in the source is dropped before it is ever asked -- but a
# brief that asks for spans, not prose, wastes fewer tokens getting there.
MODE_DRILL_ITEMS = (
    "You are given a source and you turn it into practice questions. For each item, choose "
    "a short span OF THE SOURCE, word for word, as the answer -- at most a dozen words, "
    "never across a line -- and write a question that this span, and this span alone, "
    "answers. Both the question and the answer come from the source; invent neither. An "
    "answer that is not a verbatim piece of the source is thrown away before it is ever "
    "asked, and a drill built on an invented answer teaches the invention. Ask what the "
    "source actually establishes -- a fact, a name, a number, a definition -- not what it "
    "merely mentions in passing. `items` is the list, each with `question` and `answer`; a "
    "handful is plenty, fewer when the source is thin, none at all when it holds nothing "
    "worth drilling. Ask in the source's own language.")
# the watcher (spark watch, contract 14). Silent until a line matches what
# the reader named, then one line quoting the match. The law is enforced
# after the model (text.Gate): a line whose quote is not among the ones it
# was shown is dropped, so silence is the honest answer when nothing matches.
MODE_WATCH = (
    "You watch a live stream -- log lines, build output, a running process -- for the one "
    "thing the reader named. Most of what flows past does not matter, and you say nothing "
    "about it. When a line matches what they asked for, reply with ONE line: a few words of "
    "your own, then the matching line's own text between double quotes, word for word. "
    "Every quote is checked against the lines you were shown, and a line whose quote is not "
    "among them is thrown away -- so quote what is really there, never what you expect to "
    "see. A line that only reports progress or state -- a task started, a slot chosen, a "
    "request served, a file opened -- is not a match unless the reader asked for exactly "
    "that; it is silence. No preamble, no summary, no 'nothing yet': when nothing matches, "
    "answer with nothing at all. Silence is the normal, healthy state.")
MODES.update({"edit-complete": MODE_EDIT_COMPLETE, "edit-rewrite": MODE_EDIT_REWRITE,
              "edit-answer": MODE_EDIT_ANSWER, "edit-discuss": MODE_EDIT_DISCUSS,
              "edit-read": MODE_EDIT_READ,
              "ask-questions": MODE_ASK_QUESTIONS, "read-source": MODE_READ_SOURCE,
              "drill-items": MODE_DRILL_ITEMS, "watch-stream": MODE_WATCH,
              "recall": MODE_RECALL})


def _tools_line():
    have = [t for t in PREFERRED if shutil.which(t)]
    return ("Preferred when installed (they are): " + ", ".join(have) + ".") if have else ""


def prefix(cfg, shell):
    """The stable part of the system prompt for this machine and shell."""
    pm = package_manager()
    lines = [
        "You are spark, the assistant at %s's shell prompt on %s: %s, %s, shell %s. Keyboard only, no GUI."
        % (cfg.user, cfg.name, os_pretty(), platform.machine(), shell),
    ]
    if pm:
        lines.append("Package manager: %s." % pm)
    mac = platform.system() == "Darwin"
    from . import init_shape
    runit = not mac and init_shape() == "runit"       # Void: sv in place of systemctl, svlogd in place of the journal
    lines.append("System tools: " + ("launchctl, pbcopy, pbpaste, open, mdfind, diskutil." if mac
                                     else "sv, svlogd, ip." if runit else "systemctl --user, journalctl, ip."))
    # a command pasted from a page is written for someone else's machine.
    # These are this OS's side of the pairs a paste crosses most; the model
    # is told to rewrite the other side and say so. This OS's half only, so
    # the prefix stays byte-stable per machine (the prompt cache needs it).
    if mac:
        lines.append("On this machine free is vm_stat, apt/dnf is brew, systemctl is "
                     "launchctl, xdg-open is open, ls --color is ls -G, sed -i is sed -i ''. "
                     "A command written for Linux: rewrite it for macOS and say so in the hint.")
    else:
        lines.append("On this machine vm_stat is free, brew is %s, launchctl is %s, "
                     "open is xdg-open, ls -G is ls --color, sed -i '' is sed -i. "
                     "A command written for macOS: rewrite it for this machine and say so in "
                     "the hint." % (pm or "the package manager", "sv" if runit else "systemctl"))
    t = _tools_line()
    if t:
        lines.append(t)
    lines.append(FLAGS)
    lines.append(KNOW_SHELL)
    lines.append("Never invent flags or paths.")
    return "\n".join(lines)


def machine_line(cfg, local=False):
    """The one machine fact a conversation needs. The full prefix is for
    the shell modes (line/ask/explain/do); chat sheds the costume. A
    person's own session (local) on a Linux with no display is told so: a
    small model on a Void console answered a font question with
    Alacritty's config. The page's server is no session: its environment
    says nothing about the browser at the other end."""
    line = "You are on %s's machine %s: %s, %s." % (cfg.user, cfg.name, os_pretty(), platform.machine())
    if local and platform.system() == "Linux" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        line += " This session has no graphical display: a text console or an ssh login."
    return line


def mode_prefix(cfg, mode, shell, local=False):
    """The stable part of the system prompt for a mode: one machine line
    plus spark's own commands for a conversation (chat), the whole shell
    brief for everything else."""
    if mode in ("chat", "talk"):
        return machine_line(cfg, local) + "\n" + KNOW_CHAT
    if mode.startswith(("edit-", "ask-", "read-", "drill-", "watch-")):
        # over a text -- in an editor, a plan on stdin, a source to drill,
        # a stream to watch -- the shell brief (tools, flags, spark's verbs)
        # is noise for prose and code alike, and it costs prompt
        return machine_line(cfg, local)
    return prefix(cfg, shell)


# Words the shell answers to itself: a proposed command whose head word is
# one of these needs no binary on PATH.
SH_BUILTINS = frozenset((
    "cd", "echo", "export", "set", "unset", "source", ".", "alias", "type", "printf",
    "test", "[", "kill", "wait", "jobs", "fg", "bg", "read", "eval", "exec", "shift",
    "trap", "umask"))


# a proof is read-only or it is not a proof: the head words contract 4's
# optional third line may start with -- a named list, one look, so it
# can be argued with. git/systemctl/sv/launchctl only with their read subs.
PROOF_HEADS = ("test", "[", "ls", "stat", "grep", "wc", "file", "du", "df",
               "head", "tail", "pgrep", "which", "diff", "cmp", "readlink")
PROOF_PAIRS = (("git", ("status", "log", "diff", "show", "ls-files")),
               ("systemctl", ("is-active", "is-enabled", "status")),
               ("sv", ("status", "check")),
               ("launchctl", ("print", "list")))
# the options that turn a read-only head into a writer or a runner: a
# proof carrying one anywhere in its argv is refused. A named line each,
# so any one can be argued with; the heads after an option scope it to
# the tools where it is the danger (`test -f` and `stat -c` are proofs,
# `tail -f` and `git -c` are not), () means every head. A one-letter
# option is caught inside a cluster too (`tail -fn 5`).
PROOF_DENIED = (
    ("--output", ()),           # git diff/log --output PATH (or =PATH): writes PATH
    ("-o", ()),                 # the short spelling of an output file
    ("--ext-diff", ()),         # git diff --ext-diff: runs diff.external
    ("--textconv", ()),         # git diff/show --textconv: runs a filter
    ("-f", ("tail",)),          # tail -f: never returns
    ("-F", ("tail",)),          # tail -F: the same, with retries
    ("--follow", ("tail",)),    # tail --follow, likewise
    ("-c", ("git",)),           # git -c KEY=VAL: config injection (core.pager, diff.external)
    ("--exec", ()),             # anything that runs a command per result
    ("-exec", ()),              # find -exec
    ("-execdir", ()),           # find -execdir
    ("-delete", ()),            # find -delete
)


def _denied(opt, arg):
    """Does this argv word carry the denied option: the option itself,
    `--long=value`, or a one-letter option inside a cluster (`-fn`)."""
    if arg == opt or (opt.startswith("--") and arg.startswith(opt + "=")):
        return True
    return len(opt) == 2 and re.match(r"-[A-Za-z]+$", arg) is not None and opt[1] in arg[1:]


def proof_ok(command):
    """Is this line fit to be a proof: a single read-only command --
    allowlisted head word, no compound, no redirect, no control
    character, nothing dangerous, and none of PROOF_DENIED anywhere in
    its argv (`git diff --output PATH` truncates PATH; `head SECRET
    /nope` prints the secret and exits 1). A proof that is not read-only
    is refused: never printed, never run."""
    c = (command or "").strip()
    if not c or is_dangerous(c) or re.search(r"[;&|<>`$]", c):
        return False
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in c):
        return False
    try:
        w = _shlex.split(c)
    except ValueError:
        return False
    if not w:
        return False
    head = w[0]
    if head not in PROOF_HEADS and not any(
            head == h and len(w) > 1 and w[1] in subs for h, subs in PROOF_PAIRS):
        return False
    for opt, heads in PROOF_DENIED:
        if heads and head not in heads:
            continue
        if any(_denied(opt, a) for a in w[1:]):
            return False
    return True


def missing_word(command):
    """The command's head word when nothing on this machine answers to it,
    else ''. A leading sudo/env/nohup is skipped; a shell builtin, a path,
    an assignment or anything `which` finds counts as found. '' always
    means go ahead -- this guard never blocks."""
    words = (command or "").split()
    while words and words[0] in ("sudo", "env", "nohup"):
        words = words[1:]
    w = words[0] if words else ""
    # spark's own words are here by definition -- this very process is
    # spark -- even where ~/.local/bin is not on PATH (a plain ssh HOST
    # '...', a script): `spark model list` was once told "spark: not on
    # this machine"
    if not w or "=" in w or "/" in w or w in SH_BUILTINS or w in ("spark", "explain") or shutil.which(w):
        return ""
    return w


def system(cfg, mode, shell):
    """prefix + identity (soul, memory) + the mode's task; see forge."""
    from . import forge
    return forge.system(cfg, mode, shell)


def user_message(text, cwd, context=""):
    """What is sent about the request: the directory path, the line, and
    (explain / piped input) the tail of the output, or the text of the
    @FILEs named (forge.file_context labels those itself). Nothing else."""
    head = "[cwd %s]\n" % cwd if cwd else ""
    if context:
        # an @FILE block, the editor's and the questioner's blocks, and the
        # widget's failure block (Command:/Exit:/Output:) carry their own label
        labelled = context.startswith(("File ", "Text", "Selected ", "Plan ", "Source",
                                       "The author says", "You read this as",
                                       "Declined before", "Answered before", "Command: "))
        label = "" if labelled else "Output:\n"
        return head + (text + "\n\n" if text else "") + label + context
    return head + text
