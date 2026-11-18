"""Minimal S-expression reader/writer for KiCad files.

Atoms are kept as Python str. Quoted strings are wrapped in Q so they are
written back quoted; bare tokens stay plain str.
"""
import re


class Q(str):
    """A quoted string atom."""


_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:\\.|[^"\\])*)"|([^\s()"]+))', re.S)


def parse(text):
    stack = [[]]
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError(f"parse error at {pos}: {text[pos:pos+40]!r}")
        pos = m.end()
        if m.group(1):
            stack.append([])
        elif m.group(2):
            done = stack.pop()
            stack[-1].append(done)
        elif m.group(3) is not None:
            stack[-1].append(Q(m.group(3).replace('\\"', '"').replace("\\\\", "\\")))
        elif m.group(4):
            stack[-1].append(m.group(4))
    assert len(stack) == 1, "unbalanced"
    return stack[0][0] if len(stack[0]) == 1 else stack[0]


def _atom(a):
    if isinstance(a, Q):
        return '"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(a, bool):
        return "yes" if a else "no"
    if isinstance(a, float):
        s = f"{a:.4f}".rstrip("0").rstrip(".")
        return s if s not in ("-0", "") else "0"
    return str(a)


def dump(node, indent=0):
    if not isinstance(node, list):
        return _atom(node)
    # short lists on one line
    flat = "(" + " ".join(dump(x) if isinstance(x, list) else _atom(x) for x in node) + ")"
    if len(flat) < 100 and "\n" not in flat:
        return flat
    pad = "\t" * (indent + 1)
    head = []
    rest = []
    for x in node:
        (rest if (isinstance(x, list) or rest) else head).append(x)
    out = "(" + " ".join(_atom(x) for x in head)
    for x in rest:
        out += "\n" + pad + dump(x, indent + 1)
    return out + "\n" + "\t" * indent + ")"


def find(node, key):
    """All direct children lists whose head is key."""
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def find1(node, key):
    r = find(node, key)
    return r[0] if r else None


def prop(node, name):
    for p in find(node, "property"):
        if p[1] == name:
            return p
    return None
