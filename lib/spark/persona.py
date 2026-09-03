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
    "commands in backticks, no preamble, no summary. If output was pasted, read it before answering."
)
MODE_EXPLAIN = (
    "The user pasted the output of a command that did not do what they wanted. Say in two or three "
    "short lines what happened and what to do next, with the exact command to run in backticks when "
    "there is one. No preamble."
)
MODE_CHAT = (
    "This is a conversation, not the shell prompt. Talk with the user the way they talk to you: answer in "
    "plain words, at the length the question deserves, and build on the earlier turns above. Show a "
    "command only when they ask for one or it is clearly what they want, in backticks, with a word on "
    "what it does. If you cannot know something from here, say so."
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
    lines.append("Never invent flags or paths.")
    return "\n".join(lines)


def machine_line(cfg):
    """The one machine fact a conversation needs. The full prefix is for
    the shell modes (line/ask/explain/do); chat sheds the costume."""
    return "You are on %s's machine %s: %s, %s." % (cfg.user, cfg.name, os_pretty(), platform.machine())


def mode_prefix(cfg, mode, shell):
    """The stable part of the system prompt for a mode: one machine line
    for a conversation (chat), the whole shell brief for everything else."""
    if mode in ("chat", "talk"):
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
        label = "" if context.startswith("File ") else "Output:\n"
        return head + (text + "\n\n" if text else "") + label + context
    return head + text
