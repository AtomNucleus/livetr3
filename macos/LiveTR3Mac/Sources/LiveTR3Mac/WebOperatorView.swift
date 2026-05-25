import SwiftUI
import WebKit

struct WebOperatorView: NSViewRepresentable {
    let url: URL
    let reloadToken: Int
    var projectorFontSize: Double?
    var openProjectorWindow: (() -> Void)?

    init(
        url: URL,
        reloadToken: Int,
        projectorFontSize: Double? = nil,
        openProjectorWindow: (() -> Void)? = nil
    ) {
        self.url = url
        self.reloadToken = reloadToken
        self.projectorFontSize = projectorFontSize
        self.openProjectorWindow = openProjectorWindow
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        if let script = projectorFontScript(fontSize: projectorFontSize) {
            configuration.userContentController.addUserScript(script)
        }
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.setValue(false, forKey: "drawsBackground")
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.clear.cgColor
        view.navigationDelegate = context.coordinator
        view.uiDelegate = context.coordinator
        view.allowsBackForwardNavigationGestures = true
        view.load(URLRequest(url: url))
        return view
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {
        if context.coordinator.projectorFontSize != projectorFontSize {
            context.coordinator.projectorFontSize = projectorFontSize
            applyProjectorFontSize(projectorFontSize, in: nsView)
        }

        if context.coordinator.reloadToken != reloadToken {
            context.coordinator.reloadToken = reloadToken
            nsView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
        } else if nsView.url == nil {
            nsView.load(URLRequest(url: url))
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(projectorFontSize: projectorFontSize, openProjectorWindow: openProjectorWindow)
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        var reloadToken = 0
        var projectorFontSize: Double?
        private let openProjectorWindow: (() -> Void)?

        init(projectorFontSize: Double?, openProjectorWindow: (() -> Void)?) {
            self.projectorFontSize = projectorFontSize
            self.openProjectorWindow = openProjectorWindow
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            guard webView.url?.path == LiveTR3Routes.projectorURL.path else { return }
            applyProjectorFontSize(projectorFontSize, in: webView)
        }

        func webView(
            _ webView: WKWebView,
            createWebViewWith configuration: WKWebViewConfiguration,
            for navigationAction: WKNavigationAction,
            windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            guard let url = navigationAction.request.url else { return nil }
            if url.path == LiveTR3Routes.projectorURL.path {
                openProjectorWindow?()
                return nil
            }
            webView.load(URLRequest(url: url))
            return nil
        }
    }
}

private func projectorFontScript(fontSize: Double?) -> WKUserScript? {
    guard let source = projectorFontScriptSource(fontSize: fontSize) else { return nil }
    return WKUserScript(source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true)
}

private func applyProjectorFontSize(_ fontSize: Double?, in webView: WKWebView) {
    guard webView.url?.path == LiveTR3Routes.projectorURL.path,
          let source = projectorFontScriptSource(fontSize: fontSize) else { return }
    webView.evaluateJavaScript(source)
}

private func projectorFontScriptSource(fontSize: Double?) -> String? {
    guard let fontSize else { return nil }
    let clamped = min(144, max(36, fontSize))
    let key = "livetr3.projector.font.\(projectorSessionID())"
    return """
    localStorage.setItem('\(key)', '\(Int(clamped))');
    window.dispatchEvent(new StorageEvent('storage', { key: '\(key)' }));
    """
}

private func projectorSessionID() -> String {
    URLComponents(url: LiveTR3Routes.projectorURL, resolvingAgainstBaseURL: false)?
        .queryItems?
        .first(where: { $0.name == "session" })?
        .value ?? "native"
}
