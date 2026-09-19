#!/usr/bin/env python3
"""The cipher against RFC 8439's own vectors, then round-trips and refusals.

Every piece of lib/spark/chacha.py is pinned to the number the RFC
prints for it: the block function (2.3.2), the stream (2.4.2), Poly1305
(2.5.2), the one-time key (2.6.2) and the AEAD (2.8.2). Then property
tests: seal/unseal round-trips, a flipped bit, a wrong key, a swapped
AAD all refuse, and a throughput floor so a slow regression goes loud.
Then the stores built on the vault, in a throwaway HOME: a writer never
writes over a file it cannot open, a user name is validated before the
store is touched, and the plain fails index carries no secret.
"""
import os
import shutil
import struct
import sys
import tempfile
import time

# a throwaway HOME before spark is imported: its paths are read at import
HOME = tempfile.mkdtemp(prefix="spark-vault-test-")
for _k in list(os.environ):
    if _k.startswith(("SPARK_", "XDG_", "SITE_")):
        del os.environ[_k]
os.environ.update({"HOME": HOME, "XDG_CONFIG_HOME": HOME + "/.config", "XDG_STATE_HOME": HOME + "/.local/state",
                   "XDG_DATA_HOME": HOME + "/.local/share", "SPARK_NO_REFRESH": "1", "SPARK_YES": "1"})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from spark import chacha, vault  # noqa: E402

FAILED = 0


def check(name, got, want):
    global FAILED
    if got != want:
        FAILED += 1
        print("FAIL %s\n  got  %r\n  want %r" % (name, got, want))
    else:
        print("ok   %s" % name)


def refuse(name, fn, exc=chacha.SealError):
    """fn() raises exactly `exc` -- any other exception (a ValueError out
    of a tampered field) is a failure with a name, not a crash."""
    global FAILED
    try:
        fn()
    except exc:
        print("ok   %s" % name)
    except Exception as e:
        FAILED += 1
        print("FAIL %s -- %s instead of %s: %s" % (name, type(e).__name__, exc.__name__, e))
    else:
        FAILED += 1
        print("FAIL %s -- went through instead of refusing" % name)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def corrupt(path):
    """Flip the first character of the first record: still base64, so
    the refusal is the tag's, not the parser's. Returns the new bytes."""
    head, body = read_bytes(path).split(b"\n", 1)
    body = (b"B" if body[:1] == b"A" else b"A") + body[1:]
    with open(path, "wb") as f:
        f.write(head + b"\n" + body)
    return head + b"\n" + body


SUNSCREEN = (b"Ladies and Gentlemen of the class of '99: If I could offer "
             b"you only one tip for the future, sunscreen would be it.")


def test_block_2_3_2():
    key = struct.unpack("<8I", bytes(range(32)))
    nonce = struct.unpack("<3I", bytes.fromhex("000000090000004a00000000"))
    got = chacha._block(key, 1, nonce)
    want = bytes.fromhex(
        "10f1e7e4d13b5915500fdd1fa32071c4c7d1f4c733c068030422aa9ac3d46c4e"
        "d2826446079faa0914c2d705d98b02a2b5129cd1de164eb9cbd083e8a2503c4e")
    check("2.3.2 block function", got, want)


def test_stream_2_4_2():
    key = bytes(range(32))
    nonce = bytes.fromhex("000000000000004a00000000")
    got = chacha._chacha20(key, 1, nonce, SUNSCREEN)
    want = bytes.fromhex(
        "6e2e359a2568f98041ba0728dd0d6981e97e7aec1d4360c20a27afccfd9fae0b"
        "f91b65c5524733ab8f593dabcd62b3571639d624e65152ab8f530c359f0861d8"
        "07ca0dbf500d6a6156a38e088a22b65e52bc514d16ccf806818ce91ab7793736"
        "5af90bbf74a35be6b40b8eedf2785e42874d")
    check("2.4.2 chacha20 stream", got, want)


def test_poly1305_2_5_2():
    key = bytes.fromhex("85d6be7857556d337f4452fe42d506a8"
                        "0103808afb0db2fd4abff6af4149f51b")
    got = chacha._poly1305(key, b"Cryptographic Forum Research Group")
    want = bytes.fromhex("a8061dc1305136c6c22b8baf0c0127a9")
    check("2.5.2 poly1305 tag", got, want)


def test_one_time_key_2_6_2():
    key = bytes(range(0x80, 0xA0))
    nonce = bytes.fromhex("000000000001020304050607")
    got = chacha._one_time_key(key, nonce)
    want = bytes.fromhex("8ad5a08b905f81cc815040274ab29471"
                         "a833b637e3fd0da508dbb8e2fdd1a646")
    check("2.6.2 one-time key", got, want)


def test_aead_2_8_2():
    key = bytes(range(0x80, 0xA0))
    nonce = bytes.fromhex("070000004041424344454647")
    aad = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
    sealed = chacha.seal(key, nonce, SUNSCREEN, aad)
    want_ct = bytes.fromhex(
        "d31a8d34648e60db7b86afbc53ef7ec2a4aded51296e08fea9e2b5a736ee62d6"
        "3dbea45e8ca9671282fafb69da92728b1a71de0a9e060b2905d6a5b67ecd3b36"
        "92ddbd7f2d778b8c9803aee328091b58fab324e4fad675945585808b4831d7bc"
        "3ff4def08e4b7a9de576d26586cec64b6116")
    want_tag = bytes.fromhex("1ae10b594f09e26a7e902ecbd0600691")
    check("2.8.2 aead ciphertext", sealed[:-16], want_ct)
    check("2.8.2 aead tag", sealed[-16:], want_tag)
    check("2.8.2 aead unseal", chacha.unseal(key, nonce, sealed, aad), SUNSCREEN)


def test_round_trips():
    key = os.urandom(32)
    for size in (0, 1, 15, 16, 17, 63, 64, 65, 1000, 20000):
        nonce = os.urandom(12)
        aad = b"spark-sealed-v1 thread 2000-01-01-000000"
        pt = os.urandom(size)
        got = chacha.unseal(key, nonce, chacha.seal(key, nonce, pt, aad), aad)
        check("round-trip %d bytes" % size, got, pt)


def test_refusals():
    key, nonce = os.urandom(32), os.urandom(12)
    aad = b"spark-sealed-v1 thread a"
    sealed = chacha.seal(key, nonce, b"the plain truth", aad)
    flipped = bytes([sealed[0] ^ 1]) + sealed[1:]
    refuse("flipped bit refused", lambda: chacha.unseal(key, nonce, flipped, aad))
    refuse("wrong key refused",
           lambda: chacha.unseal(os.urandom(32), nonce, sealed, aad))
    refuse("wrong aad refused",
           lambda: chacha.unseal(key, nonce, sealed, b"spark-sealed-v1 memory a"))
    refuse("short record refused", lambda: chacha.unseal(key, nonce, b"x", aad))
    refuse("bad key size refused", lambda: chacha.seal(b"short", nonce, b"", aad))


def test_throughput_floor():
    # A chat message is < 4 kB; sealing one must stay imperceptible.
    # 100 kB/s is a 10x safety margin below the slowest box we support.
    key, nonce = os.urandom(32), os.urandom(12)
    blob = os.urandom(64 * 1024)
    t0 = time.time()
    chacha.seal(key, nonce, blob, b"h")
    per_sec = len(blob) / max(time.time() - t0, 1e-9)
    check("throughput floor (>= 100 kB/s)", per_sec >= 100 * 1024, True)


def test_vault():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        # the key file: wrap, unwrap, wrong token and wrong name refused
        dk = vault.new_key()
        keyfile = os.path.join(d, "key")
        vault.write_private(keyfile, vault.wrap_key(dk, "tok-1", "alice").encode())
        check("wrap/unwrap round-trip", vault.unwrap_key(keyfile, "tok-1", "alice"), dk)
        refuse("wrong token refused", lambda: vault.unwrap_key(keyfile, "tok-2", "alice"))
        refuse("wrong user refused", lambda: vault.unwrap_key(keyfile, "tok-1", "bob"))
        check("mode 0600 on write_private", os.stat(keyfile).st_mode & 0o777, 0o600)

        # a sealed thread: append, read, tail, and the AAD binding
        t = os.path.join(d, "t.sealed")
        msgs = [b'{"role":"user","text":"m%d"}' % i for i in range(9)]
        for m in msgs:
            vault.append_sealed(t, dk, "thread", "2000-01-01-000000", m)
        check("append/read_sealed", vault.read_sealed(t, dk), msgs)
        tail = vault.read_sealed_tail(t, dk, len(msgs[0]) * 3)
        check("tail is the newest", tail, msgs[-3:])
        check("tail of a big cap", vault.read_sealed_tail(t, dk, 10 ** 6), msgs)
        check("is_sealed", vault.is_sealed(t), True)
        check("header read back", vault.read_header(t), ("thread", "2000-01-01-000000"))
        renamed = os.path.join(d, "r.sealed")
        with open(t, encoding="utf-8") as f:
            body = f.read().split("\n", 1)[1]
        with open(renamed, "w", encoding="utf-8") as f:
            f.write(vault.header("thread", "2001-01-01-000000") + "\n" + body)
        refuse("renamed thread refused", lambda: vault.read_sealed(renamed, dk))
        # a file renamed ON DISK keeps its own header: trusted, it reads
        # as another thread and the next append fails its AAD in silence.
        # The caller's expectation refuses it by name instead.
        moved = os.path.join(d, "9999-01-01-000000.sealed")
        with open(t, encoding="utf-8") as f:
            whole = f.read()
        with open(moved, "w", encoding="utf-8") as f:
            f.write(whole)
        refuse("a renamed sealed file is refused by the caller's expectation",
               lambda: vault.read_sealed(moved, dk, "thread", "9999-01-01-000000"))
        check("the matching expectation still reads",
              vault.read_sealed(t, dk, "thread", "2000-01-01-000000"), msgs)

        # a whole-blob file (memory, chat-history)
        m = os.path.join(d, "memory")
        vault.write_sealed(m, dk, "memory", "alice", b"a fact\nanother\n")
        check("whole-blob round-trip", vault.read_sealed(m, dk), [b"a fact\nanother\n"])
        check("plaintext is not sealed", vault.is_sealed(keyfile), False)


def test_audit_kind():
    # the audit trail's kind seals and opens, and is held apart from the
    # other kinds by the header
    with tempfile.TemporaryDirectory() as d:
        dk = vault.new_key()
        p = os.path.join(d, "audit")
        recs = [b'{"action":"do/run","digest":"0123456789ab","rc":0}', b'{"action":"run","rc":1,"verb":"model"}']
        for r in recs:
            vault.append_sealed(p, dk, "audit", "owner", r)
        check("audit kind seals and opens", vault.read_sealed(p, dk, "audit", "owner"), recs)
        check("audit header", vault.read_header(p), ("audit", "owner"))
        refuse("an audit file read as a ledger is refused", lambda: vault.read_sealed(p, dk, "ledger", "owner"))
        refuse("an append onto it as a thread is refused",
               lambda: vault.append_sealed(p, dk, "thread", "owner", b"x"))


def test_key_file_iterations():
    # the iteration count is the key file's word: a tampered one is a
    # refusal, never a traceback (abc) or a CPU pinned for an hour
    with tempfile.TemporaryDirectory() as d:
        dk = vault.new_key()
        parts = vault.wrap_key(dk, "tok-1", "alice").split()
        p = os.path.join(d, "key")
        for bad in ("abc", "0", "-5", "99999999999", "1e6", ""):
            line = parts[:2] + ([bad] if bad else []) + parts[3:]
            with open(p, "w", encoding="utf-8") as f:
                f.write(" ".join(line) + "\n")
            refuse("iteration count %r refused" % bad, lambda: vault.unwrap_key(p, "tok-1", "alice"))
        line = parts[:2] + [str(vault.ITERS_MAX)] + parts[3:]   # inside the bound: tried, fails its tag
        with open(p, "w", encoding="utf-8") as f:
            f.write(" ".join(line) + "\n")
        refuse("a count inside the bound is tried and fails its tag", lambda: vault.unwrap_key(p, "tok-1", "alice"))


def test_append_expects_the_header():
    # an append onto a file that is there holds it to the caller's header
    # first: an empty or foreign file takes no record nobody will open
    with tempfile.TemporaryDirectory() as d:
        dk = vault.new_key()
        empty = os.path.join(d, "empty.sealed")
        open(empty, "w").close()
        refuse("append onto an empty file refused", lambda: vault.append_sealed(empty, dk, "thread", "a", b"m"))
        check("the empty file stays empty", os.path.getsize(empty), 0)
        plain = os.path.join(d, "plain")
        with open(plain, "w", encoding="utf-8") as f:
            f.write("not sealed\n")
        refuse("append onto a plaintext file refused", lambda: vault.append_sealed(plain, dk, "thread", "a", b"m"))
        check("the plaintext file is as it was", read_bytes(plain), b"not sealed\n")
        t = os.path.join(d, "t.sealed")
        vault.append_sealed(t, dk, "thread", "2000-01-01-000000", b"m1")
        before = read_bytes(t)
        refuse("append as another thread refused",
               lambda: vault.append_sealed(t, dk, "thread", "2001-01-01-000000", b"m2"))
        refuse("append as another kind refused",
               lambda: vault.append_sealed(t, dk, "ledger", "2000-01-01-000000", b"m2"))
        check("the thread is byte-for-byte as it was", read_bytes(t), before)
        vault.append_sealed(t, dk, "thread", "2000-01-01-000000", b"m2")
        check("the matching header still appends", vault.read_sealed(t, dk), [b"m1", b"m2"])


def test_stores_never_write_over():
    # the ledger and the memory, in the throwaway HOME: a file that does
    # not open (a flipped byte, a stale account-key) refuses every writer
    # and is left byte-for-byte as it was; a reader sees it as empty
    import base64
    from spark import ACCOUNT_KEY_FILE, ledger, memory, users
    token = users.add("alice")
    users.write_login("alice", token, users.unlock("alice", token))
    check("keep writes the ledger", ledger.keep(ledger.KIND_EDIT, "t.md", "the first note"), "the first note")
    lpath = ledger.path()
    good = read_bytes(lpath)
    bad = corrupt(lpath)

    def keep():
        ledger.keep(ledger.KIND_EDIT, "t.md", "another note")
    refuse("a corrupted ledger refuses keep", keep, ledger.Refused)
    refuse("a corrupted ledger refuses clear", ledger.clear, ledger.Refused)
    refuse("a corrupted ledger refuses drill_grade",
           lambda: ledger.drill_grade("t.md", "q", "a", True), ledger.Refused)
    check("the corrupted ledger is byte-for-byte as it was", read_bytes(lpath), bad)
    check("a corrupted ledger reads as empty", ledger.entries("t.md"), [])
    try:
        keep()
    except ledger.Refused as e:
        check("the refusal names the remedy", "does not open -- spark user login again" in e.hint, True)
    with open(lpath, "wb") as f:
        f.write(good)
    with open(ACCOUNT_KEY_FILE, "wb") as f:
        f.write(base64.b64encode(os.urandom(32)) + b"\n")
    refuse("a stale account-key refuses keep", keep, ledger.Refused)
    check("the ledger under a stale key is byte-for-byte as it was", read_bytes(lpath), good)
    users.write_login("alice", token, users.unlock("alice", token))
    check("the right key writes again", ledger.keep(ledger.KIND_EDIT, "t.md", "another note"), "another note")
    check("both notes are there", [e["note"] for e in ledger.entries("t.md")], ["the first note", "another note"])

    check("remember writes the memory", memory.remember("the sky is blue"), "the sky is blue")
    mpath = memory._store()[0]
    bad = corrupt(mpath)
    refuse("a corrupted memory refuses remember", lambda: memory.remember("another fact"), memory.Refused)
    refuse("a corrupted memory refuses forget_n", lambda: memory.forget_n(1), memory.Refused)
    check("spark forget on a corrupted memory says so", memory.cmd_forget(["sky"]), 1)
    check("the corrupted memory is byte-for-byte as it was", read_bytes(mpath), bad)
    check("a corrupted memory reads as empty", memory._all_facts(), [])


def test_audit_store():
    # the trail in the throwaway HOME (alice logged in by the test before):
    # a record lands and reads back newest last, the reader's lines, a
    # trail that does not open is one signed line and exit 2, a foreign
    # file at its path takes no record and stays as it was, no login
    # keeps nothing and says so
    import contextlib
    import io
    from spark import ACCOUNT_FILE, audit, users
    apath = os.path.join(users.user_dir("alice"), "audit")
    check("a record is kept", audit.record("user add", name="bob"), "")
    check("a record from an address is kept", audit.record("do/run", "192.0.2.10", digest="0123456789ab", rc=0), "")
    recs = audit.records()
    check("two records, newest last", [(r["action"], r["ip"]) for r in recs], [("user add", "cli"), ("do/run", "192.0.2.10")])
    check("a record's keys", set(recs[1]), {"ts", "ip", "action", "digest", "rc"})
    check("the newest N", [r["action"] for r in audit.records(1)], ["do/run"])
    check("the trail is 0600", os.stat(apath).st_mode & 0o777, 0o600)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = audit.cmd_audit(["--porcelain"])
    lines = out.getvalue().splitlines()
    check("spark forge audit --porcelain: exit 0, a tab line a record",
          (rc, len(lines), lines[-1].split("\t")[1:]), (0, 2, ["192.0.2.10", "do/run", "digest=0123456789ab rc=0"]))
    good = read_bytes(apath)
    bad = corrupt(apath)
    refuse("a corrupted trail refuses to read", audit.records, audit.Refused)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = audit.cmd_audit([])
    check("spark forge audit on a trail that does not open: one signed line, exit 2",
          (rc, out.getvalue().strip()), (2, "spark forge -- " + audit.NO_OPEN))
    check("the corrupted trail is byte-for-byte as it was", read_bytes(apath), bad)
    with open(apath, "wb") as f:
        f.write(b"not sealed\n")
    check("a foreign file at the trail's path takes no record", audit.record("user add", name="c"), audit.NO_OPEN)
    check("and is as it was", read_bytes(apath), b"not sealed\n")
    with open(apath, "wb") as f:
        f.write(good)
    check("the trail reads again", len(audit.records()), 2)
    os.rename(ACCOUNT_FILE, ACCOUNT_FILE + ".aside")
    try:
        check("no login: the record is not kept, and says so", audit.record("user add", name="d"), audit.NO_STORE)
        refuse("no login: the reader refuses", audit.records, audit.Refused)
    finally:
        os.rename(ACCOUNT_FILE + ".aside", ACCOUNT_FILE)
    check("the trail took nothing meanwhile", len(audit.records()), 2)


def test_chat_history_never_written_over():
    # the chat history (a whole-blob sealed file): a save onto one that
    # does not open is skipped with one line on stderr, the file kept
    import contextlib
    import io
    from spark import forge, users

    class _RL:
        def __init__(self, lines):
            self.lines = lines

        def get_current_history_length(self):
            return len(self.lines)

        def get_history_item(self, i):
            return self.lines[i - 1]
    dk = users.account_key()
    cpath = os.path.join(users.user_dir("alice"), "chat-history")
    forge._write_chat_history(_RL(["ls", "pwd"]))
    check("the chat history is sealed", vault.read_sealed(cpath, dk, "chathist", "alice"), [b"ls\npwd\n"])
    bad = corrupt(cpath)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        forge._write_chat_history(_RL(["ls", "pwd", "cd"]))
    check("a chat history that does not open is kept as it is", read_bytes(cpath), bad)
    check("and one line on stderr says so", err.getvalue().strip(),
          "spark chat: the chat history does not open -- kept as it is; spark user login again")


def test_remove_validates_the_name():
    # `spark user remove ../x`: refused before the store is touched, and
    # remove() itself never hands a path to rmtree
    from spark import STATE_DIR, users
    victim = os.path.join(STATE_DIR, "x")
    os.makedirs(victim, exist_ok=True)
    open(os.path.join(victim, "key"), "w").close()      # exists("../x") would say yes
    check("spark user remove ../x is refused, exit 2", users.cmd_remove(["../x"]), 2)
    check("the directory beside the store is untouched", os.path.isfile(os.path.join(victim, "key")), True)
    refuse("remove() refuses a path", lambda: users.remove("../x"), ValueError)
    refuse("remove() refuses an empty name", lambda: users.remove(""), ValueError)
    check("still untouched", os.path.isdir(victim), True)
    check("a valid name that is no user is exit 2", users.cmd_remove(["nobody"]), 2)


def test_fails_index_redacts():
    # the plain index the prompt hook reads: NAME=value where NAME smells
    # of a secret becomes NAME=...; PATH=/usr/bin stays
    from spark import ledger
    entries = [{"kind": "fail", "name": "env", "note": "env TOKEN=abc curl -s host", "shape": "a" * 16,
                "head": "env", "rc": "1"},
               {"kind": "fail", "name": "PATH=/usr/bin", "note": "PATH=/usr/bin make", "shape": "b" * 16,
                "head": "make", "rc": "2"}]
    ledger.write_fails_index(entries)
    with open(ledger.FAILS_INDEX, encoding="utf-8") as f:
        text = f.read()
    check("the fails index redacts TOKEN=abc", "env TOKEN=... curl -s host" in text and "abc" not in text, True)
    check("the fails index keeps PATH=/usr/bin", "PATH=/usr/bin make" in text, True)

    def red(s):
        return ledger.SECRET_RE.sub(r"\1=...", s)
    check("api key, password, --auth and a quoted value", red("export API_KEY=x PASSWORD='p q' --auth=t path=y"),
          "export API_KEY=... PASSWORD=... --auth=... path=y")
    check("a plain word survives", red("make target=all"), "make target=all")


def main():
    test_block_2_3_2()
    test_stream_2_4_2()
    test_poly1305_2_5_2()
    test_one_time_key_2_6_2()
    test_aead_2_8_2()
    test_round_trips()
    test_refusals()
    test_vault()
    test_audit_kind()
    test_key_file_iterations()
    test_append_expects_the_header()
    test_stores_never_write_over()
    test_audit_store()
    test_chat_history_never_written_over()
    test_remove_validates_the_name()
    test_fails_index_redacts()
    test_throughput_floor()
    if FAILED:
        print("%d failed" % FAILED)
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(HOME, ignore_errors=True)
