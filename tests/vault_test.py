#!/usr/bin/env python3
"""The cipher against RFC 8439's own vectors, then round-trips and refusals.

Every piece of lib/spark/chacha.py is pinned to the number the RFC
prints for it: the block function (2.3.2), the stream (2.4.2), Poly1305
(2.5.2), the one-time key (2.6.2) and the AEAD (2.8.2). Then property
tests: seal/unseal round-trips, a flipped bit, a wrong key, a swapped
AAD all refuse, and a throughput floor so a slow regression goes loud.
"""
import os
import struct
import sys
import time

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


def refuse(name, fn):
    global FAILED
    try:
        fn()
    except chacha.SealError:
        print("ok   %s" % name)
    else:
        FAILED += 1
        print("FAIL %s -- opened instead of refusing" % name)


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

        # a whole-blob file (memory, chat-history)
        m = os.path.join(d, "memory")
        vault.write_sealed(m, dk, "memory", "alice", b"a fact\nanother\n")
        check("whole-blob round-trip", vault.read_sealed(m, dk), [b"a fact\nanother\n"])
        check("plaintext is not sealed", vault.is_sealed(keyfile), False)


def main():
    test_block_2_3_2()
    test_stream_2_4_2()
    test_poly1305_2_5_2()
    test_one_time_key_2_6_2()
    test_aead_2_8_2()
    test_round_trips()
    test_refusals()
    test_vault()
    test_throughput_floor()
    if FAILED:
        print("%d failed" % FAILED)
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
