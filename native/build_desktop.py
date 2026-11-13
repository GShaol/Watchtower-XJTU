"""Build a credential-free, self-contained arm64 macOS application."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


def run(*args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-dir', default='/private/tmp/watchtower-community-build')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    build = Path(args.build_dir)
    build.mkdir(parents=True, exist_ok=True)
    app = build/'Watchtower Community.app'
    if app.exists():
        shutil.rmtree(app)
    contents = app/'Contents'
    resources = contents/'Resources'
    (contents/'MacOS').mkdir(parents=True)
    resources.mkdir()
    run(sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', '--onedir',
        '--name', 'watchtower-core', '--target-architecture', 'arm64',
        '--paths', source/'app', '--hidden-import', '_scproxy',
        '--distpath', build/'frozen', '--workpath', build/'work', '--specpath', build,
        source/'native/desktop_backend.py', env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',
                                                  PYINSTALLER_CONFIG_DIR=str(build/'pyinstaller-cache')))
    shutil.copytree(build/'frozen/watchtower-core', resources/'backend', symlinks=True)
    shutil.copytree(source/'web', resources/'web', ignore=shutil.ignore_patterns('*.png','__pycache__'))
    shutil.copy2(source/'assets/AppIcon.icns', resources/'AppIcon.icns')
    helper = resources/'native/Watchtower Notifications.app'
    (helper/'Contents/MacOS').mkdir(parents=True)
    (helper/'Contents/Resources').mkdir()
    shutil.copy2(source/'assets/AppIcon.icns',helper/'Contents/Resources/AppIcon.icns')
    helper_info=dict(CFBundleIdentifier='org.watchtower.community.notifications',CFBundleName='Watchtower Community Notifications',CFBundleExecutable='WatchtowerNotify',CFBundlePackageType='APPL',CFBundleShortVersionString='0.1.0',CFBundleVersion='1',CFBundleIconFile='AppIcon',LSUIElement=True,NSPrincipalClass='NSApplication',LSMinimumSystemVersion='12.0')
    (helper/'Contents/Info.plist').write_bytes(plistlib.dumps(helper_info))
    run('/usr/bin/clang','-fobjc-arc','-framework','Cocoa','-framework','UserNotifications',source/'native/NotificationHelper.m','-o',helper/'Contents/MacOS/WatchtowerNotify')
    run('/usr/bin/clang','-fobjc-arc','-framework','Foundation','-framework','Security',source/'native/Credentials.m','-o',resources/'native/WatchtowerCredentials')
    run('/usr/bin/codesign','--force','--sign','-',resources/'native/WatchtowerCredentials')
    for name in ('README.md','README.zh-CN.md','LICENSE','THIRD_PARTY_NOTICES.md'):
        shutil.copy2(source/name,resources/name)
    shutil.copytree(source/'docs',resources/'docs')
    # Use the helper's embedded notification identity, preserving existing notification permission.
    info = dict(CFBundleName='Watchtower Community', CFBundleDisplayName='Watchtower Community',
                CFBundleIdentifier='org.watchtower.community.app', CFBundleExecutable='Watchtower',
                CFBundlePackageType='APPL', CFBundleIconFile='AppIcon',
                CFBundleShortVersionString='0.1.0', CFBundleVersion='1',
                LSMinimumSystemVersion='12.0', LSUIElement=False,
                NSHighResolutionCapable=True, NSPrincipalClass='NSApplication',
                NSAppTransportSecurity={'NSAllowsLocalNetworking':True})
    (contents/'Info.plist').write_bytes(plistlib.dumps(info))
    (contents/'PkgInfo').write_bytes(b'APPL????')
    swift_flags = []
    # Some CLT installations contain both legacy and current definitions of this
    # same module. Hide only the redundant map in this build's virtual filesystem;
    # never alter the user's SDK or compiler installation.
    legacy = Path('/Library/Developer/CommandLineTools/usr/include/swift/module.modulemap')
    current = legacy.with_name('bridging.modulemap')
    if legacy.exists() and current.exists() and all('module SwiftBridging' in p.read_text() for p in (legacy,current)):
        empty = build/'empty.modulemap'
        empty.write_text('// The current bridging.modulemap supplies this module.\n')
        overlay = build/'swift-overlay.json'
        overlay.write_text(json.dumps({'version':0,'roots':[{'type':'file','name':str(legacy),'external-contents':str(empty)}]}))
        swift_flags = ['-vfsoverlay',overlay]
    shutil.copy2(source/'native/WatchtowerDesktop.swift',build/'main.swift')
    run('/usr/bin/xcrun', 'swiftc', *swift_flags, '-O', '-target', 'arm64-apple-macos12.0', '-module-cache-path', build/'swift-cache',
        '-framework', 'AppKit', '-framework', 'WebKit', build/'main.swift', source/'native/SiteSessions.swift',
        '-o', contents/'MacOS/Watchtower', env=dict(os.environ,CLANG_MODULE_CACHE_PATH=str(build/'clang-cache')))
    # Remove only generated bundle metadata before ad-hoc signing our own output.
    run('/usr/bin/xattr', '-cr', app)
    run('/usr/bin/codesign', '--force', '--sign', '-', helper)
    run('/usr/bin/codesign', '--force', '--deep', '--sign', '-', app)
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', app)
    run(resources/'backend/watchtower-core', '--self-test',
        env=dict(os.environ, WATCHTOWER_COMMUNITY_HOME=str(build/'smoke-data'), WATCHTOWER_COMMUNITY_RESOURCES=str(resources)))
    print('Built:', app)


if __name__ == '__main__':
    main()
