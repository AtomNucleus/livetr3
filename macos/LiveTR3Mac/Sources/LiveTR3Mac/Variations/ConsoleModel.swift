import SwiftUI

// MARK: - Shared preview/design model
//
// `ConsoleModel` mirrors the functional surface of the live operator screen
// (`SessionController` + `SessionManager`) with in-memory sample data so every
// interface variation below can render and behave inside a SwiftUI `#Preview`.
//
// It intentionally exposes the *same* capabilities the production operator has:
//   - transport (start / stop, pause / resume)
//   - live status + language direction
//   - audio waveform + partial-result activity
//   - caption setup (source / target language, swap)
//   - input (microphone selection, VAD, polish)
//   - output (projector font size, open projector)
//   - live session actions (commit now, skip next polish, clear)
//   - export (TXT / SRT / VTT)
//   - custom vocabulary
//   - advanced timing tuning
//
// Every variation binds to this one model, so they are functionally identical
// and differ only in layout, chrome, and how settings are disclosed.

struct ConsoleBanner: Equatable {
    enum Kind { case warning, error }
    let text: String
    let kind: Kind

    var tint: Color {
        switch kind {
        case .warning: .orange
        case .error: .red
        }
    }
}

final class ConsoleModel: ObservableObject {
    enum CaptureStatus { case idle, connecting, running }

    @Published var status: CaptureStatus
    @Published var paused = false
    @Published var levels: [Float]
    @Published var partialActive = false
    @Published var entries: [TranscriptUtterance]
    @Published var config: ClientConfig
    @Published var selectedDeviceID: String
    @Published var projectorFontSize: Double
    @Published var banner: ConsoleBanner?

    let devices: [AudioInputDevice]
    var onOpenProjector: () -> Void

    init(
        status: CaptureStatus = .running,
        paused: Bool = false,
        entries: [TranscriptUtterance] = ConsoleModel.sampleEntries,
        config: ClientConfig = .previewDefault,
        devices: [AudioInputDevice] = ConsoleModel.sampleDevices,
        selectedDeviceID: String = "usb-mv7",
        levels: [Float] = ConsoleModel.sampleLevels,
        projectorFontSize: Double = 72,
        banner: ConsoleBanner? = nil,
        onOpenProjector: @escaping () -> Void = {}
    ) {
        self.status = status
        self.paused = paused
        self.entries = entries
        self.config = config
        self.devices = devices
        self.selectedDeviceID = selectedDeviceID
        self.levels = levels
        self.projectorFontSize = projectorFontSize
        self.banner = banner
        self.onOpenProjector = onOpenProjector
    }

    // MARK: Derived display state

    var isRunning: Bool { status == .running }

    var statusLabel: String {
        switch status {
        case .running: paused ? "Paused" : "Live"
        case .connecting: "Connecting"
        case .idle: "Ready"
        }
    }

    var statusColor: Color {
        switch status {
        case .running: paused ? .orange : .green
        case .connecting: .yellow
        case .idle: .secondary
        }
    }

    var statusSymbol: String {
        switch status {
        case .running: paused ? "pause.circle.fill" : "dot.radiowaves.left.and.right"
        case .connecting: "arrow.triangle.2.circlepath"
        case .idle: "circle"
        }
    }

    var directionText: String { "\(config.source_lang) → \(config.target_lang)" }

    var startStopTitle: String {
        switch status {
        case .running: "End"
        case .connecting: "Connecting"
        case .idle: "Start"
        }
    }

    var selectedDeviceName: String {
        devices.first { $0.id == selectedDeviceID }?.name ?? "System default"
    }

    // MARK: Actions

    func startStop() {
        switch status {
        case .running, .connecting:
            status = .idle
            paused = false
            partialActive = false
        case .idle:
            status = .running
            banner = nil
        }
    }

    func pauseResume() {
        guard status == .running else { return }
        paused.toggle()
    }

    func swapDirection() {
        let source = config.source_lang
        config.source_lang = config.target_lang
        config.target_lang = source
    }

    func commitNow() {
        guard let index = entries.lastIndex(where: { $0.state == .partial }) else { return }
        entries[index].state = .final
        entries[index].stableOriginalLength = entries[index].original.count
        entries[index].stableTranslationLength = entries[index].translation.count
        entries[index].endedAt = Date()
    }

    func skipNextPolish() {
        banner = ConsoleBanner(text: "Next utterance will skip polish.", kind: .warning)
    }

    func clearTranscript() {
        entries = []
        banner = nil
    }

    func openProjector() { onOpenProjector() }

    func exportTXT() {
        TranscriptExporter.exportTXT(entries: entries, source: config.source_lang, target: config.target_lang)
    }

    func exportSRT() {
        TranscriptExporter.exportSRT(entries: entries, source: config.source_lang, target: config.target_lang)
    }

    func exportVTT() {
        TranscriptExporter.exportVTT(entries: entries, source: config.source_lang, target: config.target_lang)
    }

    // MARK: Bindings

    var sourceBinding: Binding<String> {
        Binding(get: { self.config.source_lang }, set: { self.config.source_lang = $0 })
    }

    var targetBinding: Binding<String> {
        Binding(get: { self.config.target_lang }, set: { self.config.target_lang = $0 })
    }

    var deviceBinding: Binding<String> {
        Binding(get: { self.selectedDeviceID }, set: { self.selectedDeviceID = $0 })
    }

    var polishBinding: Binding<Bool> {
        Binding(get: { self.config.polish_enabled }, set: { self.config.polish_enabled = $0 })
    }

    var codeSwitchBinding: Binding<Bool> {
        Binding(
            get: { self.config.code_switching_enabled ?? false },
            set: { self.config.code_switching_enabled = $0 }
        )
    }

    var customVocabBinding: Binding<String> {
        Binding(
            get: { self.config.custom_vocab.joined(separator: ", ") },
            set: { value in
                self.config.custom_vocab = value
                    .split(separator: ",")
                    .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                    .filter { !$0.isEmpty }
            }
        )
    }

    func doubleBinding(_ keyPath: WritableKeyPath<ClientConfig, Double?>, default def: Double) -> Binding<Double> {
        Binding(
            get: { self.config[keyPath: keyPath] ?? def },
            set: { self.config[keyPath: keyPath] = $0 }
        )
    }
}

// MARK: - Sample data

extension ClientConfig {
    /// A concrete, non-optional-heavy config for previews.
    static let previewDefault: ClientConfig = {
        var config = ClientConfig.default
        config.source_lang = LiveTR3Language.english.rawValue
        config.target_lang = LiveTR3Language.spanish.rawValue
        config.custom_vocab = ["LiveTR3", "Cupertino", "parakeet"]
        config.polish_enabled = true
        return config
    }()
}

extension ConsoleModel {
    static let sampleDevices: [AudioInputDevice] = [
        AudioInputDevice(id: "builtin", name: "MacBook Pro Microphone"),
        AudioInputDevice(id: "usb-mv7", name: "Shure MV7"),
        AudioInputDevice(id: "aggregate", name: "Aggregate Device")
    ]

    static let sampleLevels: [Float] = [0.05, 0.12, 0.28, 0.44, 0.36, 0.52, 0.61, 0.4, 0.73, 0.58]

    static let sampleEntries: [TranscriptUtterance] = [
        make(1, "Good morning everyone, and thank you for joining today.",
             "Buenos días a todos, y gracias por acompañarnos hoy.", .polished, ago: 44),
        make(2, "We will begin with a short welcome before the main session.",
             "Comenzaremos con una breve bienvenida antes de la sesión principal.", .final, ago: 30),
        make(3, "Please make sure the captions are readable from the back rows.",
             "Por favor, asegúrense de que los subtítulos se lean desde las últimas filas.", .final, ago: 16),
        make(4, "If you need a different language, let the operator know now",
             "Si necesitan otro idioma, avisen al operador ahora", .partial, ago: 2)
    ]

    private static func make(
        _ id: Int,
        _ original: String,
        _ translation: String,
        _ state: UtteranceState,
        ago: TimeInterval
    ) -> TranscriptUtterance {
        let stableOriginal = state == .partial ? Int(Double(original.count) * 0.62) : original.count
        let stableTranslation = state == .partial ? Int(Double(translation.count) * 0.5) : translation.count
        return TranscriptUtterance(
            id: id,
            original: original,
            translation: translation,
            state: state,
            stableOriginalLength: stableOriginal,
            stableTranslationLength: stableTranslation,
            startedAt: Date().addingTimeInterval(-ago),
            endedAt: state == .partial ? nil : Date().addingTimeInterval(-ago + 3)
        )
    }
}
