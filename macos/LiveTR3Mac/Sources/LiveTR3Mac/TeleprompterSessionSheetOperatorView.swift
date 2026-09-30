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

    @State private var hudVisible = true
    @State private var settingsPresented = false
    @State private var partialPulseActive = false
    @State private var controlsHeight: CGFloat = 150

    var body: some View {
        ZStack(alignment: .bottom) {
            VStack(spacing: 0) {
                if let workerStatus = transcript.workerStatus, workerStatus.state != .ready {
                    banner(text: workerStatus.message, tint: .orange)
                }

                if let error = displayedError {
                    banner(text: error, tint: .red)
                }

                cueReader
            }

            VStack(spacing: 10) {
                bottomHUD
                    .opacity(hudVisible || settingsPresented ? 1 : 0)
                    .animation(.easeInOut(duration: 0.2), value: hudVisible)
                projectorLookBar
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 22)
            .background {
                GeometryReader { geometry in
                    Color.clear.preference(key: OperatorControlsHeightKey.self, value: geometry.size.height)
                }
            }
        }
        .background(Color.black.opacity(0.93))
        .onPreferenceChange(OperatorControlsHeightKey.self) { controlsHeight = $0 }
        .onHover { hudVisible = $0 }
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
        .sheet(isPresented: $settingsPresented) {
            sessionControlsSheet
        }
        .background {
            TeleprompterShortcutMonitor(
                onStartStop: session.startStop,
                onExportTXT: exportTXT
            )
        }
    }

    private var displayedError: String? {
        transcript.lastError ?? session.error
    }

    private var cueReader: some View {
        TeleprompterCueReader(
            transcript: transcript,
            targetLanguage: session.config.target_lang,
            fontSize: sessionManager.projectorFontSize
        )
        // Keep the latest caption above the floating controls, including while they fade.
        .padding(.bottom, controlsHeight + 12)
    }

    private var projectorLookBar: some View {
        HStack(spacing: 12) {
            Text("Projector")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)

            ProjectorLookPicker(selection: $sessionManager.projectorStyle)
                .frame(maxWidth: 280)

            Text(sessionManager.projectorStyle.detail)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)

            Spacer(minLength: 8)

            Button(action: onOpenProjector) {
                Label("Open Projector", systemImage: "rectangle.on.rectangle")
            }
            .buttonStyle(.bordered)
            .accessibilityHint("Opens the audience window using the selected look")
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .liveGlassSurface(cornerRadius: 18, interactive: true)
        .accessibilityElement(children: .contain)
    }

    private var bottomHUD: some View {
        HStack(spacing: 16) {
            statusBadge
            WaveformMeterView(levels: session.levels, rms: session.levels.last ?? 0)
            partialsIndicator

            Divider().frame(height: 22)

            HStack(spacing: 8) {
                Text("Aa")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Slider(value: $sessionManager.projectorFontSize, in: 36...144, step: 2)
                    .frame(width: 120)
            }

            Divider().frame(height: 22)

            Button(action: session.startStop) {
                Text(startStopTitle)
                    .font(.subheadline.weight(.semibold))
                    .frame(minWidth: 72)
            }
            .buttonStyle(.borderedProminent)
            .tint(session.status == .running ? .red : .accentColor)
            .disabled(session.status == .connecting)

            Button(session.paused ? "Resume" : "Pause", action: session.pauseResume)
                .buttonStyle(.bordered)
                .disabled(session.status != .running)

            Button {
                settingsPresented = true
            } label: {
                Label("Controls", systemImage: "slider.horizontal.3")
            }
            .buttonStyle(.bordered)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
        .liveGlassSurface(cornerRadius: 24, interactive: true)
        .liveGlassGroup()
        .shadow(color: .black.opacity(0.35), radius: 18, y: 8)
    }

    private var statusBadge: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(statusColor)
                .frame(width: 10, height: 10)
            Text(statusLabel)
                .font(.subheadline.weight(.semibold))
            Text("/")
                .foregroundStyle(.tertiary)
            Text("\(session.config.source_lang) to \(session.config.target_lang)")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(statusLabel), \(session.config.source_lang) to \(session.config.target_lang)")
    }

    private var partialsIndicator: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(Color.green)
                .frame(width: 9, height: 9)
                .opacity(partialPulseActive ? 1 : 0.25)
            Text("Partials")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
        }
    }

    private var sessionControlsSheet: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Session controls")
                    .font(.headline)
                Spacer()
                Button("Done") { settingsPresented = false }
                    .keyboardShortcut(.defaultAction)
            }
            .padding()

            Divider()

            ScrollView {
                OperatorSettingsPanel(
                    session: session,
                    sessionManager: sessionManager,
                    onOpenProjector: onOpenProjector
                )
            }
        }
        .frame(width: 620, height: 660)
    }

    @ViewBuilder
    private func banner(text: String, tint: Color) -> some View {
        Text(text)
            .font(.subheadline)
            .foregroundStyle(tint == .red ? Color.red.opacity(0.9) : Color.orange.opacity(0.95))
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 20)
            .padding(.vertical, 8)
            .background(tint.opacity(0.12))
    }

    private var startStopTitle: String {
        switch session.status {
        case .running: "End"
        case .connecting: "Connecting"
        case .idle: "Start"
        }
    }

    private var statusLabel: String {
        switch session.status {
        case .running: "Live"
        case .connecting: "Connecting"
        case .idle: "Ready"
        }
    }

    private var statusColor: Color {
        switch session.status {
        case .running: .green
        case .connecting: .yellow
        case .idle: .gray
        }
    }

    private func exportTXT() {
        TranscriptExporter.exportTXT(
            entries: transcript.entries,
            source: session.config.source_lang,
            target: session.config.target_lang
        )
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
            .padding(.vertical, 48)
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
                    Text("Translating to \(targetLanguage)…")
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
        VStack(spacing: 12) {
            Text("Ready for live translation")
                .font(.title.weight(.semibold))
                .foregroundStyle(.white)
            Text("Start a session to fill the teleprompter.")
                .font(.title3)
                .foregroundStyle(.white.opacity(0.52))
        }
        .multilineTextAlignment(.center)
        .padding(.bottom, 80)
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

private struct OperatorControlsHeightKey: PreferenceKey {
    static let defaultValue: CGFloat = 150
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}
