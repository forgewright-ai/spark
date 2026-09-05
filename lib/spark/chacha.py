"""chacha -- ChaCha20-Poly1305 AEAD, written from RFC 8439, stdlib only.

The one cipher spark uses, for small text records (a chat message, a
memory file). Pure python is fast enough at that size; the RFC's own
test vectors pin every piece in tests/vault_test.py. seal() returns
ciphertext||tag; unseal() verifies the tag in constant time and raises
SealError on any mismatch -- a wrong key, a flipped bit, a swapped AAD.
"""
import hmac
import struct

KEY_LEN = 32
NONCE_LEN = 12
TAG_LEN = 16

_CONST = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)
_P1305 = (1 << 130) - 5
_CLAMP = 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF


class SealError(Exception):
    """The record does not open: wrong key, wrong AAD, or tampered."""


def _block(key_words, counter, nonce_words):
    """One 64-byte ChaCha20 keystream block (RFC 8439 2.3)."""
    init = _CONST + key_words + (counter,) + nonce_words
    x = list(init)
    for _ in range(10):
        for a, b, c, d in ((0, 4, 8, 12), (1, 5, 9, 13), (2, 6, 10, 14),
                           (3, 7, 11, 15), (0, 5, 10, 15), (1, 6, 11, 12),
                           (2, 7, 8, 13), (3, 4, 9, 14)):
            xa, xb, xc, xd = x[a], x[b], x[c], x[d]
            xa = (xa + xb) & 0xFFFFFFFF
            xd ^= xa
            xd = ((xd << 16) | (xd >> 16)) & 0xFFFFFFFF
            xc = (xc + xd) & 0xFFFFFFFF
            xb ^= xc
            xb = ((xb << 12) | (xb >> 20)) & 0xFFFFFFFF
            xa = (xa + xb) & 0xFFFFFFFF
            xd ^= xa
            xd = ((xd << 8) | (xd >> 24)) & 0xFFFFFFFF
            xc = (xc + xd) & 0xFFFFFFFF
            xb ^= xc
            xb = ((xb << 7) | (xb >> 25)) & 0xFFFFFFFF
            x[a], x[b], x[c], x[d] = xa, xb, xc, xd
    return struct.pack("<16I", *((s + i) & 0xFFFFFFFF for s, i in zip(x, init)))


def _chacha20(key, counter, nonce, data):
    """XOR data with the keystream starting at counter (RFC 8439 2.4)."""
    key_w = struct.unpack("<8I", key)
    nonce_w = struct.unpack("<3I", nonce)
    out = bytearray()
    for i in range((len(data) + 63) // 64):
        ks = _block(key_w, (counter + i) & 0xFFFFFFFF, nonce_w)
        chunk = data[i * 64:i * 64 + 64]
        n = len(chunk)
        out += (int.from_bytes(chunk, "little")
                ^ int.from_bytes(ks[:n], "little")).to_bytes(n, "little")
    return bytes(out)


def _poly1305(key, msg):
    """The 16-byte tag of msg under a 32-byte one-time key (RFC 8439 2.5)."""
    r = int.from_bytes(key[:16], "little") & _CLAMP
    s = int.from_bytes(key[16:32], "little")
    acc = 0
    for i in range(0, len(msg), 16):
        block = msg[i:i + 16]
        acc = ((acc + int.from_bytes(block, "little")
                + (1 << (8 * len(block)))) * r) % _P1305
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _one_time_key(key, nonce):
    """The Poly1305 key: the first half of block zero (RFC 8439 2.6)."""
    return _block(struct.unpack("<8I", key), 0, struct.unpack("<3I", nonce))[:32]


def _pad16(b):
    return b"\x00" * ((-len(b)) % 16)


def _mac_data(aad, ct):
    return aad + _pad16(aad) + ct + _pad16(ct) + struct.pack("<QQ", len(aad), len(ct))


def seal(key, nonce, plaintext, aad):
    """AEAD encrypt (RFC 8439 2.8): returns ciphertext || 16-byte tag."""
    if len(key) != KEY_LEN or len(nonce) != NONCE_LEN:
        raise SealError("key must be 32 bytes and nonce 12")
    ct = _chacha20(key, 1, nonce, plaintext)
    return ct + _poly1305(_one_time_key(key, nonce), _mac_data(aad, ct))


def unseal(key, nonce, sealed, aad):
    """AEAD decrypt: verifies the tag, returns the plaintext or raises."""
    if len(key) != KEY_LEN or len(nonce) != NONCE_LEN:
        raise SealError("key must be 32 bytes and nonce 12")
    if len(sealed) < TAG_LEN:
        raise SealError("sealed record shorter than its tag")
    ct, tag = sealed[:-TAG_LEN], sealed[-TAG_LEN:]
    want = _poly1305(_one_time_key(key, nonce), _mac_data(aad, ct))
    if not hmac.compare_digest(want, tag):
        raise SealError("seal does not verify")
    return _chacha20(key, 1, nonce, ct)
