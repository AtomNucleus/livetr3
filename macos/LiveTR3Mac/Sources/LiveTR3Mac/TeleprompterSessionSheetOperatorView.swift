import AppKit
import SwiftUI

struct TeleprompterSessionSheetOperatorView: View {
    @ObservedObject var session: SessionController
    @ObservedObject var sessionManager: SessionManager
    let onOpenProjector: () -> Void
    @ObservedObject private var transcript: TranscriptStore

    init(session: SessionController, sessionManager: SessionManager, onOpenProjector: @escaping () -> Void) {
        self.session = session
        self.sessionManager = sessionManager
        self.onOpenProjector = onOpenProjector
        self.transcript = session.transcript
    }

    @State private var pointerInside = true
    @State private var inspectorPresented = false
    @State private var partialPulseActive = false

    var body: some View {
        TeleprompterCueReader(
            transcript: transcript,
            targetLanguage: session.config.target_lang,
            fontSize: sessionManager.projectorFontSize
        )
        .liveSafeAreaBar(edge: .top) { alerts }
        .liveSafeAreaBar(edge: .bottom) {
            transportBar
                .padding(.horizontal, 20)
                .padding(.bottom, 18)
                .opacity(hudVisible ? 1 : 0)
                .animation(.easeInOut(duration: 0.25), value: hudVisible)
        }
        .background {
            LinearGradient(
                colors: [Color(white: 0.075), .black],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()
        }
        .onHover { pointerInside = $0 }
        .toolbar { toolbarContent }
        .inspector(isPresented: $inspectorPresented) {
            OperatorSettingsPanel(session: session, sessionManager: sessionManager)
                .inspectorColumnWidth(min: 300, ideal: 340, max: 440)
        }
        .onAppear {
            session.refreshDevices()
        }
        .task(id: transcript.partialTickAt) {
            guard transcript.partialTickAt != nil else { return }
            partialPulseActive = true
            do {
                try await Task.sleep(nanoseconds: 150_000_000)
                partialPulseActive = false
            } catch {
                // A newer partial owns the pulse; an older task must not switch it off.
            }
        }
        .background {
            TeleprompterShortcutMonitor(
                onStartStop: session.startStop,
                onExportTXT: { export(.txt) }
            )
        }
    }

    /// Keep transport reachable whenever the operator could need it; fade it only while live and idle-pointer.
    private var hudVisible: Bool {
        pointerInside || inspectorPresented || session.status != .running
    }

    // MARK: Toolbar

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItemGroup(placement: .principal) {
            ProjectorLookPicker(selection: $sessionManager.projectorStyle, iconsOnly: true)

            Button(action: onOpenProjector) {
                Label("Open Projector", systemImage: "display")
            }
            .help("Open the audience projector window (⇧⌘P)")
        }

        ToolbarItemGroup(placement: .automatic) {
            Menu {
                Button(action: session.commitNow) {
                    Label("Commit Now", systemImage: "text.badge.checkmark")
                }
                .disabled(session.status != .running)

                Button(action: session.skipNextPolish) {
                    Label("Skip Next Polish", systemImage: "wand.and.sparkles.inverse")
                }
                .disabled(session.status != .running || !session.config.polish_enabled)

                Divider()

                Button(role: .destructive, action: session.clearTranscript) {
                    Label("Clear Transcript", systemImage: "trash")
                }
            } label: {
                Label("Session Actions", systemImage: "ellipsis")
            }
            .menuIndicator(.hidden)
            .accessibilityLabel("Session actions")
            .help("Session actions")

            Menu {
                ForEach(TranscriptFormat.allCases) { format in
                    Button(format.title) { export(format) }
                }
            } label: {
                Label("Export Transcript", systemImage: "square.and.arrow.up")
            }
            .menuIndicator(.hidden)
            .accessibilityLabel("Export transcript")
            .help("Export transcript (⌘E for text)")
            .disabled(transcript.entries.isEmpty)
        }

        ToolbarItem(placement: .automatic) {
            Button {
                inspectorPresented.toggle()
            } label: {
                Label("Session Settings", systemImage: "sidebar.trailing")
            }
            .keyboardShortcut("i", modifiers: [.command, .option])
            .help(inspectorPresented ? "Hide session settings (⌥⌘I)" : "Show session settings (⌥⌘I)")
        }
    }

    // MARK: Transport

    private var transportBar: some View {
        HStack(spacing: 14) {
            HStack(spacing: 8) {
                startStopButton
                pauseButton
            }
            .controlSize(.large)

            liveStatus

            WaveformMeterView(levels: session.levels, rms: session.levels.last ?? 0)

            Circle()
                .fill(Color.green)
                .frame(width: 7, height: 7)
                .opacity(partialPulseActive ? 1 : 0.2)
                .help("Partial captions arriving")
                .accessibilityLabel("Partial caption activity")

            Divider().frame(height: 22)

            languagePair

            Divider().frame(height: 22)

            captionSizeControl
        }
        .padding(.leading, 8)
        .padding(.trailing, 18)
        .padding(.vertical, 8)
        .liveGlassCapsule()
        .liveGlassGroup()
        .fixedSize()
    }

    private var startStopButton: some View {
        Button(action: session.startStop) {
            Group {
                switch session.status {
                case .idle:
                    Image(systemName: "mic.fill")
                case .connecting:
                    ProgressView().controlSize(.small)
                case .running:
                    Image(systemName: "stop.fill")
                }
            }
            .frame(width: 22, height: 22)
        }
        .buttonBorderShape(.circle)
        .liveGlassButtonStyle(prominent: true)
        .tint(session.status == .running ? .red : .accentColor)
        .disabled(session.status == .connecting)
        .help(session.status == .running ? "End session (Space)" : "Start session (Space)")
        .accessibilityLabel(session.status == .running ? "End session" : "Start session")
    }

    private var pauseButton: some View {
        Button(action: session.pauseResume) {
            Image(systemName: session.paused ? "play.fill" : "pause.fill")
                .frame(width: 22, height: 22)
        }
        .buttonBorderShape(.circle)
        .liveGlassButtonStyle()
        .disabled(session.status != .running)
        .help(session.paused ? "Resume capture" : "Pause capture")
        .accessibilityLabel(session.paused ? "Resume capture" : "Pause capture")
    }

    @ViewBuilder
    private var liveStatus: some View {
        switch session.status {
        case .running:
            Text(session.paused ? "PAUSED" : "LIVE")
                .font(.caption.weight(.heavy))
                .tracking(0.8)
                .foregroundStyle(.white)
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(session.paused ? Color.orange : Color.red, in: Capsule())
                .accessibilityLabel(session.paused ? "Paused" : "Live")
        case .connecting:
            Image(systemName: "antenna.radiowaves.left.and.right")
                .symbolEffect(.variableColor.iterative)
                .foregroundStyle(.yellow)
                .help("Connecting")
                .accessibilityLabel("Connecting")
        case .idle:
            EmptyView()
        }
    }

    private var languagePair: some View {
        HStack(spacing: 6) {
            Button {
                inspectorPresented = true
            } label: {
                HStack(spacing: 5) {
                    Text(LiveTR3Language.shortCode(session.config.source_lang))
                    Image(systemName: "arrow.right")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.secondary)
                    Text(LiveTR3Language.shortCode(session.config.target_lang))
                }
                .font(.callout.weight(.semibold).monospaced())
            }
            .buttonStyle(.plain)
            .help("\(session.config.source_lang) to \(session.config.target_lang)")
            .accessibilityLabel("\(session.config.source_lang) to \(session.config.target_lang)")

            Button(action: swapLanguages) {
                Image(systemName: "arrow.left.arrow.right")
            }
            .buttonStyle(.borderless)
            .help(session.status == .running ? "Swap languages from the next utterance" : "Swap languages")
            .accessibilityLabel("Swap languages")
        }
    }

    private var captionSizeControl: some View {
        HStack(spacing: 6) {
            Image(systemName: "textformat.size.smaller")
                .foregroundStyle(.secondary)
            Slider(value: $sessionManager.projectorFontSize, in: 36...144, step: 2)
                .controlSize(.small)
                .frame(width: 110)
                .accessibilityLabel("Caption size")
                .accessibilityValue("\(Int(sessionManager.projectorFontSize)) points")
            Image(systemName: "textformat.size.larger")
                .foregroundStyle(.secondary)
        }
        .help("Caption size: \(Int(sessionManager.projectorFontSize)) pt")
    }

    // MARK: Alerts

    @ViewBuilder
    private var alerts: some View {
        let workerMessage = transcript.workerStatus.flatMap { $0.state == .ready ? nil : $0.message }
        if workerMessage != nil || displayedError != nil {
            VStack(spacing: 8) {
                if let workerMessage {
                    alertPill(workerMessage, symbol: "hourglass", tint: .orange)
                }
                if let displayedError {
                    alertPill(displayedError, symbol: "exclamationmark.triangle.fill", tint: .red)
                }
            }
            .liveGlassGroup()
            .padding(.top, 8)
            .padding(.horizontal, 20)
        }
    }

    private func alertPill(_ text: String, symbol: String, tint: Color) -> some View {
        Label {
            Text(text)
                .lineLimit(2)
        } icon: {
            Image(systemName: symbol)
                .foregroundStyle(tint)
        }
        .font(.callout)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .liveGlassCapsule(tint: tint.opacity(0.35))
    }

    private var displayedError: String? {
        transcript.lastError ?? session.error
    }

    // MARK: Actions

    private func swapLanguages() {
        if session.status == .running {
            session.swapDirection()
        } else {
            var next = session.config
            (next.source_lang, next.target_lang) = (next.target_lang, next.source_lang)
            session.updateConfig(next)
        }
    }

    private func export(_ format: TranscriptFormat) {
        format.export(
            entries: transcript.entries,
            source: session.config.source_lang,
            target: session.config.target_lang
        )
    }
}

enum TranscriptFormat: String, CaseIterable, Identifiable {
    case txt, srt, vtt

    var id: String { rawValue }

    var title: String {
        switch self {
        case .txt: "Plain Text (.txt)"
        case .srt: "SubRip Subtitles (.srt)"
        case .vtt: "WebVTT Subtitles (.vtt)"
        }
    }

    func export(entries: [TranscriptUtterance], source: String, target: String) {
        switch self {
        case .txt: TranscriptExporter.exportTXT(entries: entries, source: source, target: target)
        case .srt: TranscriptExporter.exportSRT(entries: entries, source: source, target: target)
        case .vtt: TranscriptExporter.exportVTT(entries: entries, source: source, target: target)
        }
    }
}

extension LiveTR3Language {
    var shortCode: String {
        switch self {
        case .english: "EN"
        case .spanish: "ES"
        case .french: "FR"
        case .german: "DE"
        case .italian: "IT"
        case .portuguese: "PT"
        case .japanese: "JA"
        case .korean: "KO"
        case .mandarin: "ZH"
        case .arabic: "AR"
        }
    }

    static func shortCode(_ name: String) -> String {
        LiveTR3Language(rawValue: name)?.shortCode ?? String(name.prefix(2)).uppercased()
    }
}

// Observing the transcript here keeps caption delivery independent of audio-meter updates.
private struct TeleprompterCueReader: View {
    @ObservedObject var transcript: TranscriptStore
    let targetLanguage: String
    let fontSize: Double

    var body: some View {
        LiveCaptionScrollView {
            LazyVStack(alignment: cueAlignment, spacing: 18) {
                ForEach(transcript.displayEntries) { entry in
                    cueBlock(for: entry)
                        .id(entry.id)
                }
            }
            .padding(.horizontal, 48)
            .padding(.vertical, 32)
            .frame(maxWidth: .infinity, alignment: frameAlignment)
        }
        .environment(\.layoutDirection, isRtlLanguage(targetLanguage) ? .rightToLeft : .leftToRight)
        .overlay {
            if transcript.displayEntries.isEmpty {
                emptyState
            }
        }
    }

    @ViewBuilder
    private func cueBlock(for entry: TranscriptUtterance) -> some View {
        VStack(alignment: cueAlignment, spacing: 6) {
            StableCaptionLayout(fontSize: 20) {
                Text(entry.original)
                    .font(.title3)
                    .foregroundStyle(.white.opacity(0.48))
                    .multilineTextAlignment(textAlignment)
            }

            StableCaptionLayout(fontSize: fontSize) {
                if entry.translation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    Label("Translating to \(targetLanguage)…", systemImage: "ellipsis")
                        .font(.title3)
                        .foregroundStyle(.white.opacity(0.48))
                } else {
                    Text(entry.translation)
                        .font(.system(size: fontSize, weight: .semibold))
                        .foregroundStyle(entry.state == .partial ? .white.opacity(0.72) : .white)
                        .multilineTextAlignment(textAlignment)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: frameAlignment)
        .onAppear { traceCue(entry) }
        .onChange(of: entry.original) { _, _ in traceCueField(entry, field: "original", text: entry.original) }
        .onChange(of: entry.translation) { _, _ in traceCueField(entry, field: "translation", text: entry.translation) }
        .onChange(of: entry.state) { _, _ in traceCue(entry) }
    }

    private func traceCue(_ entry: TranscriptUtterance) {
        traceCueField(entry, field: "original", text: entry.original)
        traceCueField(entry, field: "translation", text: entry.translation)
    }

    private func traceCueField(_ entry: TranscriptUtterance, field: String, text: String) {
        guard LatencyTrace.shared.isEnabled else { return }
        LatencyTrace.shared.record("view_text_update_proxy", ["surface": "operator", "utterance": entry.id, "field": field, "chars": text.count, "signature": text.hashValue, "type": String(describing: entry.state)])
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label("Ready to Translate", systemImage: "captions.bubble")
        } description: {
            Text("Press Space to start.")
        }
        .foregroundStyle(.white.opacity(0.7))
    }

    private var cueAlignment: HorizontalAlignment {
        isRtlLanguage(targetLanguage) ? .trailing : .leading
    }

    private var textAlignment: TextAlignment {
        isRtlLanguage(targetLanguage) ? .trailing : .leading
    }

    private var frameAlignment: Alignment {
        isRtlLanguage(targetLanguage) ? .trailing : .leading
    }
}

private struct TeleprompterShortcutMonitor: NSViewRepresentable {
    let onStartStop: () -> Void
    let onExportTXT: () -> Void

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        context.coordinator.start(
            onStartStop: onStartStop,
            onExportTXT: onExportTXT
        )
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        context.coordinator.updateHandlers(
            onStartStop: onStartStop,
            onExportTXT: onExportTXT
        )
    }

    static func dismantleNSView(_ nsView: NSView, coordinator: Coordinator) {
        coordinator.stop()
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    final class Coordinator {
        private var monitor: Any?
        private var onStartStop: (() -> Void)?
        private var onExportTXT: (() -> Void)?

        func start(
            onStartStop: @escaping () -> Void,
            onExportTXT: @escaping () -> Void
        ) {
            updateHandlers(
                onStartStop: onStartStop,
                onExportTXT: onExportTXT
            )
            guard monitor == nil else { return }
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                guard let self else { return event }
                guard !self.isTypingTarget(event) else { return event }

                if event.keyCode == 49, event.modifierFlags.intersection(.deviceIndependentFlagsMask).isEmpty {
                    self.onStartStop?()
                    return nil
                }
                if event.modifierFlags.contains(.command), event.charactersIgnoringModifiers?.lowercased() == "e" {
                    self.onExportTXT?()
                    return nil
                }
                return event
            }
        }

        func updateHandlers(
            onStartStop: @escaping () -> Void,
            onExportTXT: @escaping () -> Void
        ) {
            self.onStartStop = onStartStop
            self.onExportTXT = onExportTXT
        }

        func stop() {
            if let monitor {
                NSEvent.removeMonitor(monitor)
            }
            monitor = nil
        }

        private func isTypingTarget(_ event: NSEvent) -> Bool {
            guard let responder = event.window?.firstResponder else { return false }
            return responder is NSTextView || responder is NSTextField
        }
    }
}
