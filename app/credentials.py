"""ScholarOne secrets are bound to an exact journal in the macOS login keychain."""
import json
import os
import re
import subprocess
import urllib.parse
import uuid
import engine
import store


def site(url):
    u=urllib.parse.urlparse(url)
    if u.scheme!='https' or u.hostname!='mc.manuscriptcentral.com' or u.username or u.password or u.port not in (None,443):
        raise engine.MonitorError('请使用 https://mc.manuscriptcentral.com/期刊代码 网址')
    slug=u.path.strip('/').split('/')[0]
    if not re.fullmatch('[A-Za-z0-9_-]{1,80}',slug):
        raise engine.MonitorError('请填写 ScholarOne 期刊入口网址')
    return 'https://mc.manuscriptcentral.com/'+slug


def connection_site(m):
    u=urllib.parse.urlparse(m.get('url',''))
    known={'openreview':('openreview.net',('https',),'https://openreview.net'),
           'coremail':('stu.xjtu.edu.cn',('https',),'https://stu.xjtu.edu.cn/coremail')
}
    if m.get('kind') in known:
        host,schemes,bound=known[m['kind']]
        if u.hostname==host and u.scheme in schemes and not u.username and not u.password and u.port in (None,443 if u.scheme=='https' else 80):return bound
        raise engine.MonitorError('此连接仅支持对应的官方网站')
    return site(m['url'])


def request(action,m,value=None):
    payload=dict(action=action,service=('org.watchtower.community.connection.' if m.get('kind') in ('openreview','coremail') else 'org.watchtower.community.scholarone.')+m['id'],site=connection_site(m))
    if value is not None:payload['value']=value
    helper=os.path.join(store.RESOURCES,'native','WatchtowerCredentials')
    try:
        r=subprocess.run([helper],input=json.dumps(payload),capture_output=True,text=True,timeout=60)
        out=json.loads(r.stdout)
        if not out.get('ok'):raise ValueError()
        return out.get('value')
    except Exception:
        raise engine.MonitorError('无法访问此账号的 macOS 钥匙串，请重新填写凭证或允许钥匙串访问') from None


def save(m,username,password):
    if not isinstance(username,str) or not isinstance(password,str) or not username.strip() or not password:
        raise engine.MonitorError('请填写账号和密码')
    if len(username)>300 or len(password)>2000:raise engine.MonitorError('账号或密码长度无效')
    request('put',m,dict(username=username.strip(),password=password))
    return dict(credential_ref=connection_site(m),credential_version=uuid.uuid4().hex,credential_blocked=False,credential_verified=None)


def load(m):
    if m.get('credential_ref')!=connection_site(m):raise engine.SessionExpired('请先在应用中填写此网站的账号和密码')
    if m.get('credential_blocked'):raise engine.SessionExpired('账号密码未通过验证，自动登录已暂停；请在连接设置中更新凭证')
    return request('get',m)


def block(m):
    latest=store.get_monitor(m['id'])
    if latest and latest.get('credential_version')==m.get('credential_version'):
        latest['credential_blocked']=True
        m['credential_blocked']=True
        store.upsert_monitor(latest)


def mark_verified(m):
    latest=store.get_monitor(m['id'])
    if latest and latest.get('credential_version')==m.get('credential_version'):
        latest['credential_verified']=m.get('credential_version')
        m['credential_verified']=latest['credential_verified']
        store.upsert_monitor(latest)
