import AppKit
import WebKit
import Darwin

final class WatchtowerDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate,
                                WKNavigationDelegate, WKUIDelegate, NSMenuDelegate {
    private let home = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Watchtower Community")
    private let resources = Bundle.main.resourceURL!
    private let port = 18767
    private var dashboardURL: URL { URL(string: "http://127.0.0.1:\(port)/")! }
    private var background: Bool { CommandLine.arguments.contains("--background") }
    private var statusItem: NSStatusItem!
    private var window: NSWindow!
    private var webView: WKWebView!
    private var awakeHelper: Process?
    private var worker: Process?
    private var output: FileHandle?
    private var heartbeat: Timer?
    private var cachedState: [String: Any] = [:]
    private var dashboardLoaded = false
    private var stopping = false
    private var failures = 0
    private var lockFD: Int32 = -1
    private var polling = false
    private var tick = 0
    private var pendingSettings = false
    private let sessionToken = UUID().uuidString + UUID().uuidString
    private var siteSessions: [String: SiteSession] = [:]
    private var sessionTimer: Timer?
    private var sessionPolling = false
    private let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 4
        config.connectionProxyDictionary = [:]
        return URLSession(configuration: config)
    }()

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            try FileManager.default.createDirectory(at: home.appendingPathComponent("data"), withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: home.appendingPathComponent("logs"), withIntermediateDirectories: true)
        } catch { showError("无法访问本机配置，请检查文件夹权限。"); NSApp.terminate(nil); return }
        lockFD = open(home.appendingPathComponent("data/desktop.lock").path, O_CREAT | O_RDWR, 0o600)
        guard lockFD >= 0, flock(lockFD, LOCK_EX | LOCK_NB) == 0 else {
            if !background {
                DistributedNotificationCenter.default().postNotificationName(Notification.Name("org.watchtower.community.show"), object: nil, userInfo: nil, deliverImmediately: true)
            }
            NSApp.terminate(nil)
            return
        }
        DistributedNotificationCenter.default().addObserver(self, selector: #selector(showWindow), name: Notification.Name("org.watchtower.community.show"), object: nil)
        NSApp.appearance = NSAppearance(named: .aqua)
        let registration=Process()
        registration.executableURL=URL(fileURLWithPath:"/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister")
        registration.arguments=["-f",resources.appendingPathComponent("native/Watchtower Notifications.app").path]
        registration.standardOutput=FileHandle.nullDevice;registration.standardError=FileHandle.nullDevice
        try? registration.run()
        buildApplicationMenu()
        buildStatusItem()
        buildWindow()
        startWorker()
        heartbeat = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            self.tick += 1
            if !self.dashboardLoaded || self.tick % 15 == 0 { self.pollState() }
        }
        sessionTimer = Timer.scheduledTimer(withTimeInterval: 0.4, repeats: true) { [weak self] _ in self?.pollSessions() }
        pollState()
        if !background { showWindow() }
    }

    private func buildApplicationMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于 Watchtower", action: #selector(about), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "隐藏 Watchtower", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "退出 Watchtower", action: #selector(quit), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)
        let editItem = NSMenuItem()
        editItem.title = "编辑"
        let editMenu = NSMenu(title: "编辑")
        for (title, action, key) in [("撤销", "undo:", "z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        editItem.submenu = editMenu
        main.addItem(editItem)
        let viewItem = NSMenuItem()
        viewItem.title = "窗口"
        let viewMenu = NSMenu(title: "窗口")
        viewMenu.addItem(withTitle: "打开 Watchtower", action: #selector(showWindow), keyEquivalent: "o")
        viewMenu.addItem(withTitle: "刷新面板", action: #selector(reload), keyEquivalent: "r")
        viewMenu.addItem(withTitle: "关闭窗口", action: #selector(closeWindow), keyEquivalent: "w")
        viewItem.submenu = viewMenu
        main.addItem(viewItem)
        NSApp.mainMenu = main
    }

    private func buildStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem.button {
            let icon = NSImage(contentsOf: resources.appendingPathComponent("AppIcon.icns"))
                ?? NSImage(systemSymbolName: "eye", accessibilityDescription: "Watchtower")
            icon?.size = NSSize(width: 19, height: 19)
            button.image = icon
            button.title = ""
            button.toolTip = "Watchtower · 后台监控中"
        }
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu
        updateMenu()
    }

    func menuWillOpen(_ menu: NSMenu) { updateMenu(); pollState() }

    private func add(_ title: String, action: Selector?, to menu: NSMenu, key: String = "") {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        menu.addItem(item)
    }

    private func updateMenu() {
        guard let menu = statusItem?.menu else { return }
        menu.removeAllItems()
        add("打开 Watchtower", action: #selector(showWindow), to: menu, key: "o")
        menu.addItem(.separator())
        let monitors = cachedState["monitors"] as? [[String: Any]] ?? []
        let events = cachedState["recent"] as? [[String: Any]] ?? []
        let enabled = monitors.filter { ($0["enabled"] as? Bool ?? true) && !($0["setup_required"] as? Bool ?? false) }.count
        let unread = events.filter { !($0["read"] as? Bool ?? false) }.count
        add(cachedState.isEmpty ? "正在连接监控…" : "\(enabled) 项监控 · \(unread) 条未读动态", action: nil, to: menu)
        add("立即检查全部", action: #selector(checkAll), to: menu)
        add("偏好设置…", action: #selector(showSettings), to: menu)
        menu.addItem(.separator())
        add("关闭窗口后继续监控", action: nil, to: menu)
        add("退出 Watchtower", action: #selector(quit), to: menu, key: "q")
        // Never put a bell, badge, count or warning next to the menu-bar icon.
        statusItem.button?.title = ""
    }

    private func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1180, height: 780),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Watchtower Community"
        window.minSize = NSSize(width: 640, height: 520)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.center()
        let configuration = WKWebViewConfiguration()
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.autoresizingMask = [.width, .height]
        window.contentView = webView
        webView.loadHTMLString("<html><body style='background:#f7f7fb;color:#6555aa;font:18px -apple-system;display:grid;place-items:center;height:90vh'>正在准备你的监控…</body></html>", baseURL: nil)
    }

    private func startWorker() {
        guard !stopping, worker?.isRunning != true else { return }
        let executable = resources.appendingPathComponent("backend/watchtower-core")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            showError("应用文件不完整，请重新安装 Watchtower。"); return
        }
        let process = Process()
        process.executableURL = executable
        process.arguments = ["--port", String(port), "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
        var environment = ProcessInfo.processInfo.environment
        environment["WATCHTOWER_COMMUNITY_HOME"] = home.path
        environment["WATCHTOWER_COMMUNITY_RESOURCES"] = resources.path
        environment["PYTHONNOUSERSITE"] = "1"
        environment["WATCHTOWER_COMMUNITY_SESSION_TOKEN"] = sessionToken
        process.environment = environment
        process.currentDirectoryURL = home
        let log = home.appendingPathComponent("logs/desktop.log")
        if !FileManager.default.fileExists(atPath: log.path) { FileManager.default.createFile(atPath: log.path, contents: nil, attributes: [.posixPermissions: 0o600]) }
        output = try? FileHandle(forWritingTo: log)
        output?.seekToEndOfFile()
        process.standardOutput = output ?? FileHandle.nullDevice
        process.standardError = output ?? FileHandle.nullDevice
        process.standardInput = FileHandle.nullDevice
        process.terminationHandler = { [weak self] terminated in
            DispatchQueue.main.async {
                guard let self = self, !self.stopping else { return }
                self.worker = nil
                self.failures += 1
                let delay = min(60.0, pow(2.0, Double(min(self.failures, 5))))
                self.statusItem.button?.toolTip = "Watchtower · 正在恢复后台监控"
                DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in self?.startWorker() }
            }
        }
        do { try process.run(); worker = process }
        catch { showError("暂时无法启动监控，请重新打开 Watchtower。") }
    }

    private func pollSessions() {
        guard !sessionPolling, !stopping else { return };sessionPolling = true
        var request = URLRequest(url:dashboardURL.appendingPathComponent("api/internal/sessions"))
        request.setValue(sessionToken,forHTTPHeaderField:"X-Watchtower-Session")
        session.dataTask(with:request) { [weak self] data, response, _ in
            let body = data.flatMap { try? JSONSerialization.jsonObject(with:$0) as? [String:Any] }
            DispatchQueue.main.async {
                guard let self = self else { return };self.sessionPolling = false
                guard (response as? HTTPURLResponse)?.statusCode == 200, let jobs = body?["jobs"] as? [[String:Any]] else { return }
                for job in jobs {
                    guard let mid = job["monitor_id"] as? String, let jid = job["job_id"] as? String else { continue }
                    let site = self.siteSessions[mid] ?? SiteSession(id:mid,title:job["title"] as? String ?? "网站") { [weak self] id in
                        guard let self = self else { return }
                        var check = URLRequest(url:self.dashboardURL.appendingPathComponent("api/check"))
                        check.httpMethod="POST";check.setValue("application/json",forHTTPHeaderField:"Content-Type")
                        check.httpBody=try? JSONSerialization.data(withJSONObject:["id":id])
                        self.session.dataTask(with:check).resume()
                    }
                    self.siteSessions[mid] = site
                    site.run(job) { [weak self] result in
                        guard let self = self else { return }
                        var result = result;result["job_id"] = jid
                        var reply = URLRequest(url:self.dashboardURL.appendingPathComponent("api/internal/session-result"))
                        reply.httpMethod="POST";reply.setValue("application/json",forHTTPHeaderField:"Content-Type")
                        reply.setValue(self.sessionToken,forHTTPHeaderField:"X-Watchtower-Session")
                        reply.httpBody=try? JSONSerialization.data(withJSONObject:result)
                        self.session.dataTask(with:reply).resume()
                    }
                }
            }
        }.resume()
    }

    private func pollState() {
        guard !polling, !stopping else { return }
        polling = true
        session.dataTask(with: dashboardURL.appendingPathComponent("api/state")) { [weak self] data, response, _ in
            let state = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.polling = false
                guard (response as? HTTPURLResponse)?.statusCode == 200,
                      let state = state, state["monitors"] is [[String: Any]] else { return }
                self.failures = 0
                self.cachedState = state
                let settings=state["settings"] as? [String:Any] ?? [:]
                
                self.updateAwake(settings["keep_awake"] as? Bool ?? false)
                self.statusItem.button?.toolTip = "Watchtower · 后台监控中"
                if !self.dashboardLoaded {
                    self.dashboardLoaded = true
                    self.webView.load(URLRequest(url: self.dashboardURL))
                }
            }
        }.resume()
    }

    private func updateAwake(_ enabled: Bool) {
        if enabled {
            guard awakeHelper?.isRunning != true else { return }
            let process=Process();process.executableURL=URL(fileURLWithPath:"/usr/bin/caffeinate")
            process.arguments=["-i","-w",String(ProcessInfo.processInfo.processIdentifier)]
            process.standardOutput=FileHandle.nullDevice;process.standardError=FileHandle.nullDevice
            do { try process.run();awakeHelper=process } catch { awakeHelper=nil }
        } else {
            if awakeHelper?.isRunning == true { awakeHelper?.terminate() }
            awakeHelper=nil
        }
    }

    @objc func showWindow() {
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        pollState()
    }
    @objc private func closeWindow() { window.performClose(nil) }
    @objc private func reload() { webView.reload() }
    @objc private func showSettings() {
        pendingSettings = true
        showWindow()
        if dashboardLoaded {
            webView.evaluateJavaScript("document.getElementById('settingsTop')?.click()")
            pendingSettings = false
        }
    }
    @objc private func checkAll() {
        var request = URLRequest(url: dashboardURL.appendingPathComponent("api/check"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data("{}".utf8)
        session.dataTask(with: request).resume()
    }
    @objc private func about() {
        NSApp.orderFrontStandardAboutPanel(options: [.applicationName: "Watchtower", .applicationVersion: "0.1.0", .credits: NSAttributedString(string: "Local research monitoring.\n关闭窗口后继续监控。")])
        NSApp.activate(ignoringOtherApps: true)
    }
    @objc private func quit() { NSApp.terminate(nil) }
    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Watchtower"
        alert.informativeText = message
        alert.addButton(withTitle: "知道了")
        alert.runModal()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { showWindow(); return false }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        stopping = true
        updateAwake(false)
        heartbeat?.invalidate()
        sessionTimer?.invalidate()
        guard let process = worker, process.isRunning else { return .terminateNow }
        process.terminate()
        DispatchQueue.global().async {
            for _ in 0..<40 {
                if !process.isRunning { break }
                usleep(100_000)
            }
            if process.isRunning { kill(process.processIdentifier, SIGKILL) }
            DispatchQueue.main.async { NSApp.reply(toApplicationShouldTerminate: true) }
        }
        return .terminateLater
    }
    func applicationWillTerminate(_ notification: Notification) {
        DistributedNotificationCenter.default().removeObserver(self)
        if lockFD >= 0 { close(lockFD) }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if pendingSettings, webView.url?.host == "127.0.0.1" {
            pendingSettings = false
            webView.evaluateJavaScript("document.getElementById('settingsTop')?.click()")
        }
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { dashboardLoaded = false }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" || (url.host == "127.0.0.1" && url.port == port && url.scheme == "http") { decisionHandler(.allow); return }
        if url.scheme == "https" || url.scheme == "http" { NSWorkspace.shared.open(url) }
        decisionHandler(.cancel)
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url, ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        return nil
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = "Watchtower"; alert.informativeText = message; alert.addButton(withTitle: "知道了")
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = "Watchtower"; alert.informativeText = message
        alert.addButton(withTitle: "确定"); alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = WatchtowerDelegate()
app.delegate = delegate
app.run()
