# -*- coding: utf-8 -*-
"""macOS 通知：通知中心横幅 + 可选前台弹窗。"""
import json
import os
import subprocess
import sys
import threading

import store


def _as(s):
    return json.dumps(s, ensure_ascii=False)


def native_request(payload):
    helper=os.path.join(store.RESOURCES,"native","Watchtower Notifications.app","Contents","MacOS","WatchtowerNotify")
    if not os.path.isfile(helper):
        return {"provider":"native","submitted":False,"error":"原生通知组件尚未安装"}
    try:
        result=subprocess.run([helper],input=json.dumps(payload,ensure_ascii=False),capture_output=True,text=True,timeout=45)
        return json.loads(result.stdout)
    except Exception:
        return {"provider":"native","submitted":False,"error":"无法连接原生通知组件，请重试"}


def notification_status():
    return native_request({"action":"status"})


def notify(title, message, subtitle=None, url=None, sound=None, popup=None):
    cfg = store.settings()
    if sound is None:
        sound = cfg.get("notify_sound", "Glass")
    if popup is None:
        popup = bool(cfg.get("alert_popup", True))
    if sys.platform != "darwin":
        store.log("通知: %s —— %s" % (title, message))
        return False

    status = native_request({"action":"notify", "title":title[:120], "message":message[:600],
                             "subtitle":(subtitle or "")[:120], "url":url or "http://127.0.0.1:18767/", "sound":sound})
    delivered = bool(status.get("delivered"))
    store.save_settings({"notification_status":dict(status,time=store.now_str())})
    store.log("原生通知：%s / %s" % (status.get("authorization","unknown"), "已投递" if delivered else "未确认投递"))

    if not popup:
        return delivered

    body = message[:400] + (("\n" + subtitle) if subtitle else "")
    script = ["on run argv",
              "set theTitle to item 1 of argv",
              "set theBody to item 2 of argv"]
    buttons = 'buttons {"知道了"}'
    if url:
        script.append("set theUrl to item 3 of argv")
        buttons = 'buttons {"知道了", "打开页面"}'
    script.append('set r to display alert theTitle message theBody %s default button "知道了" giving up after 20' % buttons)
    if url:
        script.append('if button returned of r is "打开页面" then open location theUrl')
    script.append("end run")
    argv = ["osascript"]
    for line in script:
        argv += ["-e", line]
    argv += [title, body]
    if url:
        argv.append(url)

    def _popup():
        try:
            subprocess.run(argv, capture_output=True, timeout=26)
        except Exception as e:
            store.log("弹窗提醒失败: %s" % e)

    # 弹窗放到后台，避免阻塞调度线程
    threading.Thread(target=_popup, daemon=True).start()
    return delivered
