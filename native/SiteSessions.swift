import AppKit
import WebKit

// Independent from Safari/Edge profiles. Only an explicit Open job shows a window.
final class SiteSession: NSObject, WKNavigationDelegate, WKUIDelegate {
    let view: WKWebView
    let window: NSWindow
    let monitorID: String
    private let finish: (String) -> Void
    private var loadedAt = Date.distantPast
    private var navigationFailed = false
    private var tasks: [String: Timer] = [:]
    private var seeded = false
    private var loadingStarted = false

    init(id: String, title: String, finish: @escaping (String) -> Void) {
        monitorID = id; self.finish = finish
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.preferences.javaScriptCanOpenWindowsAutomatically = false
        view = WKWebView(frame: NSRect(x: 0, y: 0, width: 1080, height: 700), configuration: config)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1080, height: 752), styleMask: [.titled,.closable,.miniaturizable,.resizable], backing: .buffered, defer: false)
        super.init()
        window.title = "连接账号 · " + title
        window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 700, height: 500)
        window.center()
        let root = NSView(frame: NSRect(x: 0,y: 0,width: 1080,height: 752))
        let bar = NSView(frame: NSRect(x: 0,y: 700,width: 1080,height: 52))
        bar.autoresizingMask = [.width,.minYMargin]
        let hint = NSTextField(labelWithString: "在网站登录后点完成。日常检查会在后台进行。")
        hint.frame = NSRect(x: 18,y: 16,width: 670,height: 20)
        hint.textColor = .secondaryLabelColor
        let done = NSButton(title: "完成，检查连接", target: self, action: #selector(doneConnecting))
        done.bezelStyle = .rounded
        done.frame = NSRect(x: 900,y: 10,width: 164,height: 32)
        done.autoresizingMask = [.minXMargin]
        bar.addSubview(hint); bar.addSubview(done)
        view.autoresizingMask = [.width,.height]
        root.addSubview(view); root.addSubview(bar)
        window.contentView = root
        view.navigationDelegate = self;view.uiDelegate = self
    }

    @objc private func doneConnecting() {
        window.orderOut(nil)
        finish(monitorID)
    }

    func run(_ job: [String: Any], reply: @escaping ([String: Any]) -> Void) {
        guard let urlText = job["url"] as? String, let url = URL(string: urlText),
              ["https","http"].contains(url.scheme ?? ""), let host = url.host else {
            reply(["error":"连接网址无效"]); return
        }
        let operation = job["operation"] as? String ?? "evaluate"
        if operation == "reset" {
            seeded = true // Never re-import an old account after an explicit credential reset.
            let names: Set<String> = host == "stu.xjtu.edu.cn" ? ["Coremail","Coremail.sid"] : []
            let store=view.configuration.websiteDataStore.httpCookieStore
            store.getAllCookies { all in
                let group=DispatchGroup()
                for cookie in all where cookie.domain.trimmingCharacters(in:CharacterSet(charactersIn:".")) == host && names.contains(cookie.name) {
                    group.enter();store.delete(cookie) { group.leave() }
                }
                group.notify(queue:.main) { reply(["result":["reset":true]]) }
            }
            return
        }
        if operation == "cookies" {
            view.configuration.websiteDataStore.httpCookieStore.getAllCookies { all in
                let cookies = all.filter { cookie in
                    let domain = cookie.domain.trimmingCharacters(in: CharacterSet(charactersIn: "."))
                    return (host == domain || host.hasSuffix("."+domain)) && url.path.hasPrefix(cookie.path) && (!cookie.isSecure || url.scheme == "https") && (cookie.expiresDate == nil || cookie.expiresDate! > Date())
                }
                reply(["result":["cookie":cookies.map { $0.name+"="+$0.value }.joined(separator:"; ")]])
            }
            return
        }
        seed(job, host: host) { [weak self] in
            guard let self = self else { return }
            if operation == "open" {
                if host == "openreview.net" { self.load(URL(string:"https://openreview.net/login")!) }
                else if host == "scholar.google.com" {
                    var target=URLComponents(url:url,resolvingAgainstBaseURL:false)!
                    target.queryItems=target.queryItems?.filter { $0.name != "authuser" }
                    var signIn=URLComponents(string:"https://accounts.google.com/ServiceLogin")!
                    signIn.queryItems=[URLQueryItem(name:"continue",value:target.url!.absoluteString)]
                    self.load(signIn.url!)
                }
                else if !self.loadingStarted { self.load(url) }
                self.window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
                reply(["result":["opened":true]]);return
            }
            if self.window.isVisible && self.view.url?.host == "accounts.google.com" {
                reply(["error":"请先在应用内完成 Google 登录，再点击完成，检查连接","needs_login":true]);return
            }
            if !self.loadingStarted || (job["refresh"] as? Bool ?? true) { self.load(url) }
            let jobID = job["job_id"] as? String ?? UUID().uuidString
            let deadline = Date().addingTimeInterval(55)
            self.tasks[jobID] = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] timer in
                guard let self = self else { timer.invalidate();return }
                if Date() > deadline || self.navigationFailed {
                    timer.invalidate();self.tasks.removeValue(forKey:jobID)
                    reply(["error":"应用内网站暂时无法连接，请稍后检查或点击连接账号"]);return
                }
                guard !self.view.isLoading, Date().timeIntervalSince(self.loadedAt) > 1 else { return }
                timer.invalidate();self.tasks.removeValue(forKey:jobID)
                guard self.view.url?.host == host,
                      host != "mc.manuscriptcentral.com" || self.view.url?.path == url.path else {
                    reply(["error":"请点击连接账号，在应用内完成网站登录或验证","needs_login":true]);return
                }
                let script = job["expression"] as? String ?? "null"
                let complete: (Any?, Error?) -> Void = { value,error in
                    // Do not echo WebKit errors: they may contain submitted credential text.
                    if error != nil { reply(["error":"页面尚未就绪，请稍后重新检查或连接账号"]);return }
                    reply(["result":value ?? NSNull()])
                }
                if job["asynchronous"] as? Bool ?? false {
                    self.view.callAsyncJavaScript("return await ("+script+");", arguments: [:], in: nil, in: .page) { result in
                        switch result { case .success(let value):complete(value,nil);case .failure(let error):complete(nil,error) }
                    }
                } else { self.view.evaluateJavaScript(script, completionHandler: complete) }
            }
        }
    }

    private func load(_ url: URL) {
        loadingStarted = true;navigationFailed = false;loadedAt = Date.distantFuture
        view.load(URLRequest(url:url))
    }

    private func seed(_ job: [String:Any], host: String, ready: @escaping () -> Void) {
        guard !seeded else { ready();return };seeded = true
        let permitted: Set<String>
        switch host {
        case "openreview.net":permitted = ["openreview.accessToken","openreview.refreshToken","openreview.user"]
        case "stu.xjtu.edu.cn":permitted = ["Coremail","Coremail.sid","uid","locale"]
        default:permitted = []
        }
        let candidates = (job["seed"] as? [[String:String]] ?? []).filter { permitted.contains($0["name"] ?? "") }
        guard !candidates.isEmpty else { ready();return }
        let store = view.configuration.websiteDataStore.httpCookieStore
        store.getAllCookies { existing in
            // An existing app login always wins over imported legacy cookies.
            if existing.contains(where: { permitted.contains($0.name) && $0.domain.trimmingCharacters(in:CharacterSet(charactersIn:".")) == host }) { ready();return }
            let group = DispatchGroup()
            for item in candidates {
                guard let name = item["name"], let value = item["value"],
                      let cookie = HTTPCookie(properties:[.domain:host,.path:"/",.name:name,.value:value,.secure:"TRUE",.expires:Date().addingTimeInterval(365*86400)]) else { continue }
                group.enter();store.setCookie(cookie) { group.leave() }
            }
            group.notify(queue:.main,execute:ready)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { loadedAt = Date();navigationFailed = false
        if let host = webView.url?.host { window.title = "连接账号 · " + host } }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { if (error as NSError).code != NSURLErrorCancelled { navigationFailed = true } }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { if (error as NSError).code != NSURLErrorCancelled { navigationFailed = true } }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url, ["https","http","about"].contains(url.scheme ?? "") else { decisionHandler(.cancel);return }
        // External browser is never used for authentication or scheduled monitoring.
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { webView.load(URLRequest(url:url)) };return nil
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        if message.range(of:"密码错误|密码不正确|账号或密码|用户名或密码|incorrect password|invalid credentials",options:.regularExpression) != nil {
            webView.evaluateJavaScript("window.__watchtower_auth_error=true")
        }
        if !window.isVisible { completionHandler();return }
        let alert=NSAlert();alert.messageText="网站提示";alert.informativeText=message
        alert.beginSheetModal(for:window) { _ in completionHandler() }
    }
}
