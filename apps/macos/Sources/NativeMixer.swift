import AppKit
import Foundation

private struct MixerSource: Decodable {
    let id: String
    let label: String
    let volume: Double
    let muted: Bool
}
private struct MixerReply: Decodable {
    let ok: Bool
    let sources: [MixerSource]
}

@MainActor final class NativeMixer: NSObject {
    private let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 600, height: 420), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
    private let status = NSTextField(wrappingLabelWithString: "Connecting…")
    private let rows = NSStackView()
    private var controls: [NSControl] = []
    private var ids: [Int: String] = [:]
    private var pending: [String: [String: Any]] = [:]
    private var debounce: Timer?
    private var poll: Timer?
    private var busy = false
    private var online = false
    private let explanation = "OBS unavailable. In OBS → Tools → WebSocket Server Settings, enable the loopback server on port 4455 and authentication. Launch via the hidden-password launcher. Controls remain disabled until connected."

    override init() {
        super.init()
        panel.title = "LANBRIDGE Mixer"
        panel.isReleasedWhenClosed = false
        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 14
        root.edgeInsets = NSEdgeInsets(top: 18, left: 18, bottom: 18, right: 18)
        root.translatesAutoresizingMaskIntoConstraints = false
        panel.contentView!.addSubview(root)
        NSLayoutConstraint.activate([root.leadingAnchor.constraint(equalTo: panel.contentView!.leadingAnchor), root.trailingAnchor.constraint(equalTo: panel.contentView!.trailingAnchor), root.topAnchor.constraint(equalTo: panel.contentView!.topAnchor), root.bottomAnchor.constraint(equalTo: panel.contentView!.bottomAnchor)])
        root.addArrangedSubview(status)
        status.widthAnchor.constraint(equalTo: root.widthAnchor, constant: -36).isActive = true
        let refresh = NSButton(title: "Refresh OBS sources", target: self, action: #selector(refreshNow))
        root.addArrangedSubview(refresh)
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        rows.orientation = .vertical
        rows.alignment = .leading
        rows.spacing = 12
        rows.translatesAutoresizingMaskIntoConstraints = false
        scroll.documentView = rows
        root.addArrangedSubview(scroll)
        scroll.widthAnchor.constraint(equalTo: root.widthAnchor, constant: -36).isActive = true
        rows.widthAnchor.constraint(equalTo: scroll.widthAnchor, constant: -20).isActive = true
        poll = Timer.scheduledTimer(withTimeInterval: 4, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.panel.isVisible, self.pending.isEmpty else { return }
                self.refreshNow()
            }
        }
    }
    func show() {
        panel.center()
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        refreshNow()
    }
    @objc private func refreshNow() {
        guard !busy, pending.isEmpty else { return }
        send(["op": "read"])
    }
    @objc private func volumeChanged(_ slider: NSSlider) {
        guard online, let id = ids[slider.tag] else { return }
        pending[id] = ["op": "set", "id": id, "volume": slider.doubleValue]
        debounce?.invalidate()
        debounce = Timer.scheduledTimer(withTimeInterval: 0.3, repeats: false) { [weak self] _ in
            Task { @MainActor in self?.flush() }
        }
    }
    @objc private func muteChanged(_ button: NSButton) {
        guard online, let id = ids[button.tag] else { return }
        // Keep volume and mute writes separate and ordered.
        pending[id + "\u{0}mute"] = ["op": "set", "id": id, "muted": button.state == .on]
        flush()
    }
    private func flush() {
        guard !busy, let key = pending.keys.sorted().first, let payload = pending.removeValue(forKey: key) else { return }
        send(payload)
    }
    private func send(_ payload: [String: Any]) {
        guard let input = try? JSONSerialization.data(withJSONObject: payload) else { return }
        busy = true
        let python = ProcessInfo.processInfo.environment["LANBRIDGE_MIXER_PYTHON"] ?? NSHomeDirectory() + "/.local/share/lanmouse-suite/venv/bin/python"
        Task {
            let data: Data = await Task.detached {
                let p = Process()
                p.executableURL = URL(fileURLWithPath: python)
                p.arguments = ["-m", "lanmouse_suite.mixer_cli"]
                let stdin = Pipe()
                // A temporary output file avoids pipe-capacity deadlocks for large source lists.
                let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
                FileManager.default.createFile(atPath: url.path, contents: nil, attributes: [.posixPermissions: 0o600])
                defer { try? FileManager.default.removeItem(at: url) }
                guard let output = try? FileHandle(forWritingTo: url) else { return Data() }
                defer { try? output.close() }
                p.standardInput = stdin
                p.standardOutput = output
                p.standardError = FileHandle.nullDevice
                do {
                    try p.run()
                    stdin.fileHandleForWriting.write(input)
                    try? stdin.fileHandleForWriting.close()
                    let deadline = Date().addingTimeInterval(12)
                    while p.isRunning && Date() < deadline { usleep(50_000) }
                    if p.isRunning { kill(p.processIdentifier, SIGKILL); p.waitUntilExit(); return Data() }
                    return (try? Data(contentsOf: url)) ?? Data()
                } catch { return Data() }
            }.value
            busy = false
            guard let reply = try? JSONDecoder().decode(MixerReply.self, from: data), reply.ok else {
                online = false
                pending.removeAll()
                controls.forEach { $0.isEnabled = false }
                status.stringValue = explanation
                if CommandLine.arguments.contains("--mixer-smoke") {
                    print("PASS native panel offline: controls disabled; setup explanation displayed")
                    NSApp.terminate(nil)
                }
                return
            }
            online = true
            if !pending.isEmpty { flush(); return }
            status.stringValue = "Connected to local OBS — \(reply.sources.count) audio sources"
            rows.arrangedSubviews.forEach { rows.removeArrangedSubview($0); $0.removeFromSuperview() }
            controls.removeAll(); ids.removeAll()
            for (index, source) in reply.sources.enumerated() {
                ids[index] = source.id
                let label = NSTextField(labelWithString: source.label)
                let slider = NSSlider(value: source.volume, minValue: 0, maxValue: 1, target: self, action: #selector(volumeChanged(_:)))
                slider.tag = index
                slider.isContinuous = true
                slider.setAccessibilityLabel(source.label + " volume")
                slider.widthAnchor.constraint(equalToConstant: 240).isActive = true
                let mute = NSButton(checkboxWithTitle: "Mute", target: self, action: #selector(muteChanged(_:)))
                mute.tag = index
                mute.state = source.muted ? .on : .off
                mute.setAccessibilityLabel(source.label + " mute")
                let row = NSStackView(views: [label, slider, mute])
                row.spacing = 12
                rows.addArrangedSubview(row)
                controls.append(contentsOf: [slider, mute])
            }
        }
    }
}
