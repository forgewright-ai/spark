"""vault -- the sealed-file format and the per-user key custody.

One format for every encrypted file spark keeps:

    line 1:   spark-sealed-v1 <kind> <name>          ASCII header
    lines 2+: base64( nonce[12] || ct || tag[16] )   one record per line

The header is the AAD of every record, so a sealed thread cannot be
renamed into another thread or replayed as a memory file. The nonce is
os.urandom(12) per record: append-safe, no counter state. A thread
holds one record per message (appends stay cheap); memory and
chat-history are one whole-blob record, rewritten wholesale.

Key custody: each user owns a random 32-byte data key (DK). The box
stores only sha256(token) as a lookup verifier and the DK wrapped by a
KDF-derived key -- the wrap's own tag proves the token. No token, no
DK, no plaintext: a lost token is lost history, by design.
"""
import base64
import hashlib
import os

from . import chacha
from .chacha import SealError  # noqa: F401  -- the vault's error is the cipher's

MAGIC = "spark-sealed-v1"
KEY_MAGIC = "spark-key-v1"
KINDS = ("thread", "memory", "chathist")
# PBKDF2-HMAC-SHA256, not scrypt: Apple's system python (the 3.9 floor)
# links an OpenSSL without scrypt, and pbkdf2_hmac is guaranteed on both
# OSes. The token is a 256-bit random spark minted -- never a human
# password -- so the KDF is belt-and-braces, not the wall. The iteration
# count lives in the key file so it can rise without a format break.
PBKDF2_ITERS = 200_000
DK_LEN = 32


def header(kind, name):
    assert kind in KINDS, kind
    return "%s %s %s" % (MAGIC, kind, name)


def is_sealed(path):
    """True when the file starts with the sealed magic (no key needed)."""
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC) + 1) == (MAGIC + " ").encode()
    except OSError:
        return False


def new_key():
    return os.urandom(DK_LEN)


def token_hash(token):
    """The lookup verifier: sha256 hex of the token. The token is 256-bit
    random, so a fast hash is sound here; scrypt only gates the wrap."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _kek(token, salt, iters):
    return hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, iters,
                               dklen=DK_LEN)


def wrap_key(dk, token, name):
    """The key-file line: DK sealed under pbkdf2(token). One line, ASCII."""
    salt, nonce = os.urandom(16), os.urandom(chacha.NONCE_LEN)
    kek = _kek(token, salt, PBKDF2_ITERS)
    sealed = chacha.seal(kek, nonce, dk, ("%s %s" % (KEY_MAGIC, name)).encode())
    return "%s pbkdf2 %d %s %s\n" % (
        KEY_MAGIC, PBKDF2_ITERS,
        base64.b64encode(salt).decode(), base64.b64encode(nonce + sealed).decode())


def unwrap_key(path, token, name):
    """The DK back out of the key file, or SealError (wrong token, wrong
    user, tampered or malformed file alike)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            parts = f.readline().split()
        magic, kdf, iters, salt_b64, blob_b64 = parts
        if magic != KEY_MAGIC or kdf != "pbkdf2":
            raise ValueError(magic)
        salt = base64.b64decode(salt_b64, validate=True)
        blob = base64.b64decode(blob_b64, validate=True)
    except (OSError, ValueError):
        raise SealError("unreadable key file: %s" % path)
    kek = _kek(token, salt, int(iters))
    nonce, sealed = blob[:chacha.NONCE_LEN], blob[chacha.NONCE_LEN:]
    dk = chacha.unseal(kek, nonce, sealed, ("%s %s" % (KEY_MAGIC, name)).encode())
    if len(dk) != DK_LEN:
        raise SealError("key file holds no data key")
    return dk


def seal_line(dk, hdr, data):
    """One record line (no newline): data sealed under a fresh nonce."""
    nonce = os.urandom(chacha.NONCE_LEN)
    return base64.b64encode(nonce + chacha.seal(dk, nonce, data, hdr.encode())).decode()


def open_line(dk, hdr, line):
    try:
        blob = base64.b64decode(line.strip(), validate=True)
    except ValueError:
        raise SealError("record is not base64")
    if len(blob) < chacha.NONCE_LEN + chacha.TAG_LEN:
        raise SealError("record shorter than nonce and tag")
    return chacha.unseal(dk, blob[:chacha.NONCE_LEN], blob[chacha.NONCE_LEN:],
                         hdr.encode())


def read_header(path):
    """(kind, name) from a sealed file's first line, or SealError."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            parts = f.readline().rstrip("\n").split(" ", 2)
    except OSError:
        raise SealError("unreadable sealed file: %s" % path)
    if len(parts) != 3 or parts[0] != MAGIC or parts[1] not in KINDS:
        raise SealError("not a sealed file: %s" % path)
    return parts[1], parts[2]


def read_sealed(path, dk):
    """Every record of a sealed file, decrypted, newest last."""
    kind, name = read_header(path)
    hdr = header(kind, name)
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        f.readline()
        for line in f:
            if line.strip():
                out.append(open_line(dk, hdr, line))
    return out


def read_sealed_tail(path, dk, max_chars):
    """The newest records whose decrypted sizes sum to <= max_chars (at
    least one when any exists): the cheap tail for a long thread."""
    kind, name = read_header(path)
    hdr = header(kind, name)
    with open(path, encoding="utf-8", errors="replace") as f:
        f.readline()
        lines = [ln for ln in f if ln.strip()]
    out, total = [], 0
    for line in reversed(lines):
        rec = open_line(dk, hdr, line)
        if out and total + len(rec) > max_chars:
            break
        out.append(rec)
        total += len(rec)
    out.reverse()
    return out


def write_private(path, data):
    """A 0600 file that was never world-readable: private temp beside the
    target, then an atomic replace."""
    tmp = path + ".tmp.%d" % os.getpid()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def write_sealed(path, dk, kind, name, blob):
    """A whole-blob sealed file (memory, chat-history): header + one record."""
    hdr = header(kind, name)
    write_private(path, ("%s\n%s\n" % (hdr, seal_line(dk, hdr, blob))).encode())


def append_sealed(path, dk, kind, name, record):
    """One record onto a sealed file, creating it (0600, header first) on
    first use. O_APPEND keeps concurrent writers whole."""
    hdr = header(kind, name)
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(hdr + "\n")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(seal_line(dk, hdr, record) + "\n")
