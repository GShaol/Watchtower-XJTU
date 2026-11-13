# Build / 构建

Use an Apple Silicon Mac, Python 3.9+ and Xcode Command Line Tools (`xcode-select --install`).
The build supports arm64 only and links macOS system frameworks.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/privacy_check.py .
.venv/bin/python native/build_desktop.py --build-dir /private/tmp/watchtower-community-build
.venv/bin/python scripts/verify_clean.py '/private/tmp/watchtower-community-build/Watchtower Community.app'
mkdir -p dist
ditto -c -k --norsrc --noextattr --noqtn --keepParent '/private/tmp/watchtower-community-build/Watchtower Community.app' 'dist/Watchtower-Community-0.1.0-macOS-arm64.zip'
.venv/bin/python scripts/privacy_check.py dist/Watchtower-Community-0.1.0-macOS-arm64.zip
```

The builder only replaces its own generated `Watchtower Community.app` inside
the selected build directory. It never installs or replaces another application.
Do not choose an unrelated folder containing an app of the same name.

The app, notification helper and Keychain helper receive local ad-hoc signatures.
No Developer ID, notarization or provisioning profile is included. A maintainer
may sign/notarize releases with their own credentials outside the repository.
Never commit signing keys. Keep the Python/PyInstaller dependency notices bundled.

`verify_clean.py` runs the packaged backend in a temporary runtime directory on
an unused loopback port. It does not log in, request notification permission or
change existing app data. It checks first-run defaults, removed APIs and access
controls, then stops its own process and removes temporary data.

For source-level UI work, run the backend with explicit isolated paths:

```sh
WATCHTOWER_COMMUNITY_HOME=/private/tmp/watchtower-community-dev \
WATCHTOWER_COMMUNITY_RESOURCES="$PWD" \
python3 native/desktop_backend.py --port 18767
```

The source-only backend has no native session bridge or built Keychain helper;
authenticated browser checks require the packaged native app. Do not interpret
source-only login failures as site compatibility tests.

构建脚本不需要个人版安装目录，也不会安装新应用或修改已有账号。运行隔离验收
不需要联网账号；真实网站兼容性需要使用者在自己的设备上单独验证。
