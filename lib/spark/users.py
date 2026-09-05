# spark.users -- the named users of this FORGE, and this machine's login.
#
# Each user owns ~/.local/state/spark/users/<name>/ (0700): token.hash
# (the lookup verifier), key (the data key, wrapped by the token --
# vault.py), threads/, memory, chat-history. The box never stores a
# token or a data key in the clear: only the user's token opens their
# data, and a lost token is lost history, by design.
#
# The local login is two 0600 files beside it: `account` (name and
# token: who this machine acts as) and `account-key` (the unwrapped
# data key, so the hot paths never pay scrypt). On the box that means
# your OS login can read your own chat data -- and nobody else's; a
# stolen disk is ciphertext plus the full-disk story (spark check's
# encryption row).

import base64
import os
import re
import shutil
import time

from . import (ACCOUNT_FILE, ACCOUNT_KEY_FILE, MARK, THREADS_DIR, USERS_DIR,
               confirm, say, state_dir, vault)

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")

USAGE = """%s user -- the named users of this FORGE

  spark user                  who this machine is; the box's users
  spark user list             the table: name, threads, last activity
  spark user add NAME         mint an account; the token is shown once
  spark user remove NAME      delete the account and its sealed data
  spark user login [NAME]     paste a token: this machine acts as NAME
  spark user logout           forget the login (the sealed data stays)
  spark user token --new      rotate your token; other logins die
  spark user claim            seal the pre-v1.4 plaintext history into
                              your store (re-runnable, verifies first)

  A name is a-z, 0-9 and -, starting with a letter, at most 32 chars.
  The token is the only key to the data: keep it, there is no reset.
""" % MARK


def legacy_threads():
    """How many pre-v1.4 plaintext thread files still sit in the old dir."""
    try:
        return sum(1 for f in os.listdir(THREADS_DIR) if f.endswith(".jsonl"))
    except OSError:
        return 0


# ------------------------------------------------------------ the store
def user_dir(name):
    return os.path.join(USERS_DIR, name)


def valid_name(name):
    return bool(NAME_RE.match(name or ""))


def sanitize(name):
    """A display name folded into a valid user name, else 'owner'."""
    base = re.sub(r"[^a-z0-9-]+", "-", (name or "").lower()).strip("-")[:32]
    return base if valid_name(base) else "owner"


def list_users():
    try:
        return sorted(n for n in os.listdir(USERS_DIR)
                      if os.path.isdir(os.path.join(USERS_DIR, n)))
    except OSError:
        return []


def exists(name):
    return os.path.isfile(os.path.join(user_dir(name), "key"))


def add(name):
    """Mint the account; returns the token -- shown once, never stored."""
    import secrets
    state_dir()
    os.makedirs(USERS_DIR, mode=0o700, exist_ok=True)
    os.chmod(USERS_DIR, 0o700)
    d = user_dir(name)
    os.makedirs(d, mode=0o700)
    os.makedirs(os.path.join(d, "threads"), mode=0o700)
    token = secrets.token_urlsafe(32)
    vault.write_private(os.path.join(d, "token.hash"),
                        (vault.token_hash(token) + "\n").encode())
    vault.write_private(os.path.join(d, "key"),
                        vault.wrap_key(vault.new_key(), token, name).encode())
    return token


def remove(name):
    shutil.rmtree(user_dir(name))


def find_by_token(token):
    """The user a token belongs to, by its hash, or ''."""
    import hmac
    h = vault.token_hash(token)
    for name in list_users():
        try:
            with open(os.path.join(user_dir(name), "token.hash"),
                      encoding="utf-8") as f:
                if hmac.compare_digest(h, f.read().strip()):
                    return name
        except OSError:
            continue
    return ""


def unlock(name, token):
    """The user's data key, or vault.SealError on a wrong token."""
    return vault.unwrap_key(os.path.join(user_dir(name), "key"), token, name)


def rotate(name, token):
    """A new token for the same data key; the old token dies. Returns the
    new token or raises vault.SealError."""
    import secrets
    dk = unlock(name, token)
    new = secrets.token_urlsafe(32)
    d = user_dir(name)
    vault.write_private(os.path.join(d, "token.hash"),
                        (vault.token_hash(new) + "\n").encode())
    vault.write_private(os.path.join(d, "key"),
                        vault.wrap_key(dk, new, name).encode())
    return new


# ------------------------------------------------------------ the login
def account():
    """(name, token) of this machine's login, or ('', '')."""
    name = token = ""
    try:
        with open(ACCOUNT_FILE, encoding="utf-8") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k == "name":
                    name = v
                elif k == "token":
                    token = v
    except OSError:
        pass
    return (name, token) if name and token else ("", "")


def account_key():
    """The logged-in data key (bytes), or None -- client machines and
    logged-out machines have none."""
    try:
        with open(ACCOUNT_KEY_FILE, encoding="utf-8") as f:
            dk = base64.b64decode(f.read().strip(), validate=True)
        return dk if len(dk) == vault.DK_LEN else None
    except (OSError, ValueError):
        return None


def write_login(name, token, dk=None):
    state_dir()
    vault.write_private(ACCOUNT_FILE, ("name=%s\ntoken=%s\n" % (name, token)).encode())
    if dk is not None:
        vault.write_private(ACCOUNT_KEY_FILE, base64.b64encode(dk) + b"\n")


def logout():
    for p in (ACCOUNT_FILE, ACCOUNT_KEY_FILE):
        try:
            os.remove(p)
        except OSError:
            pass


# ------------------------------------------------------------ the verb
def _thread_stats(name):
    """(count, newest mtime) of a user's threads."""
    d = os.path.join(user_dir(name), "threads")
    count, newest = 0, 0.0
    try:
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if os.path.isfile(p):
                count += 1
                newest = max(newest, os.path.getmtime(p))
    except OSError:
        pass
    return count, newest


def _show():
    me = account()[0]
    if me:
        say("account  this machine is %s" % me)
    else:
        say("account  no login -- spark user login NAME")
    names = list_users()
    if not names:
        say("users    none yet -- spark user add NAME")
        return 0
    say("users    %d" % len(names))
    for n in names:
        count, newest = _thread_stats(n)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(newest)) if newest else "-"
        mark = " (you)" if n == me else ""
        say("  %-20s %3d thread%s  %s%s" % (n, count, "" if count == 1 else "s", when, mark))
    return 0


def _ask_token():
    import getpass
    try:
        if os.isatty(0):
            return getpass.getpass("token: ").strip()
        return input().strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def cmd_add(args):
    show = "--show-token" in args
    names = [a for a in args if not a.startswith("-")]
    if len(names) != 1:
        say(USAGE.rstrip())
        return 2
    name = names[0]
    if not valid_name(name):
        say("spark user: a name is a-z, 0-9 and -, starting with a letter, at most 32 chars")
        return 2
    if exists(name):
        say("spark user: %s already exists" % name)
        return 2
    token = add(name)
    say("ok     user         %s" % name)
    if os.isatty(1) or show:
        say("")
        say("  the token -- shown once, never stored; it is the only key:")
        say("  %s" % token)
        say("")
    else:
        say("spark user: the token is shown only at a terminal (--show-token to print it here)")
    if not account()[0]:
        try:
            write_login(name, token, unlock(name, token))
            say("ok     account      this machine is %s" % name)
        except vault.SealError:
            pass
    n = legacy_threads()
    if n and account()[0] == name and os.isatty(0):
        if confirm("claim the %d existing plaintext thread%s into %s -- sealed, then removed"
                   % (n, "" if n == 1 else "s", name)):
            return cmd_claim()
        say("spark user: left as they are -- spark user claim moves them later")
    return 0


def _claim_files(name, dk):
    """Seal the pre-v1.4 plaintext memory and chat-history into a user's
    store (merging with anything already sealed), then remove them."""
    from . import CHAT_HISTORY_FILE, MEMORY_FILE
    moved = []
    for src, fname, kind in ((MEMORY_FILE, "memory", "memory"),
                             (CHAT_HISTORY_FILE, "chat-history", "chathist")):
        if not os.path.isfile(src):
            continue
        try:
            with open(src, encoding="utf-8", errors="replace") as f:
                legacy = [ln for ln in f.read().splitlines()]
            path = os.path.join(user_dir(name), fname)
            have = []
            if os.path.isfile(path):
                recs = vault.read_sealed(path, dk)
                have = recs[0].decode("utf-8", "replace").splitlines() if recs else []
            merged = have + [ln for ln in legacy if ln not in have]
            vault.write_sealed(path, dk, kind, name,
                               "".join(ln + "\n" for ln in merged).encode("utf-8"))
            os.remove(src)
            moved.append(fname)
        except (OSError, vault.SealError):
            continue
    return moved


def cmd_claim():
    name, token = account()
    if not name:
        say("spark user: no login here -- spark user login NAME first")
        return 2
    if not exists(name):
        say("spark user: %s's sealed store is not on this machine -- claim on the box" % name)
        return 2
    dk = account_key()
    if dk is None:
        try:
            dk = unlock(name, token)
        except vault.SealError:
            say("spark user: the stored token no longer opens %s's key -- spark user login again" % name)
            return 1
    from . import forge
    moved = forge.claim_legacy(name, dk)
    for what in _claim_files(name, dk):
        say("ok     claim        %s sealed into %s" % (what, name))
    left = legacy_threads()
    if moved or not left:
        say("ok     claim        %d thread%s sealed into %s%s"
            % (moved, "" if moved == 1 else "s", name,
               "" if not left else "; %d left (unreadable)" % left))
        return 0
    say("spark user: nothing moved -- %d plaintext thread%s left" % (left, "" if left == 1 else "s"))
    return 1


def cmd_remove(args):
    if len(args) != 1:
        say(USAGE.rstrip())
        return 2
    name = args[0]
    if not exists(name):
        say("spark user: no user named %s" % name)
        return 2
    if not confirm("remove user %s and every sealed thread -- unrecoverable" % name):
        say("spark user: kept")
        return 0
    remove(name)
    if account()[0] == name:
        logout()
    say("ok     user         %s removed" % name)
    return 0


def cmd_login(args):
    name = args[0] if args else ""
    if name and not valid_name(name):
        say("spark user: a name is a-z, 0-9 and -, starting with a letter, at most 32 chars")
        return 2
    token = _ask_token()
    if not token:
        say("spark user: no token given")
        return 2
    local = list_users()
    if not local:
        # a client machine: the sealed store lives on the box; the FORGE
        # verifies the token on first use
        if not name:
            say("spark user: on this machine say who you are -- spark user login NAME")
            return 2
        write_login(name, token)
        say("ok     account      this machine is %s (verified by the FORGE on first use)" % name)
        return 0
    found = find_by_token(token)
    if name and found and name != found:
        say("spark user: that token belongs to %s, not %s" % (found, name))
        return 1
    name = name or found
    if not name or not exists(name):
        say("spark user: no user here matches that token")
        return 1
    try:
        dk = unlock(name, token)
    except vault.SealError:
        say("spark user: the token does not open %s's key" % name)
        return 1
    write_login(name, token, dk)
    say("ok     account      this machine is %s" % name)
    return 0


def cmd_logout():
    if not account()[0]:
        say("spark user: no login here")
        return 0
    logout()
    say("ok     account      logged out (the sealed data stays)")
    return 0


def cmd_token(args):
    if args != ["--new"]:
        say(USAGE.rstrip())
        return 2
    name, token = account()
    if not name:
        say("spark user: no login here -- spark user login NAME first")
        return 2
    if not exists(name):
        say("spark user: %s's sealed store is not on this machine -- rotate on the box" % name)
        return 2
    try:
        new = rotate(name, token)
    except vault.SealError:
        say("spark user: the stored token no longer opens %s's key -- spark user login again" % name)
        return 1
    write_login(name, new, unlock(name, new))
    say("ok     token        rotated -- shown once, never stored:")
    say("  %s" % new)
    say("  other machines and browsers must log in again")
    return 0


def main(args):
    sub = args[0] if args else ""
    rest = args[1:]
    if sub in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    if sub in ("", "status"):
        return _show()
    if sub == "list":
        return _show()
    if sub == "add":
        return cmd_add(rest)
    if sub == "remove":
        return cmd_remove(rest)
    if sub == "login":
        return cmd_login(rest)
    if sub == "logout":
        return cmd_logout()
    if sub == "token":
        return cmd_token(rest)
    if sub == "claim":
        return cmd_claim()
    say(USAGE.rstrip())
    return 2
