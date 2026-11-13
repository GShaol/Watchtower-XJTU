# -*- coding: utf-8 -*-
"""Read-only fetching, parsing and snapshot comparison."""
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import store
from htmltree import parse

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class MonitorError(Exception):
    pass


class SessionExpired(MonitorError):
    pass


# ---------------------------------------------------------------- HTTP

class CredentialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if (req.has_header('Cookie') or req.has_header('Authorization')) and urllib.parse.urlparse(req.full_url).netloc != urllib.parse.urlparse(newurl).netloc:
            raise SessionExpired('登录跳转到其他站点，请重新登录；Cookie 未转发')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, cookie="", referer="", timeout=30, headers=None):
    h = {"User-Agent": UA, "Accept": "text/html,application/json,*/*;q=0.8",
         "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    if cookie:
        h["Cookie"] = cookie
    if referer:
        h["Referer"] = referer
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.build_opener(CredentialRedirect()).open(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = "utf-8"
            m = re.search(r"charset=([\w-]+)", resp.headers.get("Content-Type", ""), re.I)
            if m:
                charset = m.group(1)
            try:
                return resp.geturl(), raw.decode(charset, "replace")
            except LookupError:
                return resp.geturl(), raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise SessionExpired("HTTP %s" % e.code)
        raise MonitorError("HTTP %s" % e.code)
    except urllib.error.URLError as e:
        raise MonitorError("网络错误: %s" % e.reason)
    except TimeoutError:
        raise MonitorError("请求超时")


def looks_like_login(url, html):
    low = (url or "").lower()
    if "login" in low or "logon" in low:
        return True
    return "j_acegi_security_check" in html or bool(re.search(r'<input[^>]+type=[\"\']password', html, re.I))


def norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()




# ---------------------------------------------------------------- 字段抽取

def extract_fields(html, url, rules):
    """rules: [{name, selector, regex?, attr?, limit?}]"""
    root = parse(html)
    fields = {}
    for r in rules or []:
        name = (r.get("name") or "").strip()
        sel = (r.get("selector") or "").strip()
        if not name or not sel:
            continue
        nodes = root.select(sel)
        vals = []
        rx = None
        if r.get("regex"):
            try:
                rx = re.compile(r["regex"])
            except re.error:
                rx = None
        for n in nodes:
            attr = (r.get("attr") or "").strip()
            if attr:
                v = n.attrs.get(attr, "")
                if n.tag == "img" and not v:
                    v = n.attrs.get("src", "")
            else:
                v = n.text()
            v = norm_ws(v)
            if v and rx:
                m = rx.search(v)
                v = (m.group(1) if m and m.groups() else (m.group(0) if m else ""))
            if v:
                vals.append(v)
        vals = list(dict.fromkeys(vals))
        limit = int(r.get("limit") or 0)
        if limit > 0:
            vals = vals[:limit]
        if vals:
            fields[name] = vals[0] if len(vals) == 1 else " | ".join(vals[:20])
    return fields, root


def snapshot_from_fields(fields):
    ordered = {k: fields[k] for k in sorted(fields)}
    blob = json.dumps(ordered, ensure_ascii=False, sort_keys=True)
    return ordered, hashlib.sha1(blob.encode("utf-8")).hexdigest()


def title_of(root, url):
    for sel in ("title", "h1", "h2"):
        n = root.one(sel)
        if n:
            v = norm_ws(n.text())
            if v:
                return v
    return url


# ---------------------------------------------------------------- 网页 / 浏览器







# ---------------------------------------------------------------- API（表单 POST 接口）





# ---------------------------------------------------------------- OpenAlex











def run_check(monitor):
    import adapters,integrations
    kind=monitor.get('kind')
    if kind=='scholarone':
        import scholarone
        return scholarone.check(monitor)
    if kind=='xjtu_oa':return integrations.check_oa(monitor)
    if kind=='coremail':return integrations.check_coremail(monitor)
    if kind=='openreview':return integrations.check_openreview(monitor)
    if kind=='google_scholar':return adapters.check_google_scholar(monitor)
    raise MonitorError('Unsupported monitor type')


# ---------------------------------------------------------------- 差异

def diff_snapshots(old, new):
    if not old:
        return [], [], []
    of = old.get("fields") or {}
    nf = new.get("fields") or {}
    changes = []
    for k in nf:
        if k not in of:
            if k not in ("分篇",):
                changes.append((k, "", nf[k]))
        elif of[k] != nf[k]:
            if k == "分篇":
                continue
            changes.append((k, of[k], nf[k]))
    removed = [k for k in of if k not in nf]
    return changes, [], removed


def citation_delta(old, new):
    """对比两次快照的分篇被引，返回 [(work_id, 旧, 新, +n)]。"""
    try:
        o = json.loads((old.get("fields") or {}).get("分篇") or "{}")
        n = json.loads((new.get("fields") or {}).get("分篇") or "{}")
    except ValueError:
        return []
    out = []
    for wid, c in n.items():
        if wid in o and c > o[wid]:
            out.append((wid, o[wid], c, c - o[wid]))
    return out
