import AVFoundation
import Foundation

enum SessionCaptureStatus: Equatable {
    case idle
    case connecting
    case running
}

@MainActor
final class SessionController: ObservableObject {
    @Published private(set) var status: SessionCaptureStatus = .idle
    @Published private(set) var paused = false
    @Published private(set) var error: String?
    @Published private(set) var levels: [Float] = Array(repeating: 0, count: 10)
    @Published var config: ClientConfig
    @Published var selectedDeviceID: String = ""

    let transcript = TranscriptStore()

    private let sessionManager: SessionManager
    private let webSocket = LiveTR3WebSocket()
    private let audio = AudioCaptureEngine()

    private var manualStop = false
    private var reconnectAttempt = 0
    private var reconnectTask: Task<Void, Never>?

    init(sessionManager: SessionManager) {
        self.sessionManager = sessionManager
        self.config = Self.loadConfig()

        webSocket.onMessage = { [weak self] message in
            Task { @MainActor in
                self?.handleServerMessage(message)
            }
        }
        webSocket.onDisconnect = { [weak self] in
            Task { @MainActor in
                self?.handleDisconnect()
            }
        }
    }

    var devices: [AudioInputDevice] {
        AudioCaptureEngine.listInputDevices()
    }

    var sessionID: String {
        sessionManager.sessionID
    }

    func refreshDevices() {
        objectWillChange.send()
    }

    func startStop() {
        switch status {
        case .running, .connecting:
            stop()
        case .idle:
            Task { await start() }
        }
    }

    func pauseResume() {
        guard status == .running else { return }
        paused.toggle()
        audio.setPaused(paused)
    }

    func commitNow() {
        webSocket.sendJSON(["type": "commit_now"])
    }

    func skipNextPolish() {
        webSocket.sendJSON(["type": "skip_polish"])
    }

    func swapDirection() {
        config = ClientConfig(
            version: 2,
            source_lang: config.target_lang,
            target_lang: config.source_lang,
            custom_vocab: config.custom_vocab,
            segmenter: config.segmenter,
            polish_enabled: config.polish_enabled,
            apply_target: "next_utterance",
            input_device_id: selectedDeviceID.nilIfEmpty,
            input_device_label: selectedDeviceLabel,
            code_switching_enabled: config.code_switching_enabled,
            partial_interval_seconds: config.partial_interval_seconds,
            max_utterance_seconds: config.max_utterance_seconds,
            silero_threshold: config.silero_threshold,
            speech_pad_ms: config.speech_pad_ms,
            min_silence_ms: config.min_silence_ms
        )
        persistConfig()
        if status == .running {
            sendConfig(applyTarget: "next_utterance")
        }
    }

    func updateConfig(_ next: ClientConfig, applyTarget: String = "immediate") {
        config = next
        persistConfig()
        if status == .running {
            sendConfig(applyTarget: applyTarget)
        }
    }

    func setSelectedDeviceID(_ deviceID: String) {
        selectedDeviceID = deviceID
        if status == .running {
            Task {
                do {
                    try audio.switchDevice(deviceID.nilIfEmpty)
                    error = nil
                } catch {
                    self.error = error.localizedDescription
                }
            }
        }
    }

    func clearTranscript() {
        transcript.clear()
    }

    private func start() async {
        guard status == .idle else { return }
        manualStop = false
        error = nil
        status = .connecting

        do {
            try await requestMicrophoneAccess()
            try audio.start(
                deviceID: selectedDeviceID.nilIfEmpty,
                onFrame: { [weak self] data in
                    Task { @MainActor in
                        self?.webSocket.sendBinary(data)
                    }
                },
                onLevel: { [weak self] rms in
                    Task { @MainActor in
                        self?.appendLevel(rms)
                    }
                }
            )
            try await connectSocket(mode: .start)
            sendConfig(applyTarget: "immediate")
            webSocket.sendJSON(["type": "start"])
            reconnectAttempt = 0
            status = .running
            paused = false
            error = nil
        } catch {
            stop()
            self.error = error.localizedDescription
        }
    }

    private func stop() {
        manualStop = true
        reconnectTask?.cancel()
        reconnectTask = nil
        webSocket.sendJSON(["type": "stop"])
        webSocket.disconnect()
        audio.stop()
        paused = false
        status = .idle
    }

    private func connectSocket(mode: WebSocketConnectionMode) async throws {
        try await webSocket.connect(sessionID: sessionManager.sessionID, mode: mode)
        if mode == .resume {
            sendConfig(applyTarget: "immediate")
        }
    }

    private func sendConfig(applyTarget: String) {
        var live = config
        live.version = 2
        live.apply_target = applyTarget
        live.input_device_id = selectedDeviceID.nilIfEmpty
        live.input_device_label = selectedDeviceLabel
        webSocket.sendConfig(live)
    }

    private func handleServerMessage(_ message: LiveTR3ServerMessage) {
        if case .level(let rms) = message {
            appendLevel(rms)
        }
        transcript.handle(message)
        if case .error(let message) = message {
            error = message
        }
    }

    private func handleDisconnect() {
        guard !manualStop else {
            status = .idle
            return
        }
        status = .connecting
        error = "Backend connection lost. Reconnecting..."
        scheduleReconnect()
    }

    private func scheduleReconnect() {
        reconnectTask?.cancel()
        let delay = min(1_000 * Int(pow(2.0, Double(reconnectAttempt))), 8_000)
        reconnectAttempt += 1
        reconnectTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(delay) * 1_000_000)
            guard let self, !Task.isCancelled, !self.manualStop else { return }
            do {
                try await self.connectSocket(mode: .resume)
                self.reconnectAttempt = 0
                self.status = .running
                self.error = nil
            } catch {
                self.error = error.localizedDescription
                self.scheduleReconnect()
            }
        }
    }

    private func appendLevel(_ rms: Float) {
        if levels.count >= 10 {
            levels.removeFirst()
        }
        levels.append(rms)
    }

    private var selectedDeviceLabel: String? {
        devices.first(where: { $0.id == selectedDeviceID })?.name
    }

    private func requestMicrophoneAccess() async throws {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            return
        case .notDetermined:
            let granted = await AVCaptureDevice.requestAccess(for: .audio)
            guard granted else {
                throw LiveTR3SessionError(message: "Microphone access was denied.")
            }
        default:
            throw LiveTR3SessionError(message: "Microphone access is blocked. Enable it in System Settings.")
        }
    }

    private func persistConfig() {
        if let data = try? JSONEncoder().encode(config) {
            UserDefaults.standard.set(data, forKey: "LiveTR3.clientConfig")
        }
    }

    private static func loadConfig() -> ClientConfig {
        guard let data = UserDefaults.standard.data(forKey: "LiveTR3.clientConfig"),
              let config = try? JSONDecoder().decode(ClientConfig.self, from: data) else {
            return .default
        }
        return config
    }
}

@MainActor
final class ProjectorConnection: ObservableObject {
    @Published private(set) var connectionError: String?
    let transcript = TranscriptStore()

    private let sessionID: String
    private let webSocket = LiveTR3WebSocket()

    init(sessionID: String) {
        self.sessionID = sessionID
        webSocket.onMessage = { [weak self] message in
            Task { @MainActor in
                self?.transcript.handle(message)
                if case .error(let message) = message {
                    self?.connectionError = message
                }
            }
        }
        webSocket.onDisconnect = { [weak self] in
            Task { @MainActor in
                self?.connectionError = self?.connectionError ?? "Projector connection closed"
            }
        }
    }

    func connect() {
        Task {
            do {
                try await webSocket.connect(sessionID: sessionID, mode: .viewer)
                connectionError = nil
            } catch {
                connectionError = "Projector connection failed"
            }
        }
    }

    func disconnect() {
        webSocket.disconnect()
    }
}

private extension String {
    var nilIfEmpty: String? {
        isEmpty ? nil : self
    }
}
