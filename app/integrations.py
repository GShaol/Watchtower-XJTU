"""Read-only OA announcements, Coremail folder statistics, and OpenReview notes."""
import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie

import adapters
import engine

OA = 'https://oa.xjtu.edu.cn/'
OPENREVIEW_API = 'https://api2.openreview.net'


def cookies(value):
    jar = SimpleCookie()
    try:
        jar.load(value or '')
        return {k: v.value for k, v in jar.items()}
    except Exception:
        raise engine.SessionExpired('登录 Cookie 格式无效，请重新复制')


def request_json(url, cookie='', token='', body=None, origin=''):
    headers = {'User-Agent': engine.UA, 'Accept': 'application/json,text/*;q=0.99'}
    if cookie:
        headers['Cookie'] = cookie
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if origin:
        headers.update(Origin=origin, Referer=origin + '/', **{'X-Url': origin + '/', 'X-Source': 'Watchtower local monitor'})
    if body is not None:
        headers['Content-Type'] = 'application/json; charset=UTF-8'
    req = urllib.request.Request(url, headers=headers, data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.build_opener(engine.CredentialRedirect()).open(req, timeout=25) as response:
            raw = response.read()
            payload = json.loads(raw.decode('utf-8'))
            received = response.headers.get_all('Set-Cookie') or []
            return payload, received
    except urllib.error.HTTPError as e:
        # HTML 403 is a transport/site-gateway refusal, not evidence of an expired session.
        raw = e.read(2000).decode('utf-8', 'replace')
        if e.code == 401 or (e.code == 403 and raw.lstrip().startswith('{')):
            raise engine.SessionExpired('登录态已失效，请更新此网站的 Cookie')
        raise engine.MonitorError('站点网关拒绝请求（HTTP %s），保留上次数据；可改用已登录浏览器读取' % e.code)
    except (urllib.error.URLError, TimeoutError):
        raise engine.MonitorError('网络连接失败，保留上次成功数据')
    except (ValueError, UnicodeError):
        raise engine.MonitorError('接口未返回有效统计，保留上次成功数据')


def parse_oa(m, html):
    root = engine.parse(html)
    items, seen = [], set()
    for anchor in root.select('a'):
        match = re.search(r"gotodetail_tz\(['\"]([^'\"]+)['\"]\)", anchor.attrs.get('onclick', ''))
        if not match:
            continue
        mid = match.group(1)
        title = engine.norm_ws(anchor.text())
        parent = anchor.parent
        for _ in range(4):
            if not parent or parent.tag == 'tr':
                break
            parent = parent.parent
        date = re.search(r'\b20\d{2}-\d{2}-\d{2}\b', parent.text() if parent else '')
        if not title or not date:
            raise engine.MonitorError('OA 公告字段不完整，保留旧列表')
        if mid in seen:
            continue
        seen.add(mid)
        items.append(dict(id=mid, title=title, published=date.group(), unit='西安交通大学',
                          url=OA + 'zxgg_readcount.jsp?' + urllib.parse.urlencode({'processInsId':mid})))
    if not items:
        raise engine.MonitorError('未找到 OA「最新公告」，保留上次列表')
    items.sort(key=lambda i: i['published'], reverse=True)
    return adapters.snap(m, {i['id']:i['title'] for i in items}, source='xjtu_oa', items=items,
                         total=len(items), summary='最新公告：' + items[0]['title'])


def check_oa(m):
    try:
        _, html = engine.fetch(OA, timeout=15)
    except engine.MonitorError:
        # Public campus notices can time out through a VPN; retry directly with normal TLS verification.
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req=urllib.request.Request(OA,headers={'User-Agent':engine.UA})
            with opener.open(req,timeout=15) as response:
                html=response.read().decode('utf-8','replace')
        except Exception:
            raise engine.MonitorError('OA 公告连接暂时失败，已保留上次成功列表')
    return parse_oa(m, html)


def parse_coremail(m, payload):
    if payload.get('code') != 'S_OK':
        if payload.get('code') in ('FA_INVALID_SESSION', 'FA_SESSION_EXPIRED', 'FA_NOT_LOGIN', 'FA_SECURITY'):
            raise engine.SessionExpired('学生邮箱会话已过期，请在软件内重新连接账号')
        raise engine.MonitorError('邮箱未返回有效文件夹统计，保留上次数据')
    rows = payload.get('var')
    if not isinstance(rows, list):
        raise engine.MonitorError('邮箱文件夹统计不完整')
    inbox = next((r for r in rows if r.get('id') == 1), None)
    if not inbox:
        raise engine.MonitorError('未找到收件箱统计')
    stats = inbox.get('stats') or {}
    unread, total = stats.get('unreadMessageCount'), stats.get('messageCount')
    if not isinstance(unread, int) or not isinstance(total, int) or min(unread,total)<0:
        raise engine.MonitorError('未读数统计不完整')
    todo = next((r for r in rows if r.get('id') == -5), {})
    todo_count = todo.get('stats', {}).get('messageCount', 0)
    return adapters.snap(m, {'未读邮件': str(unread), '收件箱邮件': str(total), '待办邮件': str(todo_count)},
                         source='coremail', unread=unread, inbox_total=total, todo=todo_count,
                         summary='未读 %d 封 · 收件箱 %d 封' % (unread,total))


def check_coremail(m):
    import account_sessions
    return account_sessions.check(m,_coremail_request)


def _coremail_request(m):
    cookie=m.get('cookie','')
    sid=cookies(cookie).get('Coremail.sid')
    if not sid:raise engine.SessionExpired('请在软件内填写邮箱账号密码并保存连接')
    url = 'https://stu.xjtu.edu.cn/coremail/XT/jsp/mail.jsp?' + urllib.parse.urlencode({'func':'getAllFolders','sid':sid})
    payload, _ = request_json(url, cookie=cookie)
    result=parse_coremail(m,payload)
    list_url='https://stu.xjtu.edu.cn/coremail/s/json?'+urllib.parse.urlencode({'sid':sid,'func':'mbox:listMessages'})
    latest,_=request_json(list_url,cookie=cookie,body={'fid':1,'start':0,'limit':3,'order':'receivedDate','desc':True})
    result['items']=parse_coremail_latest(latest,result['inbox_total'])
    return result


def parse_coremail_latest(payload,inbox_total=None):
    if payload.get('code') in ('FA_INVALID_SESSION','FA_SESSION_EXPIRED','FA_NOT_LOGIN','FA_SECURITY'):
        raise engine.SessionExpired('学生邮箱会话已过期，请在软件内重新连接账号')
    if payload.get('code')!='S_OK' or not isinstance(payload.get('var'),list):
        raise engine.MonitorError('最新邮件列表未读取完整，保留上次数据')
    rows=payload['var']
    if not rows and inbox_total:
        raise engine.MonitorError('收件箱非空但未返回邮件列表，保留上次数据')
    items=[]
    for row in rows[:3]:
        if not isinstance(row,dict) or not row.get('id') or 'subject' not in row or not row.get('from') or not row.get('receivedDate'):
            raise engine.MonitorError('最新邮件字段不完整，保留上次数据')
        items.append(dict(id=str(row['id']),title=engine.norm_ws(row['subject'])[:500] or '（无主题）',
                          sender=engine.norm_ws(row['from'])[:300],published=str(row['receivedDate']).replace('T',' ')[:16],
                          url='https://stu.xjtu.edu.cn/coremail/index.jsp?cus=1'))
    return items


def value(note, name, default=''):
    item = note.get('content', {}).get(name, default)
    return item.get('value',default) if isinstance(item,dict) else item


def parse_openreview(m, notes):
    papers, fields, replies = [], {}, {}
    for note in notes:
        if not note.get('id') or note.get('replyto') or note.get('ddate'):
            continue
        nid = note['id']
        title = str(value(note,'title','未命名稿件'))
        direct = note.get('details', {}).get('replies', [])
        if not isinstance(direct,list):
            raise engine.MonitorError('OpenReview 评审数据不完整')
        visible = [r for r in direct if not r.get('ddate')]
        counts = {'review':0,'comment':0,'decision':0}
        latest = 0
        decisions = []
        for reply in visible:
            rid=reply.get('id')
            if not rid:
                raise engine.MonitorError('OpenReview 回复缺少 ID')
            invitations = reply.get('invitations') or [reply.get('invitation','')]
            typ = ' '.join(invitations).lower()
            typ = 'decision' if 'decision' in typ else ('review' if 'review' in typ and 'meta' not in typ else 'comment')
            counts[typ] += 1
            decision = value(reply,'decision')
            if decision:decisions.append(str(decision))
            # Only a digest is retained for review text; bodies and scores are never stored.
            digest = hashlib.sha256(json.dumps(reply.get('content',{}),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            stamp = reply.get('tmdate') or reply.get('mdate') or reply.get('tcdate') or reply.get('cdate') or 0
            replies[rid] = {'paper_id':nid,'type':typ,'digest':digest,'modified':stamp}
            latest=max(latest,stamp)
        venue = str(value(note,'venue','') or value(note,'venueid',''))
        decision = ' / '.join(dict.fromkeys(decisions))
        summary = '%d 条评审 · %d 条讨论' % (counts['review'],counts['comment'])
        if decision:summary += ' · '+decision
        # Content edits, venue/decision changes, new replies, and reply edits are meaningful.
        content_fingerprint = hashlib.sha256(json.dumps(note.get('content',{}),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        fields[nid] = json.dumps({'content':content_fingerprint,'replies':{r['id']:replies[r['id']]['digest'] for r in visible},'decision':decision},sort_keys=True)
        papers.append(dict(id=nid,title=title,status=summary,venue=venue,review_count=counts['review'],comment_count=counts['comment'],
                           decision=decision,url='https://openreview.net/forum?id='+urllib.parse.quote(nid),latest=latest))
    return adapters.snap(m,fields,source='openreview',papers=papers,reply_meta=replies,total=len(papers),
                         summary='%d 篇稿件 · %d 条可见回复' % (len(papers),len(replies)))


def _token_exp(token):
    try:
        segment=token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(segment+'='*(-len(segment)%4)))['exp']
    except Exception:return 0


def check_openreview(m):
    return check_openreview_account(m)


def parse_openreview_notifications(m, html):
    root = engine.parse(html)
    if engine.looks_like_login(m['url'],html):
        raise engine.SessionExpired('OpenReview 需要重新登录，请点击连接账号，在应用内完成登录')
    table = root.one('.messages-table')
    if not table:
        alert = root.one('.alert-danger')
        detail = engine.norm_ws(alert.text())[:180] if alert else ''
        raise engine.MonitorError('OpenReview 通知列表仍在加载或未登录' + ('：'+detail if detail else ''))
    items=[]
    for row in table.select('tr'):
        heading=row.one('.email-title h4')
        if not heading:continue
        title=engine.norm_ws(heading.text())
        sent=row.one('.email-sent')
        sent=engine.norm_ws(sent.text()) if sent else ''
        reference=row.one('.email-parent')
        reference=engine.norm_ws(reference.text()) if reference else ''
        content=row.one('.markdown-rendered')
        content_hash=hashlib.sha256((content.text() if content else '').encode()).hexdigest()
        link='https://openreview.net/notifications'
        for anchor in row.select('a'):
            u=urllib.parse.urlparse(urllib.parse.urljoin('https://openreview.net/',anchor.attrs.get('href','')))
            query=urllib.parse.parse_qs(u.query)
            if u.hostname=='openreview.net' and u.path=='/forum' and query.get('id'):
                link='https://openreview.net/forum?'+urllib.parse.urlencode({'id':query['id'][0]})
                break
        mid=hashlib.sha256(json.dumps([title,sent,reference,content_hash],ensure_ascii=False).encode()).hexdigest()[:32]
        items.append(dict(id=mid,title=title,sent=sent,reference=reference,url=link))
    if not items:
        empty=table.one('.empty-message')
        if not empty or 'No messages found' not in empty.text():
            raise engine.MonitorError('OpenReview 通知列表仍在加载，保留旧数据')
    return adapters.snap(dict(m,url='https://openreview.net/notifications'),{i['id']:i['title'] for i in items},
                         source='openreview_notifications',items=items,total=len(items),summary='最新页面 %d 条通知' % len(items))


def parse_openreview_rows(m, data):
    u=urllib.parse.urlparse(data.get('url',''))
    if u.hostname!='openreview.net' or 'login' in u.path:
        raise engine.SessionExpired('OpenReview 页面需要重新登录')
    if re.search(r'must be logged in|unauthorized|forbidden',str(data.get('error','')),re.I):
        raise engine.SessionExpired('请在软件设置中填写 OpenReview 账号密码并保存连接')
    if data.get('error'):
        raise engine.MonitorError('OpenReview 通知接口暂不可用，保留旧数据')
    if not data.get('hasTable'):
        raise engine.MonitorError('OpenReview 通知列表仍在加载或未登录' + ('：'+str(data.get('error'))[:160] if data.get('error') else ''))
    rows=data.get('items')
    if not isinstance(rows,list) or (not rows and not data.get('empty')):
        raise engine.MonitorError('OpenReview 通知列表仍在加载，保留旧数据')
    items=[]
    for row in rows:
        title=engine.norm_ws(row.get('title'))
        if not title:raise engine.MonitorError('OpenReview 通知标题不完整')
        sent=engine.norm_ws(row.get('sent'));reference=engine.norm_ws(row.get('reference'))
        link='https://openreview.net/notifications'
        for href in row.get('links',[]):
            parsed=urllib.parse.urlparse(urllib.parse.urljoin('https://openreview.net/',href))
            query=urllib.parse.parse_qs(parsed.query)
            if parsed.hostname=='openreview.net' and parsed.path=='/forum' and query.get('id'):
                link='https://openreview.net/forum?'+urllib.parse.urlencode({'id':query['id'][0]});break
        mid=hashlib.sha256(json.dumps([title,sent,reference,link],ensure_ascii=False).encode()).hexdigest()[:32]
        items.append(dict(id=mid,title=title,sent=sent,reference=reference,url=link))
    return adapters.snap(dict(m,url='https://openreview.net/notifications'),{i['id']:i['title'] for i in items},
                         source='openreview_notifications',items=items,total=len(items),summary='最新页面 %d 条通知' % len(items))


def check_openreview_notifications(m):
    # Extract a small metadata payload instead of transferring an entire React/email DOM over Apple Events.
    expression="""JSON.stringify({url:location.href,hasTable:!!document.querySelector('.messages-table'),empty:!!document.querySelector('.messages-table .empty-message')?.textContent?.includes('No messages found'),error:document.querySelector('.alert-danger')?.textContent?.slice(0,160)||'',items:Array.from(document.querySelectorAll('.messages-table .email-title h4')).map(h=>{const r=h.closest('tr');return {title:h.textContent,sent:r.querySelector('.email-sent')?.textContent||'',reference:r.querySelector('.email-parent')?.textContent||'',links:Array.from(r.querySelectorAll('a')).map(a=>a.href).filter(h=>h.includes('/forum?')).slice(0,3)}})})"""
    target=dict(m,url='https://openreview.net/notifications',refresh=True)
    for attempt in range(4):
        data=adapters.browser_evaluate(target,expression)
        try:return parse_openreview_rows(target,data)
        except engine.SessionExpired:raise
        except engine.MonitorError:
            if attempt==3:raise
            time.sleep(2);target['refresh']=False



def check_openreview_account(m):
    """Official read-only messages API; secrets and renewable session stay in Keychain."""
    import credentials
    secret=credentials.load(m)
    def login():
        try:
            response,received=request_json(OPENREVIEW_API+'/login',body={'id':secret['username'],'password':secret['password']},origin='https://openreview.net')
        except engine.SessionExpired:
            credentials.block(m)
            raise engine.SessionExpired('OpenReview 账号或密码未通过验证，请更新后重新连接') from None
        if response.get('mfaPending'):
            raise engine.SessionExpired('OpenReview 需要二次验证，请在应用内登录窗口完成验证')
        token=response.get('token')
        if not isinstance(token,str) or not token or not isinstance(response.get('user'),dict):
            raise engine.MonitorError('OpenReview 未确认登录成功，保留旧数据')
        secret.update(token=token,user=response['user'])
        for header in received:
            refresh=cookies(header).get('openreview.refreshToken')
            if refresh:secret['refreshToken']=refresh
        credentials.request('put',m,secret)
    if not secret.get('token') or _token_exp(secret['token'])<time.time()+300:login()
    user=secret.get('user') or {}
    profile=user.get('profile') or {}
    # Official notification UI selects confirmed email addresses from this profile.
    pid=profile.get('id') or user.get('id')
    if not pid:raise engine.MonitorError('OpenReview 未返回账号信息')
    try:
        profile_result,_=request_json(OPENREVIEW_API+'/profiles?'+urllib.parse.urlencode({'id':pid}),token=secret['token'],origin='https://openreview.net')
    except engine.SessionExpired:
        login();user=secret['user'];profile=user.get('profile') or {};pid=profile.get('id') or user.get('id')
        profile_result,_=request_json(OPENREVIEW_API+'/profiles?'+urllib.parse.urlencode({'id':pid}),token=secret['token'],origin='https://openreview.net')
    profiles=profile_result.get('profiles')
    if not isinstance(profiles,list) or not profiles:raise engine.MonitorError('OpenReview 账号资料未读取完整')
    content=profiles[0].get('content') or {}
    emails=content.get('emailsConfirmed') or []
    preferred=content.get('preferredEmail')
    if preferred:emails=[preferred]+[email for email in emails if email!=preferred]
    if not emails:raise engine.MonitorError('OpenReview 账号没有已确认的通知邮箱')
    items={}
    for email in dict.fromkeys(emails):
        after=None
        for page in range(20):
            query={'to':email,'limit':1000}
            if after:query['after']=after
            payload,_=request_json(OPENREVIEW_API+'/messages?'+urllib.parse.urlencode(query),token=secret['token'],origin='https://openreview.net')
            messages=payload.get('messages')
            if not isinstance(messages,list):raise engine.MonitorError('OpenReview 通知列表未读取完整')
            for message in messages:
                mid=message.get('id');subject=(message.get('content') or {}).get('subject')
                if not mid or not subject:raise engine.MonitorError('OpenReview 通知字段不完整')
                timestamp=message.get('timestamp',0)*1000 or message.get('cdate',0)
                sent=time.strftime('%Y-%m-%d %H:%M',time.gmtime(timestamp/1000+8*3600)) if timestamp else 'Not Sent'
                # Deliberately do not persist message bodies, recipient addresses or viewed status.
                items[mid]=dict(id=mid,title=engine.norm_ws(subject),sent=sent,reference=str(message.get('referrer') or ''),url='https://openreview.net/notifications',_time=timestamp)
            if len(messages)<1000:break
            cursor=messages[-1].get('id')
            if cursor==after:raise engine.MonitorError('OpenReview 通知分页异常，保留旧数据')
            after=cursor
        else:raise engine.MonitorError('OpenReview 通知超出本次读取范围，保留旧数据')
    rows=sorted(items.values(),key=lambda item:item.pop('_time'),reverse=True)
    credentials.mark_verified(m)
    result=adapters.snap(m,{item['id']:item['title'] for item in rows},source='openreview_notifications',items=rows,total=len(rows),summary='账号已连接 · %d 条通知'%len(rows))
    result['baseline_version']=3
    return result
