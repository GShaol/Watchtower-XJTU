"""Private background service embedded in Watchtower.app, with no GUI runtime."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

import adapters
import engine
import integrations
import notifier
import scheduler
import store
import webserver


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18767)
    parser.add_argument('--parent-pid', type=int)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        # Exercise modules with native extensions required for HTTPS and macOS proxies.
        import ssl
        import _scproxy
        import urllib.request
        assert callable(_scproxy._get_proxy_settings)
        print(json.dumps({'app':'watchtower', 'frozen':bool(getattr(sys,'frozen',False)),
                          'version':'0.1.0', 'https':bool(ssl.create_default_context()),
                          'resources':os.path.isfile(webserver.DASHBOARD)}))
        return 0
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    import community
    community.initialize()
    server = webserver.serve(args.port)
    scheduler.scheduler.start()
    store.log('Watchtower Community started')
    try:
        while not stopped.wait(1):
            if args.parent_pid and os.getppid() != args.parent_pid:
                break
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
