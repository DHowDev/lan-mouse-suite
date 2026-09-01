import AppKit
import Foundation

struct DeviceRow: Codable {
    let id: String
    let name: String
    let reachable: Bool
    let on: Bool
    let remote_on: Bool?
    let detail: String
    let address: String?
}

struct ProcessState: Codable { let running: Bool }

struct StatusPayload: Codable {
    let network: String
    let current: String?
    let devices: [DeviceRow]
    let any_on: Bool
    let manual_off: Bool
    let process: ProcessState
    let log_path: String
}

@main
struct LanMouseSuiteStatusMain {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private let menu = NSMenu()
    private var timer: Timer?
    private var busy = false
    private var refreshing = false
    private var latest: StatusPayload?
    private var lastSuccess: Date?

    private var cliPath: String {
        let override = ProcessInfo.processInfo.environment["LANMOUSE_SUITE_CLI"]
        if let value = override, !value.isEmpty { return value }
        let installed = NSHomeDirectory() + "/.local/share/lanmouse-suite/venv/bin/lanmouse-suite"
        return FileManager.default.isExecutableFile(atPath: installed) ? installed : "lanmouse-suite"
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.setAccessibilityLabel("Lan Mouse Suite devices")
        statusItem.menu = menu
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 4, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
    }

    private func rebuildMenu(_ payload: StatusPayload?, stale: Bool = false) {
        menu.removeAllItems()
        let title = NSMenuItem(title: "Lan Mouse Suite", action: nil, keyEquivalent: "")
        title.isEnabled = false
        menu.addItem(title)
        let networkTitle: String
        if let payload, stale {
            networkTitle = "Network: \(payload.network) — status stale, retrying…"
        } else if let payload {
            networkTitle = "Network: \(payload.network)"
        } else {
            networkTitle = "Status unavailable — retrying…"
        }
        let network = NSMenuItem(title: networkTitle, action: nil, keyEquivalent: "")
        network.isEnabled = false
        menu.addItem(network)
        menu.addItem(.separator())
        for row in payload?.devices ?? [] {
            let item = NSMenuItem(title: "\(row.name) — \(row.detail)", action: #selector(toggleDevice(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = row.id
            item.state = row.on ? .on : .off
            let remote = row.remote_on.map { $0 ? "remote on" : "remote off" } ?? "remote unknown"
            item.toolTip = row.address.map { "\(row.detail) at \($0); \(remote)" } ?? "\(row.detail); \(remote)"
            item.isEnabled = !busy
            menu.addItem(item)
        }
        if payload?.devices.isEmpty != false {
            let empty = NSMenuItem(title: "No peers configured", action: nil, keyEquivalent: "")
            empty.isEnabled = false
            menu.addItem(empty)
        }
        menu.addItem(.separator())
        let off = NSMenuItem(title: "Turn Everything Off", action: #selector(allOff), keyEquivalent: "")
        off.target = self
        off.isEnabled = !busy
        menu.addItem(off)
        let logs = NSMenuItem(title: "Open Logs", action: #selector(openLogs), keyEquivalent: "")
        logs.target = self
        menu.addItem(logs)
        menu.addItem(.separator())
        let release = NSMenuItem(title: "Emergency release: Control + Shift + Option + Command", action: nil, keyEquivalent: "")
        release.isEnabled = false
        menu.addItem(release)
        let quit = NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
        updateIcon(payload, stale: stale)
    }

    private func updateIcon(_ payload: StatusPayload?, stale: Bool = false) {
        let anyOn = payload?.any_on ?? false
        let symbol = anyOn ? "point.3.connected.trianglepath.dotted" : "cursorarrow.motionlines"
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: anyOn ? "Lan Mouse on" : "Lan Mouse off")
        image?.isTemplate = true
        statusItem.button?.image = image
        statusItem.button?.title = image == nil ? (anyOn ? "LM" : "LM×") : ""
        statusItem.button?.appearsDisabled = !anyOn || stale
        var mode = payload?.manual_off == true ? "manual OFF" : (anyOn ? "connected" : "off")
        if stale { mode += " (stale)" }
        statusItem.button?.toolTip = "Lan Mouse Suite: \(mode) — \(payload?.network ?? "status unavailable")"
    }

    private func refresh() {
        guard !busy, !refreshing else { return }
        refreshing = true
        Task {
            defer { refreshing = false }
            let output = await runCLI(["status", "--json"])
            guard output.code == 0, let data = output.stdout.data(using: .utf8),
                  let payload = try? JSONDecoder().decode(StatusPayload.self, from: data) else {
                // Keep showing the last known devices instead of a dead menu;
                // a stale banner tells the user the poll is failing.
                rebuildMenu(latest, stale: true)
                return
            }
            latest = payload
            lastSuccess = Date()
            rebuildMenu(payload)
        }
    }

    @objc private func toggleDevice(_ sender: NSMenuItem) {
        guard !busy, let id = sender.representedObject as? String else { return }
        busy = true
        rebuildMenu(latest)
        Task {
            _ = await runCLI(["toggle", id])
            busy = false
            refresh()
        }
    }

    @objc private func allOff() {
        guard !busy else { return }
        busy = true
        rebuildMenu(latest)
        Task {
            _ = await runCLI(["all-off"])
            busy = false
            refresh()
        }
    }

    private func runCLI(_ arguments: [String], timeout: TimeInterval = 15) async -> (code: Int32, stdout: String) {
        let executable = cliPath
        return await Task.detached(priority: .userInitiated) { [executable] in
            let process = Process()
            if executable.contains("/") {
                process.executableURL = URL(fileURLWithPath: executable)
                process.arguments = arguments
            } else {
                process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
                process.arguments = [executable] + arguments
            }
            let output = Pipe()
            process.standardOutput = output
            process.standardError = Pipe()
            do {
                try process.run()
                // Bounded wait: a hung CLI must never freeze the menu or
                // leave the app stuck in a busy state (requires relaunch).
                let deadline = Date().addingTimeInterval(timeout)
                while process.isRunning && Date() < deadline {
                    usleep(100_000)
                }
                if process.isRunning {
                    process.terminate()
                    let killDeadline = Date().addingTimeInterval(2)
                    while process.isRunning && Date() < killDeadline {
                        usleep(100_000)
                    }
                    if process.isRunning {
                        kill(process.processIdentifier, SIGKILL)
                    }
                    return (124, "")
                }
                let text = String(data: output.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                return (process.terminationStatus, text)
            } catch {
                return (127, "")
            }
        }.value
    }

    @objc private func openLogs() {
        let path = latest?.log_path ?? (NSHomeDirectory() + "/Library/Logs/LanMouseSuite/lanmouse-suite.log")
        let url = URL(fileURLWithPath: path)
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: path) { FileManager.default.createFile(atPath: path, contents: Data()) }
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    @objc private func quit() {
        timer?.invalidate()
        NSApp.terminate(nil)
    }
}
