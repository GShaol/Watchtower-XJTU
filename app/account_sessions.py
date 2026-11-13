"""Password sign-in and encrypted session reuse for campus Coremail."""
import json
import time
from http.cookies import SimpleCookie
import adapters
import credentials
import engine
import session_bridge

SITES={
 'coremail':dict(login='https://stu.xjtu.edu.cn/coremail/index.jsp?cus=1',cookie='Coremail.sid'),
}
COLLECT=r"""(()=>{const visible=e=>!!e&&e.getClientRects().length>0;const body=(document.body?.innerText||'').slice(0,16000);const p=Array.from(document.querySelectorAll('input[type=password]')).find(visible);return JSON.stringify({url:location.href,login:!!p,challenge:/验证码已经发送|通过.{0,12}验证码方式进行验证|two.factor|verification code has been sent/i.test(body)||Array.from(document.querySelectorAll('input')).some(e=>visible(e)&&/验证码|verification code|captcha/i.test(e.placeholder||'')),badPassword:!!window.__watchtower_auth_error||!!document.querySelector('#loginError')?.value||/账号或密码错误|用户名或密码错误|密码不正确|密码错误|incorrect password|invalid credentials/i.test(body),hasError:!!document.querySelector('#loginError')?.value})})()"""


def _jar(cookie):
    jar=SimpleCookie()
    try:jar.load(cookie or '')
    except Exception:return {}
    return {key:item.value for key,item in jar.items()}


def _saved(m):
    try:return credentials.request('get',m) or {}
    except engine.MonitorError:return {}


def _persist(m,secret,cookie):
    # Keychain only; no account/password/session token ever enters config or snapshots.
    if secret.get('cookie')==cookie:return
    updated=dict(secret,cookie=cookie)
    try:credentials.request('put',m,updated)
    except engine.MonitorError:
        if m.get('credential_ref'):raise


def _login(m,site):
    secret=credentials.load(m)
    session_bridge.submit(m,operation='reset')
    target=dict(m,url=site['login'],refresh=True)
    data=adapters.browser_evaluate(target,COLLECT)
    target['refresh']=False
    if data.get('challenge'):
        raise engine.SessionExpired('网站需要验证码或短信验证，请点击登录 / 重新连接完成一次验证')
    if not data.get('login'):raise engine.MonitorError('登录表单尚未就绪，请点击登录 / 重新连接确认网站状态')
    # Only the configured site's own visible form and submit handler are used.
    script=r"""(()=>{if(location.hostname!==%s)return JSON.stringify({submitted:false});const visible=e=>e.getClientRects().length>0;const u=Array.from(document.querySelectorAll('input')).find(e=>visible(e)&&/用户名|邮箱|username|account/i.test(e.placeholder||''));const p=Array.from(document.querySelectorAll('input[type=password]')).find(visible);const b=Array.from(document.querySelectorAll('button,input[type=submit],input[type=button]')).find(e=>visible(e)&&/^(登录|登\s*录|log\s*in)$/i.test((e.innerText||e.value||'').trim()));if(!u||!p||!b)return JSON.stringify({submitted:false});u.value=%s;p.value=%s;for(const e of [u,p]){e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))}setTimeout(()=>b.click(),100);return JSON.stringify({submitted:true})})()""" % (json.dumps('stu.xjtu.edu.cn'),json.dumps(secret['username']),json.dumps(secret['password']))
    response=adapters.browser_evaluate(target,script,secret=True)
    del script
    if response.get('submitted'):
        secret['pending_version']=m.get('credential_version')
        credentials.request('put',m,secret)
    if not response.get('submitted'):raise engine.MonitorError('未找到标准登录表单，凭证未提交；请点击连接账号确认页面')
    for _ in range(5):
        time.sleep(1)
        data=adapters.browser_evaluate(target,COLLECT)
        if data.get('challenge'):
            raise engine.SessionExpired('网站需要验证码或短信验证，请点击登录 / 重新连接完成一次验证')
        if data.get('badPassword'):
            credentials.block(m)
            raise engine.SessionExpired('账号或密码未通过验证，自动登录已暂停；请更新账号密码')
        if not data.get('login'):break
    if data.get('login'):raise engine.SessionExpired('登录未完成，请点击登录 / 重新连接查看网站提示')
    cookie=(session_bridge.submit(m,operation='cookies') or {}).get('cookie','')
    if not _jar(cookie).get(site['cookie']):raise engine.SessionExpired('网站尚未建立有效会话，请在软件内完成登录验证')
    return cookie,secret


def check(m,read):
    site=SITES[m['kind']]
    secret=_saved(m)
    own=(session_bridge.submit(m,operation='cookies') or {}).get('cookie','')
    cookie=own if _jar(own).get(site['cookie']) else secret.get('cookie') or m.get('cookie','')
    new_credentials=bool(m.get('credential_version') and m.get('credential_verified')!=m['credential_version'])
    attempted_login=False
    if new_credentials and not (secret.get('pending_version')==m.get('credential_version') and _jar(own).get(site['cookie'])):
        cookie,secret=_login(m,site);attempted_login=True
    try:
        if not _jar(cookie).get(site['cookie']):raise engine.SessionExpired('请在软件内填写账号密码并保存连接')
        result=read(dict(m,cookie=cookie))
    except engine.SessionExpired:
        if attempted_login or not m.get('credential_ref'):raise
        cookie,secret=_login(m,site)
        result=read(dict(m,cookie=cookie))
    secret.pop('pending_version',None)
    _persist(m,secret,cookie)
    if m.get('credential_ref'):credentials.mark_verified(m)
    return result
