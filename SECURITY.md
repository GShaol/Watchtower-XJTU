# Security / 安全

Never put accounts, passwords, cookies, Google Scholar profile IDs, manuscript
details, screenshots of real accounts, or API tokens in issues or pull requests.
Use invented examples and redact logs before sharing. Do not attach browser
profiles, a runtime data folder, HAR files or Keychain exports.

请勿在 Issue、PR 或截图中公开账号密码、Cookie、私人主页 ID、稿件信息和令牌。
复现问题请使用虚构数据；不要上传运行数据目录、浏览器会话或钥匙串导出。

For a suspected credential leak, revoke the affected credential first. For a
vulnerability, use the repository's private vulnerability reporting if enabled;
do not publish an exploit containing account data. This project has no hosted
account database or credential recovery service.
