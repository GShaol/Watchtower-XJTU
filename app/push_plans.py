"""Notification cadence independent of site polling. Legacy monitors retain behavior."""
import datetime as dt
import hashlib
import json
import re
import threading
import time
import engine
import notifier
import store
CST=dt.timezone(dt.timedelta(hours=8))
_guard=threading.Lock()
_running=set()

def times(value):
    values=re.split(r'[,，\s]+',value.strip()) if isinstance(value,str) else value
    if not isinstance(values,list) or not values or len(values)>24 or any(not isinstance(v,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',v) for v in values):raise engine.MonitorError('请填写 1 至 24 个 HH:MM 时间，多个时间用逗号分隔')
    return sorted(set(values))

def validate(value):
    if not isinstance(value,dict) or value.get('mode') not in ('changes','interval','times'):raise engine.MonitorError('请选择推送方式')
    out={'mode':value['mode']}
    if out['mode']=='interval':
        minutes=int(value.get('minutes',60))
        if not 1<=minutes<=10080:raise engine.MonitorError('推送间隔需为 1 至 10080 分钟')
        out['minutes']=minutes
    if out['mode']=='times':out['times']=times(value.get('times'))
    return out

def slot(plan,now):
    anchor=plan.get('anchor',now);mode=plan['mode']
    if mode=='interval':
        period=plan['minutes']*60
        if now<anchor+period:return None
        return anchor+int((now-anchor)//period)*period
    if mode=='times':
        current=dt.datetime.fromtimestamp(now,CST)
        for offset in range(2):
            day=current-dt.timedelta(days=offset)
            for text in sorted(plan['times'],reverse=True):
                hh,mm=map(int,text.split(':'));candidate=day.replace(hour=hh,minute=mm,second=0,microsecond=0).timestamp()
                if anchor<candidate<=now:return candidate
    return None

def lines(snapshot):
    if snapshot.get('error'):return '连接异常：'+snapshot['error']
    if not snapshot.get('ok'):return '尚未成功读取，暂无可用数据'
    parts=[]
    for paper in snapshot.get('papers',[])[:3]:parts.append('#'+str(paper.get('id',''))+' '+str(paper.get('status','')))
    if snapshot.get('source')=='google_scholar':parts.append('总被引 '+str(snapshot.get('total','—'))+' · h 指数 '+str(snapshot.get('fields',{}).get('h 指数','—')))
    elif snapshot.get('source')=='coremail':parts.append('未读 '+str(snapshot.get('unread','—'))+' · 收件箱 '+str(snapshot.get('inbox_total','—')))
    for item in snapshot.get('items',[])[:3]:parts.append(str(item.get('title','')))
    if not parts:parts=[str(key)+'：'+str(value) for key,value in list(snapshot.get('fields',{}).items())[:3] if key!='分篇']
    if snapshot.get('last_success'):parts.append('最近成功 '+dt.datetime.fromtimestamp(snapshot['last_success'],CST).strftime('%m-%d %H:%M'))
    return '\n'.join(parts) or '暂无状态'

def tick(scheduler,now=None):
    now=time.time() if now is None else now
    for m in store.monitors():
        plan=m.get('notification_plan')
        if not plan or plan['mode']=='changes' or not m.get('enabled',True) or not m.get('notifications',True) or m.get('setup_required') or m['id'] in scheduler.running:continue
        target=slot(plan,now)
        if target is None:continue
        fingerprint=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
        old=store.state().get('push_plans',{}).get(m['id'],{})
        if old.get('fingerprint')==fingerprint and old.get('last_slot',0)>=target:continue
        with _guard:
            if m['id'] in _running:continue
            _running.add(m['id'])
        def run(m=dict(m),target=target,fingerprint=fingerprint):
            try:
                if store.get_monitor(m['id'])!=m:return
                store.update_push_state(m['id'],{'fingerprint':fingerprint,'last_slot':target})
                snapshot=store.state().get('items',{}).get(m['id'],{})
                notifier.notify('Watchtower · 定时汇总',lines(snapshot),subtitle=m['title'],url=m.get('url'),popup=False)
            finally:
                with _guard:_running.discard(m['id'])
        threading.Thread(target=run,daemon=True).start()
