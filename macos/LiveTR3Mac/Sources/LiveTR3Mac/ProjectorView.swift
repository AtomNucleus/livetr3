import Combine
import SwiftUI

struct ProjectorView: View {
    @ObservedObject var connection: ProjectorConnection
    @ObservedObject var sessionManager: SessionManager
    @EnvironmentObject private var session: SessionController

    var body: some View {
        ProjectorTranscriptView(
            transcript: connection.transcript,
            sessionManager: sessionManager,
            sourceLanguage: session.config.source_lang,
            targetLanguage: session.config.target_lang,
            connectionError: connection.connectionError
        )
        .onAppear { connection.connect() }
        .onDisappear { connection.disconnect() }
    }
}

/// Observe the store itself: observing its owner does not forward nested changes.
private struct ProjectorTranscriptView: View {
    @ObservedObject var transcript: TranscriptStore
    @ObservedObject var sessionManager: SessionManager
    let sourceLanguage: String
    let targetLanguage: String
    let connectionError: String?
    var body: some View {
        if ProcessInfo.processInfo.environment["LIVETR3_PROJECTOR_READING_QUEUE"] == "1" {
            ProjectorReadingQueueDiagnosticView(transcript: transcript, sessionManager: sessionManager,
                sourceLanguage: sourceLanguage, targetLanguage: targetLanguage, connectionError: connectionError)
        } else {
        GeometryReader { geometry in
            let layout = ProjectorCaptionLayout(size: geometry.size,
                requestedFontSize: sessionManager.projectorFontSize,
                style: sessionManager.projectorStyle)
            if layout.style == .rollUp {
                ProjectorRollUpStage(
                    entries: transcript.displayEntries,
                    layout: layout,
                    targetLanguage: targetLanguage,
                    status: connectionError ?? transcript.lastError
                )
            } else {
                ProjectorLiveCaptionStage(
                    entries: transcript.displayEntries,
                    layout: layout,
                    sourceLanguage: sourceLanguage,
                    targetLanguage: targetLanguage,
                    status: connectionError ?? transcript.lastError
                )
            }
        }
        }
    }
}

/// Follow the same revisions as the operator. Full captions remain in scrollable history;
/// no reading-time queue can withhold a newer utterance or hide its live translation.
struct ProjectorLiveCaptionStage: View {
    let entries: [TranscriptUtterance]
    let layout: ProjectorCaptionLayout
    let sourceLanguage: String
    let targetLanguage: String
    var status: String?

    var body: some View {
        VStack(spacing: 16) {
            switch layout.style {
            case .focus, .rollUp:
                lane(source: false)
            case .split:
                HStack(spacing: 24) {
                    lane(source: true)
                    Rectangle().fill(.white.opacity(0.25)).frame(width: 1)
                    lane(source: false)
                }
            case .stack:
                VStack(spacing: 24) {
                    lane(source: true)
                    Rectangle().fill(.white.opacity(0.25)).frame(height: 1)
                    lane(source: false)
                }
            }
            if let status {
                Text(status).font(.system(size: 18)).foregroundStyle(.orange)
            }
        }
        .padding(layout.inset)
        .frame(width: layout.size.width, height: layout.size.height)
        .background(.black)
        .foregroundStyle(.white)
        .transaction { $0.animation = nil }
    }

    private func lane(source: Bool) -> some View {
        let language = source ? sourceLanguage : targetLanguage
        let fontSize = source ? layout.sourceFontSize : layout.fontSize
        let ordered = Self.orderedEntries(entries)
        return VStack(alignment: .leading, spacing: 12) {
            Text(language).font(.system(size: 18, weight: .semibold)).foregroundStyle(.white.opacity(0.6))
            LiveCaptionScrollView {
                LazyVStack(alignment: .leading, spacing: fontSize * 0.3) {
                    ForEach(ordered) { entry in
                        let text = source ? entry.original : entry.translation
                        StableCaptionLayout(fontSize: fontSize) {
                            Text(text.isEmpty && !source ? "Translating…" : text)
                                .font(.system(size: fontSize, weight: .semibold))
                                .lineSpacing(layout.lineSpacing)
                                .foregroundStyle(entry.state == .partial ? .white.opacity(0.75) : .white)
                                .fixedSize(horizontal: false, vertical: true)
                                .multilineTextAlignment(isRtlLanguage(language) ? .trailing : .leading)
                                .frame(maxWidth: .infinity, alignment: isRtlLanguage(language) ? .trailing : .leading)
                                .onAppear { trace(entry, source: source) }
                                .onChange(of: text) { _, _ in trace(entry, source: source) }
                                .onChange(of: entry.state) { _, _ in trace(entry, source: source) }
                        }
                    }
                }
                .padding(.vertical, 8)
            }
            .overlay {
                if ordered.isEmpty {
                    Text("Listening…").font(.system(size: fontSize)).foregroundStyle(.white.opacity(0.75))
                }
            }
        }
        .environment(\.layoutDirection, isRtlLanguage(language) ? .rightToLeft : .leftToRight)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    static func orderedEntries(_ entries: [TranscriptUtterance]) -> [TranscriptUtterance] {
        entries.sorted { $0.id < $1.id }
    }

    private func trace(_ entry: TranscriptUtterance, source: Bool) {
        guard LatencyTrace.shared.isEnabled else { return }
        let text = source ? entry.original : entry.translation
        LatencyTrace.shared.record("view_text_update_proxy", ["surface": "projector", "utterance": entry.id, "field": source ? "original" : "translation", "chars": text.count, "signature": text.hashValue, "type": String(describing: entry.state)])
    }
}

/// Kept separate from the connection so the real audience surface can be rendered in tests.
struct ProjectorCaptionStage: View {
    let current: ProjectorCaptionPresentation.Caption?
    var previous: ProjectorCaptionPresentation.Caption? = nil
    let draft: ProjectorCaptionPresentation.Caption?
    var isTranslationPending = false
    let layout: ProjectorCaptionLayout
    let sourceLanguage: String
    let targetLanguage: String
    var status: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            mainCaption
                .frame(height: layout.mainHeight, alignment: .topLeading)

            VStack(alignment: .leading, spacing: 12) {
                Rectangle().fill(.white.opacity(0.2)).frame(height: 1)
                if let current, isTranslationPending || (draft != nil && current.utteranceID != draft?.utteranceID) {
                    label("Live draft · may change", color: .white.opacity(0.8))
                    draftCaption(draft)
                } else if let status {
                    label("Caption connection needs attention", color: .orange)
                        .accessibilityHint(status)
                }
            }
            .frame(height: layout.draftHeight, alignment: .topLeading)
        }
        .padding(layout.inset)
        .frame(width: layout.size.width, height: layout.size.height, alignment: .topLeading)
        .background(.black)
        .foregroundStyle(.white)
        .transaction { $0.animation = nil }
    }

    @ViewBuilder
    private var mainCaption: some View {
        if let caption = current ?? draft {
            let isDraft = current == nil
            let source = isDraft ? layout.prefix(caption.original, source: true, balancePages: false) : caption.original
            let target = isDraft && isTranslationPending ? "Translating…"
                : isDraft ? layout.prefix(caption.translation, source: false, balancePages: false) : caption.translation
            switch layout.style {
            case .focus, .rollUp:
                lane(target, previous: previous?.translation, source: false,
                     title: title(targetLanguage, draft: isDraft, continuation: caption.isContinuation),
                     fontSize: layout.fontSize, language: targetLanguage)
            case .split:
                HStack(alignment: .top, spacing: 24) {
                    lane(source, previous: previous?.original, source: true,
                         title: title(sourceLanguage, draft: isDraft, continuation: caption.isContinuation),
                         fontSize: layout.sourceFontSize, language: sourceLanguage)
                    Rectangle().fill(.white.opacity(0.25)).frame(width: 1)
                    lane(target, previous: previous?.translation, source: false,
                         title: title(targetLanguage, draft: isDraft, continuation: caption.isContinuation),
                         fontSize: layout.fontSize, language: targetLanguage)
                }
            case .stack:
                VStack(alignment: .leading, spacing: 24) {
                    lane(source, previous: previous?.original, source: true,
                         title: title(sourceLanguage, draft: isDraft, continuation: caption.isContinuation),
                         fontSize: layout.sourceFontSize, language: sourceLanguage)
                        .frame(height: (layout.mainHeight - 24) / 2, alignment: .top)
                    lane(target, previous: previous?.translation, source: false,
                         title: title(targetLanguage, draft: isDraft, continuation: caption.isContinuation),
                         fontSize: layout.fontSize, language: targetLanguage)
                }
            }
        } else {
            Text(isTranslationPending ? "Translating…" : "Listening…")
                .font(.system(size: layout.fontSize, weight: .medium))
                .foregroundStyle(.white.opacity(0.75))
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
    }

    private func title(_ language: String, draft: Bool, continuation: Bool) -> String {
        language + (draft ? " · Live draft" : continuation ? " · Continued" : "")
    }

    private func lane(_ text: String, previous: String?, source: Bool, title: String,
                      fontSize: CGFloat, language: String) -> some View {
        VStack(alignment: isRtlLanguage(language) ? .trailing : .leading, spacing: 12) {
            label(title)
            VStack(spacing: 20) {
                // Refit history only for an explicit window/font/layout change. Ordinary
                // arrivals keep the entire preceding page in this fixed reading slot.
                captionText(layout.prefix(previous ?? "", source: source, balancePages: false)
                    .trimmingCharacters(in: .whitespacesAndNewlines), fontSize: fontSize, language: language)
                    .foregroundStyle(Color.white.opacity(0.88))
                    .frame(height: layout.textHeight(source: source), alignment: .top)
                captionText(text.trimmingCharacters(in: .whitespacesAndNewlines), fontSize: fontSize, language: language)
                    .frame(height: layout.textHeight(source: source), alignment: .top)
            }
        }
        .frame(maxWidth: .infinity, alignment: isRtlLanguage(language) ? .topTrailing : .topLeading)
    }

    @ViewBuilder
    private func draftCaption(_ draft: ProjectorCaptionPresentation.Caption?) -> some View {
        let target = isTranslationPending ? "Translating…" : draft?.translation ?? ""
        if layout.style == .split {
            HStack(alignment: .top, spacing: 48) {
                draftText(draft?.original ?? "", language: sourceLanguage, width: layout.columnWidth)
                draftText(target, language: targetLanguage, width: layout.columnWidth)
            }
        } else {
            draftText(target, language: targetLanguage, width: layout.columnWidth)
        }
    }

    private func draftText(_ text: String, language: String, width: CGFloat) -> some View {
        captionText(layout.draftExcerpt(text, width: width), fontSize: layout.draftFontSize, language: language)
            .foregroundStyle(Color(red: 0.91, green: 0.94, blue: 1))
    }

    private func captionText(_ text: String, fontSize: CGFloat, language: String) -> some View {
        Text(text)
            .font(.system(size: fontSize, weight: .semibold))
            .lineSpacing(layout.lineSpacing)
            .fixedSize(horizontal: false, vertical: true)
            .multilineTextAlignment(isRtlLanguage(language) ? .trailing : .leading)
            .frame(maxWidth: .infinity, alignment: isRtlLanguage(language) ? .trailing : .leading)
            .environment(\.layoutDirection, isRtlLanguage(language) ? .rightToLeft : .leftToRight)
    }

    private func label(_ text: String, color: Color = .white.opacity(0.72)) -> some View {
        Text(text)
            .font(.system(size: 18, weight: .semibold))
            .foregroundStyle(color)
    }
}

/// The prior policy is retained only for an explicit diagnostic A/B replay.
private struct ProjectorReadingQueueDiagnosticView: View {
    @ObservedObject var transcript: TranscriptStore
    @ObservedObject var sessionManager: SessionManager
    let sourceLanguage: String
    let targetLanguage: String
    let connectionError: String?
    @State private var presentation = ProjectorCaptionPresentation()
    private let clock = Timer.publish(every: 0.1, on: .main, in: .common).autoconnect()
    var body: some View {
        GeometryReader { geometry in
            let layout = ProjectorCaptionLayout(size: geometry.size,
                requestedFontSize: sessionManager.projectorFontSize, style: sessionManager.projectorStyle)
            ProjectorCaptionStage(current: presentation.current, previous: presentation.previous,
                draft: presentation.draft, isTranslationPending: presentation.isTranslationPending,
                layout: layout, sourceLanguage: sourceLanguage, targetLanguage: targetLanguage,
                status: connectionError ?? transcript.lastError)
                .onAppear { receive(layout) }
                .onChange(of: transcript.displayEntries) { _, _ in receive(layout) }
                .onChange(of: layout) { _, _ in advance(layout) }
                .onReceive(clock) { _ in advance(layout) }
                .onChange(of: presentation.current) { _, current in
                    if let current { LatencyTrace.shared.record("projector_page_update_proxy", ["utterance": current.utteranceID, "source_chars": current.original.count, "translation_chars": current.translation.count]) }
                }
        }
    }
    private func receive(_ layout: ProjectorCaptionLayout) {
        presentation.receive(transcript.displayEntries, at: ProcessInfo.processInfo.systemUptime)
        advance(layout)
    }
    private func advance(_ layout: ProjectorCaptionLayout) {
        let now = ProcessInfo.processInfo.systemUptime
        presentation.tick(at: now, layout: layout)
        LatencyTrace.shared.record("projector_reading_queue", ["current_utterance": presentation.current?.utteranceID ?? -1,
            "newest_received": transcript.entries.map(\.id).max() ?? -1,
            "queued_utterances": presentation.queuedUtteranceCount, "hold_remaining": max(0, presentation.holdUntil-now)])
    }
}
