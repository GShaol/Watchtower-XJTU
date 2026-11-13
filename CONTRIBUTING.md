# Contributing / 参与开发

Keep the public scope limited to the nine documented modules. Changes must not
send mail, submit manuscripts, change read flags, or import another app's data.
Use synthetic fixtures and mock website requests in tests. Do not use real
researcher names, IDs, inbox headers or manuscript numbers in fixtures.

Run `python3 -m unittest discover -s tests -v` and
`python3 scripts/privacy_check.py .` before opening a PR. UI changes should retain
keyboard access, narrow-window support and scroll position during polling.
 
请使用虚构测试数据；提交前执行测试和隐私检查。不要上传真实账号截图。
If you add a dependency or asset, document its source and redistribution license.
