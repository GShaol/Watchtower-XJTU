"""Independent local checks, durable changes, and Asia/Shanghai scheduling."""
import datetime
import threading
import time
import uuid

import engine
import notifier
import store

CST = datetime.timezone(datetime.timedelta(hours=8))


class Scheduler:
    def __init__(self):
        self.stopping = threading.Event()
        self.thread = None
        self.running = {}
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(4)

    @property
    def recent(self):
        return store.state().get('recent', [])

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()

    def _loop(self):
        while not self.stopping.is_set():
            try:
                self.tick()
            except Exception:
                store.log('调度异常，将自动重试')
            self.stopping.wait(15)

    def _due(self, m, st, now):
        if not m.get('enabled', True) or m.get('setup_required'):
            return False
        sched = m.get('schedule') or {}
        if sched.get('type') == 'daily':
            t = datetime.datetime.fromtimestamp(now, CST)
            if st.get('scheduled_day') == t.date().isoformat():
                return False
            hh, mm = map(int, sched.get('time', '09:30').split(':'))
            if (t.hour, t.minute) < (hh, mm):
                return False
            return now - st.get('scheduled_attempt', 0) >= 1800
        return now - st.get('last_ts', 0) >= max(1, int(m.get('interval_minutes') or 30)) * 60

    def next_ts(self, m, st):
        if not m.get('enabled', True) or m.get('setup_required'):
            return None
        now = time.time()
        if (m.get('schedule') or {}).get('type') == 'daily':
            t = datetime.datetime.fromtimestamp(now, CST)
            hh, mm = map(int, m['schedule'].get('time', '09:30').split(':'))
            next_t = t.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if st.get('scheduled_day') == t.date().isoformat():
                next_t += datetime.timedelta(days=1)
            return max(now, next_t.timestamp(), st.get('scheduled_attempt', 0) + 1800 if st.get('error') else 0)
        return max(now, st.get('last_ts', 0) + max(1, int(m.get('interval_minutes') or 30)) * 60)

    def tick(self):
        now = time.time()
        for m in store.monitors():
            st = store.state().get('items', {}).get(m['id'], {})
            if self._due(m, st, now):
                self.submit(m, manual=False)
        import push_plans
        push_plans.tick(self,now)

    def submit(self, m, manual=True):
        mid = m['id']
        with self.lock:
            if mid in self.running:
                return False
            self.running[mid] = True
        threading.Thread(target=self._worker, args=(dict(m), manual), daemon=True).start()
        return True

    def _worker(self, m, manual):
        try:
            with self.slots:
                self._run(m, manual)
        finally:
            with self.lock:
                self.running.pop(m['id'], None)

    def check(self, m, manual=True):
        """Synchronous entry point for CLI and tests."""
        with self.lock:
            if m['id'] in self.running:
                return
            self.running[m['id']] = True
        self._worker(m, manual)

    def _run(self, m, manual):
        mid = m['id']
        old = store.state().get('items', {}).get(mid, {})
        now = time.time()
        daily_digest = m.get('notification_mode') == 'daily_digest' and not m.get('notification_plan')
        today = datetime.datetime.fromtimestamp(now, CST).date().isoformat()
        attempt = {'last_ts': now, 'last_run': store.now_str(), 'title': m.get('title')}
        if not manual:
            attempt['scheduled_attempt'] = now
        try:
            snap = engine.run_check(m)
        except Exception as e:
            # Keep the last successful snapshot intact on any failure.
            msg = str(e) if isinstance(e, engine.MonitorError) else '读取失败，请稍后重试或检查配置'
            failures = old.get('failures', 0) + 1
            failed = dict(old, **attempt)
            failed.update(error=msg, ok=False, failures=failures)
            if store.get_monitor(mid) != m:
                return
            store.update_item_state(mid, failed)
            store.log('检查失败 [%s]: %s' % (m.get('title'), msg))
            if daily_digest:
                if not manual and old.get('daily_notification_day') != today:
                    failed['daily_notification_day'] = today
                    store.update_item_state(mid, failed)
                    self._event(m, 'digest', '每日摘要', [('读取状态', '', msg)], m.get('url'))
            elif (isinstance(e, engine.SessionExpired) and old.get('error') != msg) or failures == 3:
                self._event(m, 'connection', '需要处理', [('连接状态', '', msg)], m.get('url'))
            return
        if store.get_monitor(mid) != m:
            return
        cookie_update = snap.pop('_cookie_update', None)
        if cookie_update:
            m = dict(m, cookie=cookie_update)
            store.upsert_monitor(m)
        first = not old.get('fingerprint') or old.get('source') != snap.get('source') or old.get('baseline_version') != snap.get('baseline_version')
        changes = []
        if not first:
            changes, _, removed = engine.diff_snapshots(old, snap)
            changes += [(k, str(old['fields'][k]), '已移除') for k in removed if k != '分篇']
            if m['kind'] == 'web' and not m.get('fields') and old.get('text_fingerprint') != snap.get('text_fingerprint') and not changes:
                changes = [('网页正文', '', '页面内容发生变化')]
            if snap.get('source') in ('xjtu_oa', 'openreview_notifications'):
                seen = set(old.get('seen_ids', []))
                changes = [('OpenReview 新通知' if snap.get('source')=='openreview_notifications' else '新增公告', '', i['title']) for i in snap.get('items', []) if i['id'] not in seen]
            elif snap.get('source') == 'coremail':
                changes = []
                if snap.get('inbox_total',0) > old.get('inbox_total',0) or snap.get('unread',0) > old.get('unread',0):
                    changes = [('未读邮件', str(old.get('unread',0)), str(snap.get('unread',0))),
                               ('收件箱邮件', str(old.get('inbox_total',0)), str(snap.get('inbox_total',0)))]
            elif snap.get('source') == 'openreview':
                names = {p['id']:p['title'] for p in snap.get('papers',[])}
                changes = [('稿件更新', '', names.get(c[0],c[0])) for c in changes]
            elif m['kind'] in ('google_scholar', 'citations'):

                # A corrected/decreased citation total or h-index change is not a new citation.
                before = int(old.get('total', 0))
                after = int(snap.get('total', 0))
                changes = [('总被引', str(before), str(after))] if after > before else []
        if snap.get('source') in ('xjtu_oa', 'openreview_notifications'):
            snap['seen_ids'] = sorted(set(old.get('seen_ids', [])) | {i['id'] for i in snap.get('items', [])})
        new = dict(snap, **attempt)
        new.update(ok=True, error='', failures=0, last_success=now, last_changed=old.get('last_changed'))
        for key in ('scheduled_day', 'scheduled_attempt', 'daily_notification_day', 'digest_total'):
            if key in old:
                new[key] = old[key]
        if not manual:
            new['scheduled_attempt'] = now
            new['scheduled_day'] = datetime.datetime.fromtimestamp(now, CST).date().isoformat()
        if changes:
            new['last_changed'] = now
        send_digest = daily_digest and not manual and old.get('daily_notification_day') != today
        if send_digest:
            new['daily_notification_day'] = today
            if snap.get('source') == 'google_scholar':
                new['digest_total'] = snap.get('total')
        store.update_item_state(mid, new)
        if send_digest:
            self._event(m, 'digest', '每日摘要', self._digest(snap, old), snap.get('url'))
        elif changes:
            self._event(m, 'change', '有新变化', changes, snap.get('url'), notify=not daily_digest)
        store.log('检查完成 [%s]: %s' % (m.get('title'), '建立基线' if first else ('有更新' if changes else '无变化')))

    def _digest(self, snap, old):
        if snap.get('source') == 'google_scholar':
            fields = snap.get('fields', {})
            total = snap.get('total', 0)
            delta = total - old.get('digest_total', old.get('total', total))
            return [('总被引', '', str(total) + ('（较上次摘要 %+d）' % delta)),
                    ('h 指数 / i10 指数', '', fields.get('h 指数', '—') + ' / ' + fields.get('i10 指数', '—'))]
        return [('最新公告 %d' % (i+1), '', item.get('published','') + ' · ' + item['title'])
                for i,item in enumerate(snap.get('items', [])[:3])]

    def _event(self, m, kind, label, changes, url, notify=True):
        event = {'event_id': uuid.uuid4().hex, 'id': m['id'], 'title': m.get('title'), 'kind': kind,
                 'time': store.now_str(), 'ts': time.time(), 'changes': changes[:20], 'url': url, 'read': False}
        store.append_event(event)
        lines = ['%s：%s%s' % (k, (str(ov)[:80]+' → ') if ov else '', str(nv)[:150]) for k, ov, nv in changes[:3]]
        if kind in ('change','connection') and m.get('notification_plan',{}).get('mode') in ('interval','times'):notify=False
        if notify and m.get('notifications', True):
            ok = notifier.notify('Watchtower · ' + label, '\n'.join(lines), subtitle=m.get('title'), url=url)
            store.save_settings({'last_notification': {'time': store.now_str(), 'sent': bool(ok)}})


scheduler = Scheduler()
