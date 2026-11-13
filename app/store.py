# -*- coding: utf-8 -*-
"""配置与状态持久化。"""
import json
import os
import tempfile
import threading
from datetime import datetime, timezone, timedelta

ROOT = os.environ.get("WATCHTOWER_COMMUNITY_HOME") or os.path.expanduser("~/Library/Application Support/Watchtower Community")
# Read-only resources live in the app bundle; private data stays outside upgrades.
RESOURCES = os.environ.get("WATCHTOWER_COMMUNITY_RESOURCES") or ROOT
DATA_DIR = os.path.join(ROOT, "data")
LOG_DIR = os.path.join(ROOT, "logs")
CONFIG = os.path.join(DATA_DIR, "config.json")
STATE = os.path.join(DATA_DIR, "state.json")
SETTINGS = os.path.join(DATA_DIR, "settings.json")

_lock = threading.Lock()

DEFAULT_SETTINGS = {
    "port": 18767,
    "tick_seconds": 30,
    "notify_sound": "Glass",
    "alert_popup": False,
}


def now_str():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, obj, private=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    if private:
        os.chmod(path, 0o600)


def settings():
    s = dict(DEFAULT_SETTINGS)
    s.update(_read(SETTINGS, {}))
    return s


def save_settings(patch):
    with _lock:
        s = settings()
        s.update(patch or {})
        _write(SETTINGS, s)
        return s


def monitors():
    return _read(CONFIG, {"monitors": []}).get("monitors", [])


def save_monitors(items):
    with _lock:
        _write(CONFIG, {"monitors": items}, private=True)


def get_monitor(mid):
    for m in monitors():
        if m.get("id") == mid:
            return m
    return None


def upsert_monitor(m):
    with _lock:
        items = monitors()
        for i, old in enumerate(items):
            if old.get("id") == m.get("id"):
                items[i] = m
                break
        else:
            items.append(m)
        _write(CONFIG, {"monitors": items}, private=True)


def delete_monitor(mid):
    with _lock:
        items = [m for m in monitors() if m.get("id") != mid]
        _write(CONFIG, {"monitors": items}, private=True)
        st = state()
        st.get("items", {}).pop(mid, None)
        _write(STATE, st)


def state():
    return _read(STATE, {"items": {}, "last_run": ""})


def save_state(st):
    with _lock:
        _write(STATE, st)


def update_item_state(mid, item):
    with _lock:
        st = state()
        st.setdefault("items", {})[mid] = item
        st["last_run"] = now_str()
        _write(STATE, st)


def append_event(event):
    with _lock:
        st = state()
        st["recent"] = ([event] + st.get("recent", []))[:200]
        _write(STATE, st, private=True)


def mark_read():
    with _lock:
        st = state()
        for event in st.get("recent", []):
            event["read"] = True
        _write(STATE, st, private=True)


def log(msg):
    line = "[%s] %s" % (now_str(), msg)
    print(line, flush=True)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "watchtower.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def update_push_state(mid,value):
    with _lock:
        st=state();st.setdefault('push_plans',{})[mid]=value;_write(STATE,st)
