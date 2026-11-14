# Watchtower Community

一款本地 macOS 应用，可在后台监控研究网站，并在有更新时发送 macOS 通知。

## 监控内容

- Google Scholar 引用次数、h 指数和 i10 指数。
- 西安交通大学（XJTU）学生邮箱的未读邮件数量及近期邮件标题。
- 西安交通大学（XJTU）网上办事大厅的公开通知。
- OpenReview 账户通知。
- IEEE TIFS、TDSC、ToN、TMC 和 JSAC 的 ScholarOne 稿件状态。

## 开始使用

1. 使用搭载 Apple 芯片、运行 macOS 12 或更高版本的 Mac。
2. 从上游发布页面（如有）安装 **Watchtower Community.app**；也可以使用 Python 3.9 或更高版本及 Xcode 命令行工具从源代码构建。
3. 打开应用，并使用你自己的账户或 Google Scholar 个人主页链接，连接所需模块。全部九个模块默认关闭。
4. 设置监控和通知计划，然后保持应用运行。关闭窗口后，应用仍会在菜单栏运行；退出应用则会停止检查。

从源代码构建的说明请参阅构建指南：[构建指南](docs/BUILD.md)

## 本地存储

凭据保存在 macOS 钥匙串中。设置和监控快照保存在你的 Mac 上，后端服务仅监听本地回环接口。网站集成能否使用，取决于各服务的登录、验证及可用性要求。

有关设置详情和兼容性限制，请阅读完整文档。

[完整 README](README.md) · [隐私说明](docs/PRIVACY.md)

本项目采用 MIT 许可证。[许可证](LICENSE)
