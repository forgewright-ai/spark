# spark.tls -- the page over HTTPS: the certificate files the listener
# serves (a pair you were given, or a pair spark minted), the trust a
# client types (a CA file, or one server's fingerprint), and the three
# readers over a certificate that the stdlib lacks: its sha256, its
# expiry and its names. Nothing here opens a socket for itself; the
# forge wraps its listener with a context from here, and the wire hangs
# the trust handler on its one opener.

import calendar
import hashlib
import http.client
import os
import shutil
import ssl
import subprocess
import time
import urllib.parse
import urllib.request

from . import CONFIG_DIR, STATE_DIR, debug, state_dir
from . import vault

OWN_DIR = os.path.join(STATE_DIR, "https")          # the pair spark minted (own mode) and its root
TRUST_DIR = os.path.join(CONFIG_DIR, "trust")        # what `spark client URL --ca|--pin` saved, one file a host
RELOAD_SECONDS = 60             # how often the listener looks at its files' times
ROOT_DAYS = 3650                # the own root's life
LEAF_DAYS = 398                 # the own leaf's life: the longest browsers accept
RENEW_DAYS = 30                 # the leaf is minted again this many days before its end
HSTS_SECONDS = 604800           # one week: enough to stick, short enough that https off strands no name
TRUST_PORT_OFFSET = 1           # own mode's plain listener for the root: the page's port plus one

_OID_SAN = b"\x55\x1d\x11"      # 2.5.29.17 subjectAltName
_OID_BASIC = b"\x55\x1d\x13"    # 2.5.29.19 basicConstraints


class TlsError(Exception):
    """One line for a person: what is wrong with a file, a pair or a
    fingerprint."""


# ------------------------------------------------------------------ files
def read_pem(path):
    """The first certificate in a PEM file as DER bytes. TlsError when
    the file does not open or holds no certificate."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        raise TlsError("cannot read %s: %s" % (path, e.strerror or e))
    return pem_to_der(text, path)


def pem_to_der(text, name="the certificate"):
    begin, end = "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"
    i = text.find(begin)
    j = text.find(end, i)
    if i < 0 or j < 0:
        raise TlsError("%s holds no certificate" % name)
    try:
        return ssl.PEM_cert_to_DER_cert(text[i:j + len(end)])
    except ValueError as e:
        raise TlsError("%s: %s" % (name, e))


def fingerprint(der):
    """sha256 of a DER certificate, the shape a person compares:
    `sha256:AB:CD:...`."""
    h = hashlib.sha256(der).hexdigest().upper()
    return "sha256:" + ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def normal_pin(text):
    """A fingerprint as typed (with or without `sha256:`, colons, case)
    as 64 lowercase hex characters, or '' when it is no fingerprint."""
    t = (text or "").strip().lower()
    if t.startswith("sha256"):
        t = t[6:].lstrip(":")
    t = t.replace(":", "").replace(" ", "")
    return t if len(t) == 64 and all(c in "0123456789abcdef" for c in t) else ""


def same_pin(der, pin):
    return hashlib.sha256(der).hexdigest() == normal_pin(pin)


# ------------------------------------------------------------- the reader
def _tlv(b, i):
    """The tag, the body's start and end, and the next element's start,
    of the DER element at i. A short or long length both read."""
    if i + 2 > len(b):
        raise TlsError("the certificate is cut short")
    tag, n = b[i], b[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7f
        if k == 0 or k > 4 or i + k > len(b):
            raise TlsError("the certificate is not DER")
        n = int.from_bytes(b[i:i + k], "big")
        i += k
    if i + n > len(b):
        raise TlsError("the certificate is cut short")
    return tag, i, i + n, i + n


def _children(b, i, end):
    while i < end:
        tag, s, e, i = _tlv(b, i)
        yield tag, s, e


def _time(b, tag, s, e):
    t = b[s:e].decode("ascii", "replace")
    if tag == 0x17:                       # UTCTime YYMMDDHHMMSSZ
        try:
            yy = int(t[:2])
        except ValueError:
            raise TlsError("the certificate's validity does not read")
        t = ("20%02d" if yy < 50 else "19%02d") % yy + t[2:]
    elif tag != 0x18:                     # GeneralizedTime YYYYMMDDHHMMSS[.f]Z
        raise TlsError("the certificate's validity does not read")
    t = t.split(".")[0].rstrip("Z")
    if len(t) == 12:
        t += "00"
    try:
        return calendar.timegm(time.strptime(t, "%Y%m%d%H%M%S"))
    except ValueError:
        raise TlsError("the certificate's validity does not read")


def read_der(der):
    """What spark needs of a certificate: {not_after (epoch), not_before,
    dns [names], ips [addresses], ca (bool)}. A hand reader of the
    fixed order of RFC 5280, because the stdlib has no public one."""
    out = {"not_after": 0, "not_before": 0, "dns": [], "ips": [], "ca": False}
    tag, s, e, _ = _tlv(der, 0)
    if tag != 0x30:
        raise TlsError("the certificate is not DER")
    tbs = next(_children(der, s, e), None)
    if not tbs or tbs[0] != 0x30:
        raise TlsError("the certificate is not DER")
    parts = list(_children(der, tbs[1], tbs[2]))
    if parts and parts[0][0] == 0xa0:     # [0] version
        parts = parts[1:]
    if len(parts) < 6:
        raise TlsError("the certificate is cut short")
    validity = parts[3]
    times = list(_children(der, validity[1], validity[2]))
    if len(times) != 2:
        raise TlsError("the certificate's validity does not read")
    out["not_before"] = _time(der, *times[0])
    out["not_after"] = _time(der, *times[1])
    for tag, s, e in parts[6:]:
        if tag != 0xa3:                   # [3] extensions
            continue
        seq = next(_children(der, s, e), None)
        if not seq:
            continue
        for _t, es, ee in _children(der, seq[1], seq[2]):
            fields = list(_children(der, es, ee))
            if not fields or fields[0][0] != 0x06:
                continue
            oid = der[fields[0][1]:fields[0][2]]
            value = fields[-1]
            if value[0] != 0x04:
                continue
            if oid == _OID_SAN:
                inner = next(_children(der, value[1], value[2]), None)
                if inner:
                    for gtag, gs, ge in _children(der, inner[1], inner[2]):
                        if gtag == 0x82:
                            out["dns"].append(der[gs:ge].decode("ascii", "replace").lower())
                        elif gtag == 0x87 and ge - gs in (4, 16):
                            raw = der[gs:ge]
                            out["ips"].append(".".join(str(c) for c in raw) if len(raw) == 4
                                              else ":".join("%x" % int.from_bytes(raw[i:i + 2], "big")
                                                            for i in range(0, 16, 2)))
            elif oid == _OID_BASIC:
                inner = next(_children(der, value[1], value[2]), None)
                if inner:
                    first = next(_children(der, inner[1], inner[2]), None)
                    out["ca"] = bool(first and first[0] == 0x01 and der[first[1]:first[2]] != b"\x00")
    return out


def read_cert(path):
    """read_der of the first certificate in a PEM file, with `sha256` and
    `path` added."""
    der = read_pem(path)
    d = read_der(der)
    d["sha256"] = fingerprint(der)
    d["path"] = path
    return d


def days_left(info, now=None):
    return (info["not_after"] - (now or time.time())) / 86400.0


# -------------------------------------------------------- the listener's
def server_context(cert, key):
    """A server context for the pair: TLS 1.2 or newer, Python's own
    cipher choice. TlsError names what is wrong with the files."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        ctx.load_cert_chain(cert, key)
    except (ssl.SSLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", None) or getattr(e, "strerror", None) or str(e)
        raise TlsError("the certificate pair does not load: %s" % reason)
    return ctx


def check_pair(cert, key, name=""):
    """What `spark serve https CERT KEY` asks before it writes a key: the
    files read, the key is private, the pair loads, the certificate has
    not ended, and it names `name` (or says which names it has). Returns
    read_cert's dict. TlsError otherwise, one line."""
    for p in (cert, key):
        if not os.path.isfile(p):
            raise TlsError("no file at %s" % p)
        if not os.access(p, os.R_OK):
            raise TlsError("%s is not readable by this user" % p)
    mode = os.stat(key).st_mode & 0o077
    if mode:
        raise TlsError("the key %s is readable by others -- chmod 600 %s" % (key, key))
    info = read_cert(cert)
    server_context(cert, key)
    if days_left(info) <= 0:
        raise TlsError("the certificate ended on %s" % time.strftime("%Y-%m-%d", time.gmtime(info["not_after"])))
    if name and name.lower() not in info["dns"] and name not in info["ips"]:
        raise TlsError("the certificate does not name %s; it names %s" % (name, ", ".join(info["dns"] + info["ips"]) or "nothing"))
    return info


class Served:
    """The listener's certificate pair, reloaded when the files change:
    a renewal needs no restart. `context()` is asked on the accept loop
    at every connection and looks at the files' times at most once in
    RELOAD_SECONDS; a pair that does not load keeps the old context and
    says so in `error`, which the https row reads."""

    def __init__(self, cert, key):
        self.cert, self.key = cert, key
        self.ctx = server_context(cert, key)
        self.info = read_cert(cert)
        self.stamp = self._stamp()
        self.t = time.monotonic()
        self.error = ""

    def _stamp(self):
        try:
            return tuple(os.stat(p).st_mtime_ns for p in (self.cert, self.key))
        except OSError:
            return None

    def context(self):
        now = time.monotonic()
        if now - self.t < RELOAD_SECONDS:
            return self.ctx
        self.t = now
        stamp = self._stamp()
        if stamp is not None and stamp != self.stamp:
            try:
                ctx = server_context(self.cert, self.key)
                self.info = read_cert(self.cert)
                self.ctx, self.stamp, self.error = ctx, stamp, ""
                debug("tls: the certificate pair reloaded")
            except TlsError as e:
                self.error = str(e)
                debug("tls: " + self.error)
        return self.ctx

    def names(self):
        return list(self.info["dns"])


# -------------------------------------------------------------- the trust
def trust_files():
    """The files under TRUST_DIR, newest last: one a host, named by it."""
    try:
        return sorted(os.path.join(TRUST_DIR, f) for f in os.listdir(TRUST_DIR) if f.endswith(".pem"))
    except OSError:
        return []


def trust_path(host):
    return os.path.join(TRUST_DIR, host.lower().replace("/", "_") + ".pem")


def save_trust(host, pem_text):
    """Write a host's trust file (0600 under a 0700 directory) and return
    its path. The text is a certificate: a root to verify with, or a
    leaf to pin."""
    pem_to_der(pem_text, host)
    os.makedirs(TRUST_DIR, mode=0o700, exist_ok=True)
    os.chmod(TRUST_DIR, 0o700)
    path = trust_path(host)
    fd = vault.open_private(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(pem_text if pem_text.endswith("\n") else pem_text + "\n")
    return path


def forget_trust(host):
    try:
        os.remove(trust_path(host))
        return True
    except OSError:
        return False


def local_pins(cfg):
    """The machine that serves trusts its own pair: the configured
    certificate's sha256 is the pin for every name the page answers to,
    so the start's probe, the check's rows and `spark serve` reach the
    page whatever the system store thinks of the issuer. Empty on a
    machine that serves nothing."""
    cert = cfg.forge_cert
    if not cert:
        return {}
    try:
        der = read_pem(cert)
        info = read_der(der)
    except TlsError:
        return {}
    from . import lan_ip, own_hostnames
    hosts = {cfg.forge_host, "127.0.0.1", "localhost", cfg.forge_name, lan_ip()} | own_hostnames()
    hosts |= set(info["dns"]) | set(info["ips"])
    pin = hashlib.sha256(der).hexdigest()
    return {h.lower(): pin for h in hosts if h}


def trust_state(cfg):
    """(the CA files to verify with, {host: pin}). The CA files:
    SPARK_CA_FILE, the own root when one was minted here, and every
    saved file that is a CA. The pins: the page's own pair for this
    machine's names, then the saved leaves by host (a saved file
    wins)."""
    cas, pins = [], dict(local_pins(cfg))
    if cfg.ca_file:
        cas.append(cfg.ca_file)
    own = own_paths()["root"]
    if os.path.isfile(own):
        cas.append(own)
    for path in trust_files():
        try:
            der = read_pem(path)
            info = read_der(der)
        except TlsError as e:
            debug("tls: %s ignored: %s" % (path, e))
            continue
        if info["ca"]:
            cas.append(path)
        else:
            pins[os.path.basename(path)[:-4]] = hashlib.sha256(der).hexdigest()
    return cas, pins


def client_context(ca_files=()):
    """The system store, and every CA file given on top of it: downloads
    from the public hosts keep working beside a private root."""
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    for path in ca_files:
        try:
            ctx.load_verify_locations(path)
        except (ssl.SSLError, OSError) as e:
            debug("tls: %s not loaded: %s" % (path, e))
    return ctx


def _unverified():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class _PinnedConnection(http.client.HTTPSConnection):
    """An HTTPS connection to one pinned host: the handshake runs without
    the store, then the peer's certificate must be the pinned one, byte
    for byte through its sha256, or the connection is closed before a
    request goes."""

    def __init__(self, pin, *args, **kwargs):
        kwargs["context"] = _unverified()
        super().__init__(*args, **kwargs)
        self._pin = pin

    def connect(self):
        super().connect()
        der = self.sock.getpeercert(True) or b""
        if hashlib.sha256(der).hexdigest() != self._pin:
            self.close()
            raise ssl.SSLCertVerificationError("the server's certificate is not the one pinned here -- spark client URL --pin again after comparing")


class TrustHandler(urllib.request.HTTPSHandler):
    """urllib's HTTPS handler with spark's trust: the system store plus
    SPARK_CA_FILE and the saved roots for every host; a pinned connection
    for a host whose saved file is a leaf. Read once per process, on the
    first https request, so importing the wire costs nothing."""

    def __init__(self):
        # a bare context, never used: https_open passes its own. With none,
        # Python 3.12 and newer build a default one here and load the
        # system's CAs, 20 ms and more at every spawn, since HANDLER is made
        # at import
        super().__init__(context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
        self._ctx, self._pins = None, None

    def _load(self):
        if self._ctx is not None:
            return
        try:
            from . import config
            cas, pins = trust_state(config.load())
        except Exception:                         # noqa: BLE001 -- a config error is the verb's to say, not the wire's
            cas, pins = [], {}
        self._ctx, self._pins = client_context(cas), pins

    def refresh(self):
        self._ctx = None

    def https_open(self, req):
        self._load()
        host = (urllib.parse.urlsplit(req.full_url).hostname or "").lower()
        pin = self._pins.get(host)
        if pin:
            return self.do_open(lambda *a, **k: _PinnedConnection(pin, *a, **k), req)
        return self.do_open(http.client.HTTPSConnection, req, context=self._ctx)


HANDLER = TrustHandler()


def peer_certificate(url, timeout=5.0):
    """The leaf a server presents at url, as (der, info), with no trust
    asked: what `spark client` shows a person before they type a pin.
    None when nothing answers TLS there."""
    parts = urllib.parse.urlsplit(url)
    host, port = parts.hostname, parts.port or 443
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout) as c, \
                _unverified().wrap_socket(c, server_hostname=host) as s:
            der = s.getpeercert(True)
    except (OSError, ValueError):
        return None
    if not der:
        return None
    try:
        return der, read_der(der)
    except TlsError:
        return der, {"not_after": 0, "not_before": 0, "dns": [], "ips": [], "ca": False}


def verify_error(url, timeout=5.0):
    """'' when this machine's trust accepts the server at url (whatever
    it answers), the one-line reason when it does not (an untrusted
    issuer, a wrong name, a pin that does not match, no TLS), and None
    when nothing answers there at all."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url.rstrip("/") + "/api/health"), timeout=timeout):
            return ""
    except urllib.error.HTTPError:
        return ""                                   # it answered over TLS: the trust held
    except ssl.SSLCertVerificationError as e:
        return getattr(e, "verify_message", "") or str(e)
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            return getattr(reason, "verify_message", "") or str(reason)
        if isinstance(reason, ssl.SSLError):
            return str(reason)
        return None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- own mode
def openssl():
    return shutil.which("openssl") or ""


def own_paths():
    return {"root": os.path.join(OWN_DIR, "root.crt"), "root_key": os.path.join(OWN_DIR, "root.key"),
            "cert": os.path.join(OWN_DIR, "leaf.crt"), "key": os.path.join(OWN_DIR, "leaf.key")}


def is_own(cert):
    """Whether the configured certificate is the one spark minted."""
    return bool(cert) and os.path.abspath(cert) == own_paths()["cert"]


def _openssl(args, cwd):
    exe = openssl()
    if not exe:
        raise TlsError("no openssl binary -- install openssl, or give spark a certificate pair of your own")
    try:
        p = subprocess.run([exe] + args, cwd=cwd, capture_output=True, text=True, timeout=60,
                           preexec_fn=lambda: os.umask(0o077))
    except (OSError, subprocess.SubprocessError) as e:
        raise TlsError("openssl did not run: %s" % e)
    if p.returncode != 0:
        line = (p.stderr or p.stdout or "").strip().splitlines()
        raise TlsError("openssl: %s" % (line[-1] if line else "exit %d" % p.returncode))


def mint_root(names, label="spark"):
    """A root of this machine's own: P-256, ROOT_DAYS, a CA, constrained to
    the DNS names given and no other (an address constraint would make
    older stacks refuse the chain, so the address is left to the leaf).
    Writes root.crt and root.key (0600) under OWN_DIR."""
    names = [n for n in dict.fromkeys(n.lower() for n in names if n)]
    if not names:
        raise TlsError("no name to constrain the root to")
    state_dir()
    os.makedirs(OWN_DIR, mode=0o700, exist_ok=True)
    os.chmod(OWN_DIR, 0o700)
    p = own_paths()
    constraint = "nameConstraints=critical," + ",".join("permitted;DNS:" + n for n in names)
    _openssl(["req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
              "-days", str(ROOT_DAYS), "-keyout", p["root_key"], "-out", p["root"],
              "-subj", "/CN=%s root" % label.replace("/", " "),
              "-addext", "basicConstraints=critical,CA:TRUE",
              "-addext", "keyUsage=critical,keyCertSign,cRLSign",
              "-addext", "subjectKeyIdentifier=hash",
              "-addext", constraint], OWN_DIR)
    os.chmod(p["root_key"], 0o600)
    fd = vault.open_private(os.path.join(OWN_DIR, "root.names"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(names) + "\n")
    return read_cert(p["root"])


def own_names():
    """The DNS names the own root was constrained to, recorded at its
    mint: a leaf may carry these and no other."""
    try:
        with open(os.path.join(OWN_DIR, "root.names"), encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []


def mint_leaf(names, ips, label="spark"):
    """The page's certificate under the own root: the DNS names and the
    addresses given, LEAF_DAYS. Writes leaf.crt and leaf.key (0600)."""
    names = [n for n in dict.fromkeys(n.lower() for n in names if n)]
    ips = [i for i in dict.fromkeys(ips) if i]
    if not names and not ips:
        raise TlsError("no name or address for the certificate")
    p = own_paths()
    if not (os.path.isfile(p["root"]) and os.path.isfile(p["root_key"])):
        raise TlsError("no root of this machine's own yet")
    csr, ext = os.path.join(OWN_DIR, "leaf.csr"), os.path.join(OWN_DIR, "leaf.ext")
    try:
        _openssl(["req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
                  "-keyout", p["key"] + ".new", "-out", csr,
                  "-subj", "/CN=%s" % (names[0] if names else ips[0]).replace("/", " ")], OWN_DIR)
        san = ",".join(["DNS:" + n for n in names] + ["IP:" + i for i in ips])
        with os.fdopen(vault.open_private(ext, os.O_WRONLY | os.O_CREAT | os.O_TRUNC), "w", encoding="utf-8") as f:
            # the key identifiers written out: OpenSSL 3 added both to a
            # leaf by itself, OpenSSL 4 does not, and a client in strict
            # mode (python 3.13 and later) refuses a leaf without the
            # authority key identifier
            f.write("subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature\n"
                    "extendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\n"
                    "authorityKeyIdentifier=keyid,issuer\n" % san)
        _openssl(["x509", "-req", "-in", csr, "-CA", p["root"], "-CAkey", p["root_key"], "-CAcreateserial",
                  "-days", str(LEAF_DAYS), "-out", p["cert"] + ".new", "-extfile", ext], OWN_DIR)
        os.chmod(p["key"] + ".new", 0o600)
        # the key first, then the certificate: a reload between the two
        # finds a pair that does not load and keeps the old one
        os.replace(p["key"] + ".new", p["key"])
        os.replace(p["cert"] + ".new", p["cert"])
    finally:
        for f in (csr, ext, p["key"] + ".new", p["cert"] + ".new", os.path.join(OWN_DIR, "root.srl")):
            try:
                os.remove(f)
            except OSError:
                pass
    return read_cert(p["cert"])


def renew_due(now=None):
    """Whether the own leaf ends within RENEW_DAYS (or is missing)."""
    p = own_paths()
    try:
        return days_left(read_cert(p["cert"]), now) < RENEW_DAYS
    except TlsError:
        return True
