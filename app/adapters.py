"""Site-specific read-only adapters. No passwords or mailbox contents are stored."""
import json
import os
import re
import subprocess
import threading
import urllib.parse
import urllib.request

import engine
import store

_browser_lock = threading.Lock()



def snap(m, fields, **extra):
    fields, fp = engine.snapshot_from_fields(fields)
    return dict(title=m.get('title'), url=m.get('url'), fields=fields, fingerprint=fp,
                baseline_version=2, **extra)






def browser_evaluate(m, expression, asynchronous=False, secret=False):
    """Use only Watchtower's isolated session. Never launch or control Edge."""
    import session_bridge
    with _browser_lock:
        return session_bridge.submit(m,expression=expression,asynchronous=asynchronous)


def browser_html(m):
    data = browser_evaluate(m, 'JSON.stringify({url:location.href,html:document.documentElement.outerHTML})')
    if urllib.parse.urlparse(data.get('url','')).hostname != urllib.parse.urlparse(m['url']).hostname:
        raise engine.MonitorError('浏览器跳转到其他站点，请先完成登录')
    return data['url'], data['html']


def parse_google(m, html):
    root = engine.parse(html)
    table = root.one('#gsc_rsb_st')
    if not table or not root.one('#gsc_prf_in'):
        raise engine.MonitorError('私人 Scholar 尚未连接，请点击登录 / 重新连接，在软件内登录创建此主页的 Google 账号')
    rows = table.select('tr')
    metrics = []
    for row in rows:
        nums = row.select('.gsc_rsb_std')
        if nums:
            value = nums[0].text().replace(',', '').strip()
            if not value.isdigit():
                raise engine.MonitorError('Google Scholar 引用统计格式变化，保留旧基线')
            metrics.append(value)
    if len(metrics) < 3:
        raise engine.MonitorError('Google Scholar 引用统计不完整')
    fields = dict(zip(['总被引', 'h 指数', 'i10 指数'], metrics[:3]))
    return snap(m, fields, source='google_scholar', total=int(metrics[0]), summary='总被引 ' + metrics[0])


def scholar_session_url(url):
    parsed=urllib.parse.urlsplit(url)
    query=urllib.parse.urlencode([(key,value) for key,value in urllib.parse.parse_qsl(parsed.query) if key!='authuser'])
    return urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path,query,''))


def check_google_scholar(m):
    target=dict(m,url=scholar_session_url(m['url']),transport='browser')
    expression="JSON.stringify({url:location.href,html:(document.querySelector('#gsc_prf_in')?.outerHTML||'')+(document.querySelector('#gsc_rsb_st')?.outerHTML||'')})"
    data=browser_evaluate(target,expression)
    actual=urllib.parse.urlparse(data.get('url',''))
    if actual.hostname!='scholar.google.com':
        raise engine.SessionExpired('请先在应用内完成 Google 登录，再重新检查私人 Scholar')
    expected_user=urllib.parse.parse_qs(urllib.parse.urlparse(target['url']).query).get('user')
    if urllib.parse.parse_qs(actual.query).get('user')!=expected_user:
        raise engine.SessionExpired('当前 Google 账号未打开指定的私人 Scholar 主页，请确认登录了创建此主页的账号')
    return parse_google(m,data.get('html',''))






def check_browser(m):
    if not m.get('fields'):
        raise engine.MonitorError('请先在「监控字段」中指定要观察的未读数或状态元素')
    final, html = browser_html(m)
    if engine.looks_like_login(final, html):
        raise engine.SessionExpired('浏览器页面需要重新登录')
    fields, root = engine.extract_fields(html, final, m['fields'])
    if len(fields) != len(m['fields']):
        raise engine.MonitorError('未找到监控字段，请确认已登录，并更新 CSS 选择器')
    return snap(m, fields, source='browser', summary='；'.join('%s %s' % i for i in fields.items()))


def scan_browser(m):
    m = dict(m, kind=m.get('kind') or 'browser', refresh=False)
    _, html = browser_html(m)
    if engine.looks_like_login(m['url'], html):
        raise engine.SessionExpired('请先完成网站登录，再扫描页面')
    root = engine.parse(html)
    candidates, used = [], set()
    for n in root.iter():
        if n.tag not in ('span', 'b', 'em', 'strong', 'a', 'div', 'td', 'button', 'li'):
            continue
        text = engine.norm_ws(n.text())
        if not text or len(text) > 75:
            continue
        label = text
        if text.isdigit() and n.parent:
            label = engine.norm_ws(n.parent.text())
        if not re.search(r'未读|待办|待处理|待审|外审|初审|终审|修回|录用|under review|awaiting|unread|inbox', label, re.I):
            continue
        if len(label) > 100:
            continue
        mid = n.attrs.get('id', '')
        selector = '#' + mid if re.fullmatch(r'[A-Za-z_][\w-]*', mid) else ''
        if not selector:
            classes = [c for c in n.attrs.get('class', '').split() if re.fullmatch(r'[A-Za-z_][\w-]*', c)]
            if classes:
                selector = n.tag + ''.join('.' + c for c in classes[:3])
        if not selector or selector in used or len(root.select(selector)) != 1:
            continue
        used.add(selector)
        candidates.append({'text': label[:100], 'selector': selector})
        if len(candidates) == 20:
            break
    return candidates
