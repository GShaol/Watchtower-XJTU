"""In-memory, authenticated bridge to the app's own WebKit sessions.
No Apple Events, external browser, credentials in files, or public script endpoint.
"""
import hmac
import json
import os
import threading
import time
import uuid
from urllib.parse import urlparse
import engine

_TOKEN=os.environ.get('WATCHTOWER_COMMUNITY_SESSION_TOKEN','')
_lock=threading.Lock()
_jobs={}


def authorized(value):
    return bool(_TOKEN) and hmac.compare_digest(value or '',_TOKEN)


def submit(m,operation='evaluate',expression='',asynchronous=False,wait=True):
    if not _TOKEN:raise engine.MonitorError('请从 Watchtower 应用打开独立连接')
    u=urlparse(m.get('url',''))
    if u.scheme not in ('http','https') or not u.hostname:raise engine.MonitorError('连接网址无效')
    mid=m.get('id') or 'preview_'+uuid.uuid4().hex
    # Import only the existing site's login cookies into our own first session.
    allowed={'openreview.net':{'openreview.accessToken','openreview.refreshToken','openreview.user'},
             'stu.xjtu.edu.cn':{'Coremail','Coremail.sid','uid','locale'}}.get(u.hostname,set())
    seed=[]
    for part in m.get('cookie','').split(';'):
        key,sep,value=part.strip().partition('=')
        if sep and key in allowed:seed.append({'name':key,'value':value})
    job=dict(job_id=uuid.uuid4().hex,monitor_id=mid,title=m.get('title','连接账号'),url=m['url'],operation=operation,
             expression=expression,asynchronous=asynchronous,refresh=bool(m.get('refresh',True)),seed=seed)
    event=threading.Event();record=dict(job=job,event=event,claimed=False,expires=time.monotonic()+75)
    with _lock:_jobs[job['job_id']]=record
    if not wait:return job['job_id']
    if not event.wait(70):
        with _lock:_jobs.pop(job['job_id'],None)
        raise engine.MonitorError('应用内连接超时，请点击连接账号确认网站是否可用')
    with _lock:_jobs.pop(job['job_id'],None)
    response=record.get('response',{})
    if response.get('error'):raise engine.SessionExpired(response['error']) if response.get('needs_login') else engine.MonitorError(response['error'])
    result=response.get('result')
    if isinstance(result,str):
        try:result=json.loads(result)
        except ValueError:raise engine.MonitorError('网站未返回有效数据') from None
    return result


def pending():
    with _lock:
        now=time.monotonic()
        for key,record in list(_jobs.items()):
            if record['expires']<now:_jobs.pop(key,None)
        out=[]
        for record in _jobs.values():
            if not record['claimed']:
                record['claimed']=True;out.append(record['job'])
        return out


def complete(body):
    with _lock:
        record=_jobs.get(body.get('job_id'))
        if not record:return False
        record['response']={k:body[k] for k in ('result','error','needs_login') if k in body}
        record['event'].set()
        if record['job']['operation']=='open':_jobs.pop(body['job_id'],None)
    return True
