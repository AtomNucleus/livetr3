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
    @State private var clock: SessionClock?

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

            ControlGroup {
                Button {
                    adjustCaptionSize(by: -Self.captionSizeStep)
                } label: {
                    Label("Smaller Captions", systemImage: "textformat.size.smaller")
                }
                .keyboardShortcut("-", modifiers: .command)
                .disabled(sessionManager.projectorFontSize <= Self.captionSizeRange.lowerBound)
                .help("Smaller captions (⌘−)")

                Button {
                    adjustCaptionSize(by: Self.captionSizeStep)
                } label: {
                    Label("Bigger Captions", systemImage: "textformat.size.larger")
                }
                .keyboardShortcut("+", modifiers: .command)
                .disabled(sessionManager.projectorFontSize >= Self.captionSizeRange.upperBound)
                .help("Bigger captions (⌘+)")
            } label: {
                Label("Caption Size", systemImage: "textformat.size")
            }
            .accessibilityValue("\(Int(sessionManager.projectorFontSize)) points")

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

    /// One pill: a single obvious action when idle, labelled Pause, status and End
    /// once live, and the language pair as a glass button at the end.
    private var transportBar: some View {
        HStack(spacing: 4) {
            transportPill
            languageCodes
        }
        .padding(5)
        .liveGlassCapsule()
        .controlSize(.large)
        .liveGlassGroup()
        .fixedSize()
        .animation(.smooth(duration: 0.3), value: session.status)
        .animation(.smooth(duration: 0.2), value: session.paused)
        .onChange(of: session.status) { _, status in
            clock = status == .running ? SessionClock(startedAt: Date()) : nil
        }
        .onChange(of: session.paused) { _, paused in
            clock?.setPaused(paused, at: Date())
        }
        .onAppear {
            // Reopening the window mid-session restarts the count rather than hiding it.
            if session.status == .running, clock == nil {
                clock = SessionClock(startedAt: Date())
                clock?.setPaused(session.paused, at: Date())
            }
        }
    }

    @ViewBuilder
    private var transportPill: some View {
        switch session.status {
        case .idle:
            Button(action: session.startStop) {
                Label("Start Translating", systemImage: "mic.fill")
                    .padding(.horizontal, 6)
            }
            .buttonBorderShape(.capsule)
            .liveGlassButtonStyle(prominent: true)
            .help("Start session (Space)")
        case .connecting:
            Button(action: {}) {
                Label {
                    Text("Connecting…")
                } icon: {
                    ProgressView().controlSize(.small)
                }
                .padding(.horizontal, 6)
            }
            .buttonBorderShape(.capsule)
            .liveGlassButtonStyle(prominent: true)
            .disabled(true)
        case .running:
            HStack(spacing: 4) {
                Button(action: session.pauseResume) {
                    Label(session.paused ? "Resume" : "Pause",
                          systemImage: session.paused ? "play.fill" : "pause.fill")
                        .frame(minWidth: 78)
                }
                .buttonBorderShape(.capsule)
                .liveGlassButtonStyle()
                .help(session.paused ? "Resume capture" : "Pause capture")

                liveStatus
                    .padding(.horizontal, 10)

                Button(role: .destructive, action: session.startStop) {
                    Label("End", systemImage: "stop.fill")
                        .frame(minWidth: 52)
                }
                .buttonBorderShape(.capsule)
                .liveGlassButtonStyle()
                .tint(.red)
                .help("End session (Space)")
            }
        }
    }

    /// Waveform and elapsed time; the waveform brightens briefly as partial captions arrive.
    private var liveStatus: some View {
        HStack(spacing: 10) {
            LiveWaveformMeter(meter: session.levelMeter)
                .opacity(session.paused ? 0.35 : (partialPulseActive ? 1 : 0.7))
                .accessibilityHint("Brightens as captions arrive")

            if let clock {
                SessionClockLabel(clock: clock, paused: session.paused)
            }
        }
    }

    /// Codes keep the pill short and can't truncate; full names are in the tooltip and for VoiceOver.
    private var languageCodes: some View {
        Button(action: swapLanguages) {
            HStack(spacing: 6) {
                Text(LiveTR3Language.shortCode(session.config.source_lang))
                Image(systemName: "arrow.right")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(.secondary)
                Text(LiveTR3Language.shortCode(session.config.target_lang))
            }
            .font(.callout.weight(.semibold).monospaced())
            .lineLimit(1)
            .fixedSize()
        }
        .buttonBorderShape(.capsule)
        .liveGlassButtonStyle()
        .help("\(session.config.source_lang) to \(session.config.target_lang). "
              + (session.status == .running ? "Click to swap from the next utterance." : "Click to swap."))
        .accessibilityLabel("\(session.config.source_lang) to \(session.config.target_lang)")
        .accessibilityHint("Swaps the languages")
    }

    private func adjustCaptionSize(by delta: Double) {
        sessionManager.projectorFontSize = min(max(sessionManager.projectorFontSize + delta, Self.captionSizeRange.lowerBound), Self.captionSizeRange.upperBound)
    }

    private static let captionSizeRange: ClosedRange<Double> = 36...144
    private static let captionSizeStep: Double = 4

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

/// Elapsed live time, excluding paused stretches. Kept as view state so the
/// session controller publishes nothing new.
struct SessionClock: Equatable {
    let startedAt: Date
    private var pausedTotal: TimeInterval = 0
    private var pausedSince: Date?

    init(startedAt: Date) {
        self.startedAt = startedAt
    }

    mutating func setPaused(_ paused: Bool, at now: Date) {
        if paused, pausedSince == nil {
            pausedSince = now
        } else if !paused, let since = pausedSince {
            pausedTotal += now.timeIntervalSince(since)
            pausedSince = nil
        }
    }

    func elapsed(at now: Date) -> TimeInterval {
        let end = pausedSince ?? now
        return max(0, end.timeIntervalSince(startedAt) - pausedTotal)
    }
}

/// Redraws only itself, once a second, so the timer never invalidates the caption list.
private struct SessionClockLabel: View {
    let clock: SessionClock
    let paused: Bool

    var body: some View {
        TimelineView(.periodic(from: clock.startedAt, by: 1)) { context in
            let seconds = Int(clock.elapsed(at: context.date))
            Text(Self.format(seconds))
                .font(.callout.weight(.semibold).monospacedDigit())
                .foregroundStyle(paused ? Color.orange : Color.primary)
                .accessibilityLabel(paused ? "Paused at \(Self.format(seconds))" : "Live for \(Self.format(seconds))")
        }
    }

    static func format(_ seconds: Int) -> String {
        let h = seconds / 3600, m = (seconds % 3600) / 60, s = seconds % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%02d:%02d", m, s)
    }
}
