// JARVIS menu bar icon: always one click away.
// Usage: JARVISMenu <dashboard-url> <path-to-JARVIS.app>
import Cocoa

let args = CommandLine.arguments
let base = args.count > 1 ? args[1] : "http://127.0.0.1:8000"
let appPath = args.count > 2 ? args[2] : "/Applications/JARVIS.app"

final class MenuController: NSObject, NSApplicationDelegate, NSMenuDelegate {
    var item: NSStatusItem!
    let statusLine = NSMenuItem(title: "Checking…", action: nil, keyEquivalent: "")
    let stopItem = NSMenuItem(title: "Emergency stop", action: #selector(toggleStop), keyEquivalent: "")
    var stopped = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = item.button {
            if let img = NSImage(systemSymbolName: "circle.hexagongrid.circle", accessibilityDescription: "JARVIS")
                ?? NSImage(systemSymbolName: "circle.circle", accessibilityDescription: "JARVIS") {
                img.isTemplate = true
                button.image = img
            } else {
                button.title = "J"
            }
            button.toolTip = "JARVIS"
        }
        let menu = NSMenu()
        menu.delegate = self
        statusLine.isEnabled = false
        menu.addItem(statusLine)
        menu.addItem(NSMenuItem.separator())
        let openItem = NSMenuItem(title: "Open JARVIS", action: #selector(openApp), keyEquivalent: "o")
        openItem.target = self
        menu.addItem(openItem)
        stopItem.target = self
        menu.addItem(stopItem)
        menu.addItem(NSMenuItem.separator())
        let restart = NSMenuItem(title: "Restart Hermes & Mac agent", action: #selector(restartHelpers), keyEquivalent: "")
        restart.target = self
        menu.addItem(restart)
        let quit = NSMenuItem(title: "Quit JARVIS", action: #selector(quitAll), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
        item.menu = menu
        refresh()
        Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in self?.refresh() }
    }

    func menuWillOpen(_ menu: NSMenu) { refresh() }

    func refresh() {
        guard let url = URL(string: base + "/api/status") else { return }
        var req = URLRequest(url: url)
        req.timeoutInterval = 3
        URLSession.shared.dataTask(with: req) { data, _, _ in
            var text = "JARVIS isn't running — click Open"
            var halted = false
            if let data = data, let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                let brain = (json["brain"] as? [String: Any])?["ready"] as? Bool ?? false
                let agent = (json["agent"] as? [String: Any])?["online"] as? Bool ?? false
                halted = json["emergency_stop"] as? Bool ?? false
                text = halted ? "● Actions halted" : (brain && agent ? "● All systems online" : "● Needs attention — open JARVIS")
            }
            DispatchQueue.main.async {
                self.statusLine.title = text
                self.stopped = halted
                self.stopItem.title = halted ? "Resume actions" : "Emergency stop"
            }
        }.resume()
    }

    func post(_ path: String, then: (() -> Void)? = nil) {
        guard let url = URL(string: base + path) else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 60
        URLSession.shared.dataTask(with: req) { _, _, _ in
            DispatchQueue.main.async {
                if let then = then { then() } else { self.refresh() }
            }
        }.resume()
    }

    @objc func openApp() { NSWorkspace.shared.open(URL(fileURLWithPath: appPath)) }
    @objc func toggleStop() { post(stopped ? "/api/resume" : "/api/emergency-stop") }
    @objc func restartHelpers() { post("/api/services/restart") }
    @objc func quitAll() { post("/api/shutdown") { self.refresh() } }
}

let app = NSApplication.shared
let controller = MenuController()
app.delegate = controller
app.setActivationPolicy(.accessory)
app.run()
