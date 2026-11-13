# Publish to GitHub / 上传 GitHub

This folder is the **repository root**. Upload its contents, not a parent folder
containing application archives, acceptance reports or unrelated personal files.

1. Review `README.md`, `README.zh-CN.md`, LICENSE, screenshot and release notes.
2. Run source tests, privacy scans and isolated packaged verification from BUILD.md.
3. Create a new GitHub repository, for example `watchtower-community`.
4. Upload this folder's contents, including `.github/` and `.gitignore`, or use
   Git from the repository root. There is intentionally no inherited `.git` history.
5. Choose the Git commit author identity yourself. Publishing from your personal
   GitHub account makes that repository ownership visible.
6. Put the **clean application ZIP**, SHA256 checksum and release notes in a
   GitHub Release. Do not commit binaries into the source tree or upload runtime data.
7. Enable secret scanning/push protection where available. Check pull requests
   and screenshots for private information before merging.

The workflow in `.github/workflows/checks.yml` runs offline source checks. The
manually triggered build workflow targets the `macos-15` Apple Silicon hosted
runner and uploads an artifact. It does not create a Release or require account
credentials. GitHub runner availability and Actions permissions depend on the
repository/account; see [GitHub runner documentation](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

## Release checklist

- [ ] Nine modules only; SMTP/Notion/extra modules absent.
- [ ] First run has nine disabled, unconnected templates; no real results.
- [ ] No accounts, profile IDs, manuscripts, tokens, cookies, local usernames,
      signing identities or private paths in tracked files or screenshots.
- [ ] Fresh source build succeeds; source scan and final ZIP scan pass.
- [ ] Isolated clean-runtime verification passes without website credentials.
- [ ] Notice states ad-hoc signing and lack of notarization.
- [ ] Live compatibility limitations, especially JSAC/EDAS and Google login, are explicit.
- [ ] Release archive matches the documented checksum.

中文：上传的是本文件所在目录的内容，不是外层总文件夹。应用 ZIP 作为 Release
附件发布，不要上传使用后的 data、logs、WebKit 会话、钥匙串导出和真实账号截图。
GitHub 账号归属及提交作者由你自行选择；程序包脱敏不会隐藏仓库所有者身份。
