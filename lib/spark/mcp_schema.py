# The bounded JSON Schema subset used by MCP calls and planning alike.
# Unsupported assertions are refusals, never silently ignored. Patterns
# use a small regular language and a linear matcher, not backtracking
# over provider text. No provider-specific rule lives here.

import decimal
import math
import re
import warnings

PATTERN_MAX = 256
PATTERN_ATOMS = 64
STRING_MAX = 4096
STRING_LIMIT = 65536
ARRAY_MAX = 32
META = {"title", "description", "default", "examples", "$schema", "$id", "$comment",
        "deprecated", "readOnly", "writeOnly", "format", "contentMediaType", "contentEncoding"}
KEYS = {
    "object": {"properties", "required", "additionalProperties", "minProperties", "maxProperties"},
    "string": {"minLength", "maxLength", "pattern", "format"},
    "integer": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"},
    "number": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"},
    "array": {"items", "minItems", "maxItems", "uniqueItems"},
    "boolean": set(),
}
COUNTS = {"minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties"}


def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and (isinstance(v, int) or math.isfinite(v))


def bound_text(v):
    # A refusal must not render an arbitrarily large provider integer,
    # including one beyond Python's decimal conversion limit.
    return "the declared bound" if isinstance(v, int) and v.bit_length() > 256 else str(v)


def ratio(v):
    # JSON numbers have decimal semantics. Integer arithmetic avoids
    # Decimal's working precision rounding or refusing a valid multiple.
    return (v, 1) if isinstance(v, int) else decimal.Decimal(str(v)).as_integer_ratio()


def equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    return a == b


def pattern_atoms(pattern):
    """A bounded regular language. Groups may be optional, never looped;
    each compiled regex is a single character, never a provider pattern."""
    if not isinstance(pattern, str) or len(pattern) > PATTERN_MAX:
        raise ValueError("invalid pattern size")
    slashes = len(pattern[:-1]) - len(pattern[:-1].rstrip("\\"))
    start, end = pattern.startswith("^"), pattern.endswith("$") and slashes % 2 == 0
    source = pattern[int(start):len(pattern) - int(end)]
    count = 0

    def parse(i=0, depth=0):
        nonlocal count
        if depth > 8:
            raise ValueError("unsupported pattern depth")
        atoms = []
        while i < len(source):
            ch, begin = source[i], i
            if ch == ")" and depth:
                return atoms, i + 1
            if ch == "(":
                i += 1
                if source[i:i + 2] == "?:":
                    i += 2
                atom, i = parse(i, depth + 1)
            elif ch == "[":
                i += 1
                while i < len(source) and source[i] != "]":
                    if source[i] == "\\":
                        i += 1
                        if i == len(source) or source[i].isalnum():
                            raise ValueError("unsupported pattern escape")
                    i += 1
                if i == len(source):
                    raise ValueError("invalid pattern class")
                atom = source[begin:i + 1]
                if any(x in atom for x in ("&&", "--", "~~", "||", "[[")):
                    raise ValueError("unsupported pattern class")
                i += 1
            elif ch == "\\":
                i += 1
                if i == len(source) or source[i].isalnum():
                    raise ValueError("unsupported pattern escape")
                atom = re.escape(source[i])
                i += 1
            elif ch == ".":
                atom, i = "[^\\n\\r\\u2028\\u2029]", i + 1
            elif ch in "^$()|*+?{}]":
                raise ValueError("unsupported pattern construct")
            else:
                atom, i = re.escape(ch), i + 1
            lo = hi = 1
            if i < len(source) and source[i] in "*+?":
                lo, hi = {"*": (0, STRING_LIMIT), "+": (1, STRING_LIMIT), "?": (0, 1)}[source[i]]
                i += 1
            elif i < len(source) and source[i] == "{":
                m = re.match(r"\{([0-9]{1,5})(?:,([0-9]{0,5}))?\}", source[i:])
                if m is None:
                    raise ValueError("unsupported pattern repetition")
                lo = int(m[1])
                hi = lo if m[2] is None else int(m[2]) if m[2] else STRING_LIMIT
                if not lo <= hi <= STRING_LIMIT:
                    raise ValueError("unsupported pattern repetition")
                i += len(m[0])
            if isinstance(atom, list):
                if hi > 1:
                    raise ValueError("unsupported repeated pattern group")
            else:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("error", FutureWarning)
                        atom = re.compile(atom)
                except (re.error, FutureWarning) as e:
                    raise ValueError("invalid pattern class") from e
            atoms.append((atom, lo, hi))
            count += 1
            if count > PATTERN_ATOMS:
                raise ValueError("unsupported pattern size")
        if depth:
            raise ValueError("invalid pattern group")
        return atoms, i
    atoms, _ = parse()
    return start, end, atoms


def pattern_matches(pattern, value):
    """O(pattern atoms * value length), including overlapping repeats.
    Reachable prefix lengths form the states; range sums avoid retrying
    the same suffix. Unanchored patterns can start at any character."""
    start, end, atoms = pattern_atoms(pattern)

    def advance(atoms, states):
        for atom, lo, hi in atoms:
            if isinstance(atom, list):
                moved = advance(atom, states) if hi else [False] * len(states)
                states = [a or b for a, b in zip(states, moved)] if lo == 0 else moved
                continue
            sums = [0]
            for state in states:
                sums.append(sums[-1] + state)
            states, run = [], 0
            for j in range(len(value) + 1):
                run = run + 1 if j and atom.fullmatch(value[j - 1]) else 0
                left, right = max(0, j - hi, j - run), j - lo
                states.append(right >= left and sums[right + 1] > sums[left])
        return states
    states = advance(atoms, [True] + [not start] * len(value))
    return states[-1] if end else any(states)


def problem(p, root=False, depth=0):
    if not isinstance(p, dict) or depth > 2:
        return "unsupported schema shape"
    if not all(isinstance(k, str) for k in p):
        return "invalid schema keys"
    kind = p.get("type", "object" if root else "")
    if (not isinstance(kind, str) or kind not in KEYS
            or (kind == "object" and not root) or (root and kind != "object")):
        return "unsupported schema type"
    for key in p:
        if key not in META | KEYS[kind] | {"type", "enum", "const"}:
            # The caller scrubs provider text before showing this.
            return "unsupported constraint %s" % key
        v = p[key]
        if key in COUNTS and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
            return "invalid %s" % key
        if key in KEYS["number"] and (not finite(v) or (key == "multipleOf" and v <= 0)):
            return "invalid %s" % key
    if "enum" in p and (not isinstance(p["enum"], list) or not p["enum"]):
        return "invalid enum"
    if kind == "string":
        # JSON Schema's format and content keywords are annotations.
        # MCP's format=password still marks a credential in mcp.secret.
        if "pattern" in p:
            try:
                pattern_atoms(p["pattern"])
            except ValueError as e:
                return str(e)
    if kind == "object":
        props, req = p.get("properties", {}), p.get("required", [])
        if (not isinstance(props, dict) or not all(isinstance(k, str) for k in props)
                or not isinstance(req, list) or not all(isinstance(k, str) and k in props for k in req)):
            return "invalid object properties or required arguments"
        if "additionalProperties" in p and not isinstance(p["additionalProperties"], bool):
            return "unsupported constraint additionalProperties"
        for prop in props.values():
            why = problem(prop, depth=depth + 1)
            if why:
                return why
    if kind == "array":
        if depth > 1 or "uniqueItems" in p and not isinstance(p["uniqueItems"], bool):
            return "unsupported array constraint"
        return problem(p.get("items"), depth=depth + 1)
    return ""


def constraints(p, v):
    if "enum" in p and not any(equal(v, choice) for choice in p["enum"]):
        return "is not one of its choices"
    if "const" in p and not equal(v, p["const"]):
        return "is not its required value"
    if isinstance(v, str) and "pattern" in p and not pattern_matches(p["pattern"], v):
        return "does not match its pattern"
    if finite(v):
        if "exclusiveMinimum" in p and v <= p["exclusiveMinimum"]:
            return "must be above %s" % bound_text(p["exclusiveMinimum"])
        if "exclusiveMaximum" in p and v >= p["exclusiveMaximum"]:
            return "must be below %s" % bound_text(p["exclusiveMaximum"])
        if "multipleOf" in p:
            n, d = ratio(v)
            mn, md = ratio(p["multipleOf"])
            if (n * md) % (d * mn):
                return "must be a multiple of %s" % bound_text(p["multipleOf"])
    if isinstance(v, list):
        if len(v) < p.get("minItems", 0):
            return "has too few items"
        if p.get("uniqueItems") and any(equal(x, y) for i, x in enumerate(v) for y in v[:i]):
            return "must have unique items"
    if isinstance(v, dict) and not p.get("minProperties", 0) <= len(v) <= p.get("maxProperties", len(v)):
        return "has the wrong number of arguments"
    return ""
