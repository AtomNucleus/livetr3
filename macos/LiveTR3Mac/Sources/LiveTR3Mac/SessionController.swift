import AVFoundation
import Combine
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
    private let runtime: LiveTR3Runtime
    private let engine: CaptionEngine
    private let audio = AudioCaptureEngine()

    private var manualStop = false
    private var reconnectAttempt = 0
    private var reconnectTask: Task<Void, Never>?

    init(sessionManager: SessionManager, runtime: LiveTR3Runtime) {
        self.sessionManager = sessionManager
        self.runtime = runtime
        self.engine = Self.makeEngine()
        let environment = ProcessInfo.processInfo.environment
        self.config = environment["LIVETR3_DIAGNOSTIC_MIN_SILENCE_MS"] == nil
            ? Self.loadConfig() : .diagnosticConfig(environment: environment)

        engine.onMessage = { [weak self] message in
            Task { @MainActor in
                self?.handleServerMessage(message)
            }
        }
        engine.onDisconnect = { [weak self] in
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

    func startDiagnosticReplayIfRequested() async {
        guard ProcessInfo.processInfo.environment["LIVETR3_NATIVE_REPLAY"] != nil else { return }
        config = .diagnosticConfig(environment: ProcessInfo.processInfo.environment)
        await start()
    }

    func pauseResume() {
        guard status == .running else { return }
        paused.toggle()
        audio.setPaused(paused)
    }

    func commitNow() {
        engine.sendJSON(["type": "commit_now"])
    }

    func skipNextPolish() {
        engine.sendJSON(["type": "skip_polish"])
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
            min_silence_ms: config.min_silence_ms,
            early_commit_enabled: config.early_commit_enabled,
            early_commit_min_seconds: config.early_commit_min_seconds,
            early_commit_punctuation: config.early_commit_punctuation,
            early_commit_stability: config.early_commit_stability,
            stability_window: config.stability_window
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
            let replayPath = ProcessInfo.processInfo.environment["LIVETR3_NATIVE_REPLAY"]
            if replayPath == nil { try await requestMicrophoneAccess() }
            try await ensureRuntimeReady()
            try await connectEngine(mode: .start)
            sendConfig(applyTarget: "immediate")
            engine.sendJSON(["type": "start"])
            let directSender = ProcessInfo.processInfo.environment["LIVETR3_AUDIO_MAIN_ACTOR"] == "1"
                ? nil : engine.audioSender()
            let onFrame: (Data) -> Void = { [weak self] data in
                if let directSender { directSender(data) }
                else {
                    Task { @MainActor in
                        LatencyTrace.shared.record("audio_send", ["bytes": data.count])
                        self?.engine.sendBinary(data)
                    }
                }
            }
            let onLevel: (Float) -> Void = { [weak self] rms in
                Task { @MainActor in self?.appendLevel(rms) }
            }
            if let replayPath {
                // Start only after the actual model worker reports readiness.
                for _ in 0..<1200 {
                    if transcript.workerStatus?.state == .ready { break }
                    try await Task.sleep(nanoseconds: 100_000_000)
                }
                guard transcript.workerStatus?.state == .ready else {
                    throw LiveTR3SessionError(message: "Diagnostic replay model did not become ready.")
                }
                LatencyTrace.shared.record("replay_start", ["config": String(describing: config)])
                try audio.startReplay(url: URL(fileURLWithPath: replayPath), onFrame: onFrame, onLevel: onLevel) { [weak self] in
                    Task { @MainActor in self?.engine.sendJSON(["type": "commit_now"]) }
                }
            } else {
                try audio.start(deviceID: selectedDeviceID.nilIfEmpty, onFrame: onFrame, onLevel: onLevel)
            }
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
        engine.sendJSON(["type": "stop"])
        engine.disconnect()
        audio.stop()
        paused = false
        status = .idle
    }

    private func connectEngine(mode: CaptionEngineConnectionMode) async throws {
        try await engine.connect(sessionID: sessionManager.sessionID, mode: mode)
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
        engine.sendConfig(live)
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
        error = "Local engine connection interrupted. Reconnecting to local engine..."
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
                try await self.connectEngine(mode: .resume)
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

    private func ensureRuntimeReady() async throws {
        switch runtime.state {
        case .ready:
            return
        case .idle, .failed:
            await runtime.start()
        case .starting:
            break
        }

        for _ in 0..<80 {
            if runtime.state == .ready {
                return
            }
            if runtime.state == .failed {
                throw LiveTR3SessionError(message: runtime.statusMessage)
            }
            try await Task.sleep(nanoseconds: 250_000_000)
        }

        throw LiveTR3SessionError(message: "Local engine did not become ready.")
    }

    private static func makeEngine() -> CaptionEngine {
        if ProcessInfo.processInfo.environment["LIVETR3_DEBUG_WEBSOCKET"] == "1" {
            return LiveTR3WebSocket()
        }
        return LocalEngineConnection()
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
        return optimizedConfig(config)
    }

    private static func optimizedConfig(_ config: ClientConfig) -> ClientConfig {
        var next = config
        // 150 and 400 ms were earlier defaults; 600 ms cut FLEURS source errors
        // by about 12% for about 0.05 s of added caption delay.
        if next.min_silence_ms == nil || next.min_silence_ms == 150 || next.min_silence_ms == 400 {
            next.min_silence_ms = ClientConfig.default.min_silence_ms
        }
        if next.max_utterance_seconds == nil || next.max_utterance_seconds == 12 {
            next.max_utterance_seconds = 6
        }
        if next.partial_interval_seconds == nil
            || next.partial_interval_seconds == 0.75
            || next.partial_interval_seconds == 0.45 {
            next.partial_interval_seconds = 0.25
        }
        next.early_commit_enabled = false
        if next.early_commit_min_seconds == nil {
            next.early_commit_min_seconds = 1.0
        }
        if next.early_commit_punctuation == nil {
            next.early_commit_punctuation = true
        }
        if next.early_commit_stability == nil {
            next.early_commit_stability = true
        }
        if next.stability_window == nil {
            next.stability_window = 2
        }
        return next
    }
}

@MainActor
final class ProjectorConnection: ObservableObject {
    @Published private(set) var connectionError: String?
    let transcript = TranscriptStore(traceLabel: "projector")

    private let sessionID: String
    private let makeEngine: () -> CaptionEngine
    private let waitForRetry: (TimeInterval) async throws -> Void
    private var engine: CaptionEngine?
    private var connectionTask: Task<Void, Never>?
    private var retryTask: Task<Void, Never>?
    private var attemptID: UUID?
    private var wantsConnection = false
    private var retryDelay: TimeInterval = 0.5
    private var transcriptObservation: AnyCancellable?

    init(sessionID: String, makeEngine: (() -> CaptionEngine)? = nil,
         waitForRetry: @escaping (TimeInterval) async throws -> Void = { delay in
             try await Task.sleep(for: .seconds(delay))
         }) {
        self.sessionID = sessionID
        self.makeEngine = makeEngine ?? {
            if ProcessInfo.processInfo.environment["LIVETR3_DEBUG_WEBSOCKET"] == "1" {
                return LiveTR3WebSocket()
            }
            return LocalEngineConnection()
        }
        self.waitForRetry = waitForRetry
        transcriptObservation = transcript.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }
    }

    func connect() {
        guard !wantsConnection else { return }
        wantsConnection = true
        retryDelay = 0.5
        beginAttempt()
    }

    func disconnect() {
        wantsConnection = false
        retryTask?.cancel()
        retryTask = nil
        retireAttempt()
        connectionError = nil
    }

    private func beginAttempt() {
        guard wantsConnection, attemptID == nil else { return }
        let id = UUID()
        let engine = makeEngine()
        // Rejoin as a viewer of this same session, never send producer `resume` or
        // clear the store: its IDs and the presentation's reading position survive.
        let replayFloor = transcript.entries.map(\.id).max() ?? Int.min
        self.engine = engine
        attemptID = id
        engine.onMessage = { [weak self] message in
            guard let self, self.wantsConnection, self.attemptID == id else { return }
            if case .caption(_, let utteranceID, _, _) = message,
               utteranceID <= replayFloor,
               !self.transcript.entries.contains(where: { $0.id == utteranceID }) { return }
            self.transcript.handle(message)
            switch message {
            case .caption, .status(state: .ready, message: _):
                self.connectionError = nil
                self.retryDelay = 0.5
            default:
                break
            }
        }
        engine.onDisconnect = { [weak self] in
            self?.connectionFailed(id: id)
        }
        let sessionID = self.sessionID
        connectionTask = Task { [weak self] in
            do {
                try Task.checkCancellation()
                try await engine.connect(sessionID: sessionID, mode: .viewer)
                try Task.checkCancellation()
                guard let self, self.wantsConnection, self.attemptID == id else { return }
                self.connectionTask = nil
                self.connectionError = nil
                self.transcript.clearError()
                // Reset backoff on actual traffic, not an optimistic WebSocket open.
            } catch {
                self?.connectionFailed(id: id)
            }
        }
    }

    private func connectionFailed(id: UUID) {
        guard wantsConnection, attemptID == id else { return }
        retireAttempt()
        connectionError = "Projector local engine connection closed. Reconnecting…"
        guard retryTask == nil else { return }
        let delay = retryDelay
        retryDelay = min(retryDelay * 2, 8)
        let wait = waitForRetry
        retryTask = Task { [weak self] in
            do {
                try await wait(delay)
                try Task.checkCancellation()
                guard let self, self.wantsConnection else { return }
                self.retryTask = nil
                self.beginAttempt()
            } catch {
                // Closing the projector cancels the pending delay.
            }
        }
    }

    private func retireAttempt() {
        // Invalidate callbacks before cancellation, including late connect completions.
        attemptID = nil
        connectionTask?.cancel()
        connectionTask = nil
        engine?.onMessage = nil
        engine?.onDisconnect = nil
        engine?.disconnect()
        engine = nil
    }
}

private extension String {
    var nilIfEmpty: String? {
        isEmpty ? nil : self
    }
}
