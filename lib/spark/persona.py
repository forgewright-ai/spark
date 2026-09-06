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

_DANGER = [
    r"\brm\s+(-[a-zA-Z]*[rRf][a-zA-Z]*\s+)+",      # rm -rf, rm -r, rm -f ...
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
    r"\bsudo\s+rm\b", r"\bsystemctl\s+(disable|mask|stop)\b", r"\blaunchctl\s+(bootout|unload|disable)\b",
]
DANGER = [re.compile(p) for p in _DANGER]


def is_dangerous(command):
    return any(p.search(command) for p in DANGER)


LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["cmd", "answer"]},
        "command": {"type": "string"},
        "hint": {"type": "string"},
        "danger": {"type": "boolean"},
    },
    "required": ["kind", "command", "hint", "danger"],
}

MODE_LINE = (
    "The user typed a question at the shell prompt. If it asks for something a shell command can do, "
    "reply kind=cmd with ONE command line in `command` (no comments, no explanation inside it, no `sudo` "
    "unless unavoidable) and a `hint` of at most 70 characters saying what it does. Set danger=true when "
    "the command deletes, overwrites, kills, reboots, or changes permissions or history. If the question "
    "is not something a command answers, reply kind=answer with the answer in `hint` (one line, at most "
    "70 characters) and an empty `command`."
)
MODE_ASK = (
    "Answer the user's question about their shell, tools, files or system. Be terse: a few lines, "
    "no preamble, no summary. Plain text for a terminal -- no markdown marks (no **, no #, no "
    "backticks, no tables); a command goes on its own line, indented four spaces. If output was "
    "pasted, read it before answering."
)
MODE_EXPLAIN = (
    "The user pasted the output of a command that did not do what they wanted. Say in two or three "
    "short lines what happened and what to do next, with the exact command to run on its own line, "
    "indented four spaces, when there is one. Plain text for a terminal -- no markdown marks. "
    "No preamble."
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
    "answer with these: spark chat; spark do WORDS; spark serve|stop; spark check; "
    "spark update; spark theme NAME; spark model NAME|list; spark ember NAME; "
    "spark font FACE SIZE; spark quiet start|login|boot on|off; spark shell on|off; "
    "spark bar on|off; spark soul edit; spark remember WORDS; spark history; "
    "spark stats|bench; spark forge on|off; spark setup."
)
KNOW_CHAT = (
    "You run as spark; when asked how to change or run spark itself, these are "
    "spark's own commands.\n"
    "The AI: spark chat -- a conversation; spark do WORDS -- a task, one command at "
    "a time; spark soul edit -- who it is; spark remember WORDS -- a fact it keeps; "
    "spark ember NAME -- the conversational model; spark forge on|off -- the FORGE "
    "on the LAN; spark history -- the threads; spark stats|bench -- the numbers.\n"
    "The machine: spark serve|stop -- the model server; spark model NAME|list -- "
    "the table, or choose one; spark check -- the drift report; spark update -- "
    "the newest version; spark setup -- the guided first run; spark shell on|off "
    "-- the shell layer; spark quiet start|login|boot on|off -- a quieter machine.\n"
    "The look: spark theme NAME -- the palette; spark font FACE SIZE -- the "
    "console font; spark bar on|off -- the tmux status line."
)
MODE_DO = (
    "You are completing a task in steps. Propose ONE shell command as kind=cmd with a one-line `hint` "
    "(at most 70 characters) saying what it does, or reply kind=done with the result in `hint` when the "
    "goal is met. Read the output of the previous step before proposing the next; if a step failed, fix "
    "it or say so. Set danger=true when the command deletes, overwrites, kills, reboots, or changes "
    "permissions. Never propose a command that needs interactive input, and never repeat a step whose "
    "output already answers the goal."
)
# "talk" is the old name for "chat": old thread and turn records carry it,
# so it stays an accepted alias for one version.
MODES = {"line": MODE_LINE, "ask": MODE_ASK, "explain": MODE_EXPLAIN, "chat": MODE_CHAT, "talk": MODE_CHAT, "do": MODE_DO}

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
MODE_EDIT_ASK = (
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
MODES.update({"edit-complete": MODE_EDIT_COMPLETE, "edit-rewrite": MODE_EDIT_REWRITE,
              "edit-ask": MODE_EDIT_ASK, "edit-read": MODE_EDIT_READ})


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
    lines.append("System tools: " + ("launchctl, pbcopy, pbpaste, open, mdfind, diskutil."
                                     if platform.system() == "Darwin" else "systemctl --user, journalctl, ip."))
    t = _tools_line()
    if t:
        lines.append(t)
    lines.append(FLAGS)
    lines.append(KNOW_SHELL)
    lines.append("Never invent flags or paths.")
    return "\n".join(lines)


def machine_line(cfg):
    """The one machine fact a conversation needs. The full prefix is for
    the shell modes (line/ask/explain/do); chat sheds the costume."""
    return "You are on %s's machine %s: %s, %s." % (cfg.user, cfg.name, os_pretty(), platform.machine())


def mode_prefix(cfg, mode, shell):
    """The stable part of the system prompt for a mode: one machine line
    plus spark's own commands for a conversation (chat), the whole shell
    brief for everything else."""
    if mode in ("chat", "talk"):
        return machine_line(cfg) + "\n" + KNOW_CHAT
    if mode.startswith("edit-"):
        # inside an editor the shell brief (tools, flags, spark's verbs)
        # is noise for prose and code alike, and it costs prompt
        return machine_line(cfg)
    return prefix(cfg, shell)


# Words the shell answers to itself: a proposed command whose head word is
# one of these needs no binary on PATH.
SH_BUILTINS = frozenset((
    "cd", "echo", "export", "set", "unset", "source", ".", "alias", "type", "printf",
    "test", "[", "kill", "wait", "jobs", "fg", "bg", "read", "eval", "exec", "shift",
    "trap", "umask"))


def missing_word(command):
    """The command's head word when nothing on this machine answers to it,
    else ''. A leading sudo/env/nohup is skipped; a shell builtin, a path,
    an assignment or anything `which` finds counts as found. '' always
    means go ahead -- this guard never blocks."""
    words = (command or "").split()
    while words and words[0] in ("sudo", "env", "nohup"):
        words = words[1:]
    w = words[0] if words else ""
    if not w or "=" in w or "/" in w or w in SH_BUILTINS or shutil.which(w):
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
        # an @FILE block and the editor's blocks carry their own label
        labelled = context.startswith(("File ", "Text", "Selected ", "The author says", "You read this as", "Declined before"))
        label = "" if labelled else "Output:\n"
        return head + (text + "\n\n" if text else "") + label + context
    return head + text
