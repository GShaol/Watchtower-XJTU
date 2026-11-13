# Privacy / 隐私

## Distribution versus runtime

The public tree contains selected source code, a generic icon, documentation and
synthetic tests only. The build creates native helpers from source. No prebuilt
personal app, browser profile, Keychain export or runtime state is a build input.

After a user connects an account, that user's computer naturally contains private
configuration, results and authentication state. These must never be included in
an issue, repository or application ZIP.

## Independent identity

- Main bundle: `org.watchtower.community.app`
- Notification helper: `org.watchtower.community.notifications`
- Keychain services: `org.watchtower.community.connection.*` and
  `org.watchtower.community.scholarone.*`
- Runtime: `~/Library/Application Support/Watchtower Community/`
- Local API: `127.0.0.1:18767`
- Website storage: WebKit store belonging to the Community application's identity.

There is no migration from the private application, no ordinary browser profile
access and no automatic startup agent. The developer-only
`WATCHTOWER_COMMUNITY_HOME` environment variable permits isolated testing.

Passwords, refresh tokens and renewable mailbox sessions go through a native
Keychain helper over stdin/stdout, not shell arguments. Public state includes
only whether credentials are saved. Website collection tasks use an in-memory
bridge protected by a fresh per-process token. Requests go to the configured
official website. Google and journal sign-in pages may contact their own identity
providers. The app itself has no analytics endpoint or mail delivery service.

Read-only refers to research/mail actions. Signing in, refreshing authentication
and fetching data necessarily make requests to the service. The app does not
submit manuscripts, publish messages, mark messages read or alter manuscript state.

Only loopback clients are accepted, with Host and Origin checks. The dashboard
is not intended as a hardened multi-user web service: another process running
as the same macOS user may access ordinary loopback APIs. Do not expose the port
through a proxy, tunnel or network interface.

## Publication review

Run `scripts/privacy_check.py` on source **and** the final application ZIP.
Review screenshots, fixtures, license metadata and all archive entries manually.
The heuristic scanner does not prove absence of every possible kind of personal
information. The source tree intentionally contains no Git history; initialize
a new repository only after review, and choose the commit identity yourself.

分享版与个人版使用不同应用身份、运行目录和钥匙串命名。用户配置后的运行目录、
网页会话、缓存和日志仍属于该用户的私人资料，不可随应用分享。扫描并非绝对保证，
发布前应人工检查文档、截图、测试样例和压缩包内容。GitHub 仓库所有者和提交作者
由发布者自行决定，不属于应用内的脱敏范围。
