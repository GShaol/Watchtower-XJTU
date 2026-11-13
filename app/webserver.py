"""Loopback-only dashboard and validated JSON API."""
import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import scheduler as sched_mod
import store
import session_bridge
from engine import MonitorError

DASHBOARD = os.path.join(store.RESOURCES, 'web', 'dashboard.html')
PUBLIC = ('id', 'kind', 'category', 'title', 'url', 'author_name', 'author_id', 'limit',
          'interval_minutes', 'enabled', 'fields', 'schedule', 'referer', 'origin', 'form',
          'mapping', 'transport', 'browser', 'refresh', 'setup_required', 'notifications', 'notification_mode', 'profile_id',
          'notification_plan','journal_code', 'journal_name', 'login_url', 'source_url')


def public_monitor(m):
    return dict({k: m[k] for k in PUBLIC if k in m}, has_cookie=bool(m.get('cookie')),has_credentials=bool(m.get('credential_ref')))


def state_payload():
    state = store.state()
    monitors = store.monitors()
    items = {}
    for m in monitors:
        v = state.get('items', {}).get(m['id'], {})
        keys = ('title', 'fields', 'last_ts', 'last_run', 'last_success', 'last_changed', 'error', 'ok',
                'summary', 'papers', 'total', 'works', 'source', 'transport', 'failures', 'unread', 'inbox_total', 'todo')
        item = {k: v[k] for k in keys if k in v}
        if v.get('source') in ('xjtu_oa', 'openreview', 'openreview_notifications'):
            item['fields'] = {}
        item['items'] = v.get('items', [])[:3] if m['kind'] in ('xjtu_oa','openreview','coremail') else v.get('items', [])[:20]
        item['running'] = m['id'] in sched_mod.scheduler.running
        item['next_ts'] = sched_mod.scheduler.next_ts(m, v)
        items[m['id']] = item
    return {'monitors': [public_monitor(m) for m in monitors], 'items': items,
            'recent': state.get('recent', []), 'settings': store.settings(), 'server_time': store.now_str()}


def validate(m):
    if not isinstance(m, dict):
        raise ValueError('请求格式无效')
    out = dict(m)
    out['id'] = str(m.get('id') or 'm_' + uuid.uuid4().hex[:10])
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', out['id']):
        raise ValueError('监控 ID 无效')
    if m.get('kind') not in ('scholarone','google_scholar','xjtu_oa','coremail','openreview'):
        raise ValueError('请选择有效类型')
    import community
    community.validate_module(out)
    out['title'] = str(m.get('title') or '').strip()[:120]
    if not out['title']:
        raise ValueError('请填写名称')
    if m['kind'] not in ('scholar', 'citations'):
        u = urlparse(m.get('url') or '')
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
            raise ValueError('请填写有效的 http / https 网址')
    if m['kind'] == 'google_scholar':
        u = urlparse(m['url'])
        if u.hostname != 'scholar.google.com' or u.path != '/citations' or not re.search(r'(?:^|&)user=[\w-]+', u.query):
            raise ValueError('请使用包含 user 参数的 Google Scholar 个人主页地址')
    if m['kind']=='scholarone':
        import credentials
        out['url']=credentials.site(m['url'])
    for name in ('login_url','source_url'):
        if m.get(name):
            u=urlparse(m[name])
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:
                raise ValueError('期刊入口网址无效')
    out['interval_minutes'] = max(1, min(10080, int(m.get('interval_minutes') or 30)))
    out['enabled'] = bool(m.get('enabled', True))
    out['notifications'] = bool(m.get('notifications', True))
    out['notification_mode'] = 'daily_digest' if m.get('notification_mode') == 'daily_digest' else 'changes'
    out['setup_required'] = bool(m.get('setup_required', False))
    schedule = m.get('schedule') or {}
    if schedule.get('type') == 'daily':
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', schedule.get('time', '')):
            raise ValueError('每天检查时间无效')
        out['schedule'] = {'type': 'daily', 'time': schedule['time']}
    else:
        out.pop('schedule', None)
        if out['notification_mode'] == 'daily_digest':
            raise ValueError('每日摘要需要设置每天固定时间')
    if 'notification_plan' in m:
        import push_plans
        out['notification_plan']=push_plans.validate(m['notification_plan'])
    fields = m.get('fields') or []
    if not isinstance(fields, list) or len(fields) > 20:
        raise ValueError('监控字段格式无效')
    for r in fields:
        if not isinstance(r, dict) or not r.get('name') or not r.get('selector'):
            raise ValueError('请填写字段名称和 CSS 选择器')
        if r.get('regex'):
            re.compile(r['regex'])
    if '\n' in m.get('cookie', '') or '\r' in m.get('cookie', ''):
        raise ValueError('Cookie 请只粘贴值，不能包含换行')
    return {k: v for k, v in out.items() if k in PUBLIC or k == 'cookie'}


def respond(h, obj, code=200):
    body = json.dumps(obj, ensure_ascii=False).encode()
    h.send_response(code)
    h.send_header('Content-Type', 'application/json; charset=utf-8')
    h.send_header('Content-Length', str(len(body)))
    h.send_header('Cache-Control', 'no-store')
    h.send_header('X-Content-Type-Options', 'nosniff')
    h.end_headers()
    h.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def local(self):
        return self.headers.get('Host', '') in ('127.0.0.1:' + str(self.server.server_port), 'localhost:' + str(self.server.server_port))

    def do_GET(self):
        if not self.local():
            return respond(self, {'error': '仅支持本机访问'}, 403)
        path = urlparse(self.path).path
        if path == '/api/internal/sessions':
            if self.headers.get('Origin') or not session_bridge.authorized(self.headers.get('X-Watchtower-Session')):
                return respond(self, {'error':'禁止访问'},403)
            return respond(self, {'jobs':session_bridge.pending()})
        if path in ('/dashboard.css','/dashboard.js'):
            asset=os.path.join(store.RESOURCES,'web',path[1:])
            with open(asset,'rb') as file:body=file.read()
            self.send_response(200)
            self.send_header('Content-Type','text/css; charset=utf-8' if path.endswith('.css') else 'application/javascript; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ('/', '/index.html'):
            with open(DASHBOARD, 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == '/api/state':
            return respond(self, state_payload())
        if path == '/api/health':
            return respond(self, {'app': 'watchtower', 'version': '0.1.0', 'pid': os.getpid()})
        if path == '/api/notification-status':
            import notifier
            return respond(self,notifier.notification_status())
        if path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return
        return respond(self, {'error': '页面不存在'}, 404)

    def do_POST(self):
        origin = self.headers.get('Origin')
        if not self.local() or (origin and urlparse(origin).netloc != self.headers.get('Host')):
            return respond(self, {'error': '仅允许本机看板操作'}, 403)
        if not self.headers.get('Content-Type', '').startswith('application/json'):
            return respond(self, {'error': '请使用 JSON 请求'}, 415)
        try:
            size = int(self.headers.get('Content-Length') or 0)
            internal_result=urlparse(self.path).path=='/api/internal/session-result'
            if internal_result and (origin or not session_bridge.authorized(self.headers.get('X-Watchtower-Session'))):
                return respond(self,{'error':'禁止访问'},403)
            if size > (4000000 if internal_result else 128000):
                raise ValueError('请求过大')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('请求格式无效')
            path = urlparse(self.path).path
            if path == '/api/internal/session-result':
                if origin or not session_bridge.authorized(self.headers.get('X-Watchtower-Session')):
                    return respond(self,{'error':'禁止访问'},403)
                return respond(self,{'ok':session_bridge.complete(body)})
            if path == '/api/connect':
                m=store.get_monitor(body.get('id'))
                if not m:return respond(self,{'error':'请先保存监控'},404)
                session_bridge.submit(m,operation='open',wait=False)
                return respond(self,{'ok':True})
            if path == '/api/save':
                m = validate(body)
                old = store.get_monitor(m['id']) or {}
                if m.get('notification_plan'):
                    previous={k:v for k,v in old.get('notification_plan',{}).items() if k!='anchor'}
                    m['notification_plan']['anchor']=old.get('notification_plan',{}).get('anchor',time.time()) if previous==m['notification_plan'] else time.time()
                if m['kind'] in ('scholarone','openreview','coremail'):
                    import credentials
                    import engine
                    try:
                        username=body.get('account_username',body.get('scholarone_username',''))
                        password=body.get('account_password',body.get('scholarone_password',''))
                        if username or password:
                            m.update(credentials.save(m,username,password))
                        elif old.get('credential_ref')==credentials.connection_site(m):
                            for key in ('credential_ref','credential_version','credential_blocked','credential_verified'):m[key]=old.get(key)
                        elif m['kind'] in ('coremail',) and old.get('cookie') and not body.get('clear_cookie'):
                            pass
                        else:raise engine.MonitorError('请填写此网站的账号和密码')
                    except engine.MonitorError as exc:return respond(self,{'error':str(exc)},422)
                    m.update(setup_required=False,transport='browser' if m['kind']=='scholarone' else 'http',fields=[])
                same_host = urlparse(old.get('url', '')).hostname == urlparse(m.get('url', '')).hostname
                if not m.get('cookie') and same_host and not body.get('clear_cookie'):
                    m['cookie'] = old.get('cookie', '')
                store.upsert_monitor(m)
                if m.get('enabled') and not m.get('setup_required'):
                    sched_mod.scheduler.submit(m)
                return respond(self, {'ok': True, 'id': m['id']})
            if path == '/api/toggle':
                m = store.get_monitor(body.get('id'))
                if not m:
                    return respond(self, {'error': '监控不存在'}, 404)
                m['enabled'] = bool(body.get('enabled'))
                store.upsert_monitor(m)
                return respond(self, {'ok': True})
            if path == '/api/check':
                ms = [store.get_monitor(body['id'])] if body.get('id') else store.monitors()
                count = 0
                for m in ms:
                    if m and not m.get('setup_required') and (body.get('id') or m.get('enabled', True)):
                        count += bool(sched_mod.scheduler.submit(m))
                return respond(self, {'ok': True, 'started': count})
            if path == '/api/read':
                store.mark_read()
                return respond(self, {'ok': True})
            if path == '/api/test-notify':
                import notifier
                ok = notifier.notify('Watchtower · 提醒测试', '监控更新会通过此通知到达。', subtitle=store.now_str(), popup=False)
                store.save_settings({'last_notification': {'time': store.now_str(), 'sent': bool(ok)}})
                return respond(self, {'ok': bool(ok),'status':store.settings().get('notification_status',{})})
            if path == '/api/settings':
                patch = {}
                if 'keep_awake' in body:patch['keep_awake']=bool(body['keep_awake'])
                if 'alert_popup' in body:
                    patch['alert_popup'] = bool(body['alert_popup'])
                if 'notify_sound' in body:
                    if body['notify_sound'] not in ('Glass', 'Submarine', 'Basso', ''):
                        raise ValueError('提示音无效')
                    patch['notify_sound'] = body['notify_sound']
                return respond(self, store.save_settings(patch))
            return respond(self, {'error': '接口不存在'}, 404)
        except (ValueError, TypeError, KeyError, re.error):
            return respond(self, {'error': '配置格式有误，请检查网址、时间及字段规则'}, 400)
        except MonitorError as exc:
            return respond(self, {'error':str(exc)}, 422)
        except Exception:
            return respond(self, {'error': '保存失败，请重试；旧配置已保留'}, 500)


class Server(ThreadingHTTPServer):
    daemon_threads = True


def serve(port):
    httpd = Server(('127.0.0.1', port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
