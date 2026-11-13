# -*- coding: utf-8 -*-
"""轻量 HTML 树 + 极简 CSS 选择器（够监控抓字段用，无第三方依赖）。"""
import re
from html.parser import HTMLParser


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.children = []
        self.parent = parent

    def iter(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                for n in c.iter():
                    yield n

    def text(self):
        parts = []

        def walk(n):
            for c in n.children:
                if isinstance(c, Node):
                    if c.tag in ("script", "style"):
                        continue
                    walk(c)
                    if c.tag in ("br", "p", "div", "li", "tr", "td", "h1", "h2", "h3"):
                        parts.append("\n")
                else:
                    parts.append(c)

        walk(self)
        raw = "".join(parts).replace("\xa0", " ")
        lines = []
        for ln in raw.split("\n"):
            ln = re.sub(r"[ \t\r\f\v]+", " ", ln).strip()
            if ln:
                lines.append(ln)
        return "\n".join(lines)

    def one(self, selector):
        found = self.select(selector, limit=1)
        return found[0] if found else None

    def select(self, selector, limit=None):
        groups = [s.strip() for s in selector.split(",") if s.strip()]
        out = []
        for g in groups:
            parts = _tokenize(g)
            nodes = [self]
            for i, part in enumerate(parts):
                nxt = []
                for n in nodes:
                    for m in n.iter():
                        if m is n and i > 0:
                            continue
                        if _matches(m, part):
                            nxt.append(m)
                nodes = nxt
                if not nodes:
                    break
            for n in nodes:
                if n not in out:
                    out.append(n)
                    if limit and len(out) >= limit:
                        return out
        return out


def _tokenize(sel):
    """支持 "a b"、"a > b"、"td:nth-child(2)"、".cls"、"#id"、"[attr=value]"。"""
    parts, buf, depth = [], "", 0
    i = 0
    while i < len(sel):
        ch = sel[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch.isspace() and depth == 0:
            if buf:
                parts.append(buf)
                buf = ""
        else:
            buf += ch
        i += 1
    if buf:
        parts.append(buf)
    return [p for p in parts if p and p != ">"]


_COMPOUND = re.compile(
    r"^(?P<tag>[a-zA-Z][\w-]*|\*)?"
    r"(?P<rest>(?:[.#][\w-]+|\[[^\]]+\]|:[\w-]+(?:\([^)]*\))?)*)$"
)
_PART = re.compile(r"([.#])([\w-]+)|\[([\w-]+)(?:([~^$*|]?=)(?:\"([^\"]*)\"|'([^']*)'|([^\]\s]+)))?\]|:([\w-]+)(?:\(([^)]*)\))?")


def _matches(node, compound):
    m = _COMPOUND.match(compound)
    if not m:
        return False
    tag = m.group("tag")
    if tag and tag != "*" and node.tag != tag.lower():
        return False
    rest = m.group("rest") or ""
    for pm in _PART.finditer(rest):
        kind = pm.group(1) or ("[" if pm.group(3) else ":")
        if kind == ".":
            classes = (node.attrs.get("class") or "").split()
            if pm.group(2) not in classes:
                return False
        elif kind == "#":
            if node.attrs.get("id") != pm.group(2):
                return False
        elif kind == "[":
            key = pm.group(3)
            op = pm.group(4)
            want = pm.group(5) or pm.group(6) or pm.group(7)
            have = node.attrs.get(key)
            if have is None:
                return False
            if op == "=" and have != want:
                return False
            if op == "^=" and not have.startswith(want):
                return False
            if op == "$=" and not have.endswith(want):
                return False
            if op == "*=" and want not in have:
                return False
        elif kind == ":":
            pseudo, arg = pm.group(8), pm.group(9)
            if pseudo == "first-child":
                if node.parent is None:
                    return False
                kids = [c for c in node.parent.children if isinstance(c, Node)]
                if not kids or kids[0] is not node:
                    return False
            elif pseudo == "nth-child" and arg:
                try:
                    n = int(arg.strip())
                except ValueError:
                    return False
                kids = [c for c in node.parent.children if isinstance(c, Node)] if node.parent else []
                if len(kids) < n or kids[n - 1] is not node:
                    return False
            elif pseudo == "nth-of-type" and arg:
                try:
                    n = int(arg.strip())
                except ValueError:
                    return False
                kids = [c for c in node.parent.children if isinstance(c, Node) and c.tag == node.tag] if node.parent else []
                if len(kids) < n or kids[n - 1] is not node:
                    return False
            elif pseudo == "last-child":
                kids = [c for c in node.parent.children if isinstance(c, Node)] if node.parent else []
                if not kids or kids[-1] is not node:
                    return False
    return True


class _Builder(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(n)
        if tag not in self.VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        n = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(n)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse(html):
    b = _Builder()
    try:
        b.feed(html)
        b.close()
    except Exception:
        pass
    return b.root
