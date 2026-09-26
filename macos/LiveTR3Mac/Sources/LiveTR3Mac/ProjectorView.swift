import AppKit
import SwiftUI

struct ProjectorView: View {
    @ObservedObject var connection: ProjectorConnection
    @ObservedObject var sessionManager: SessionManager
    @EnvironmentObject private var session: SessionController

    @State private var fittedFontSize: CGFloat = 72

    private var visibleEntries: [TranscriptUtterance] {
        connection.transcript.entries
            .filter { entry in
                !entry.original.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    || !entry.translation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            }
            .suffix(2)
            .map { $0 }
    }

    private var statusText: String? {
        if let connectionError = connection.connectionError {
            return connectionError
        }
        if let lastError = connection.transcript.lastError {
            return lastError
        }
        if let workerStatus = connection.transcript.workerStatus, workerStatus.state != .ready {
            return workerStatus.message
        }
        return nil
    }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            VStack(spacing: 0) {
                if let statusText {
                    Text(statusText)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Color.orange.opacity(0.9))
                        .textCase(.uppercase)
                        .tracking(2)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 32)
                        .padding(.top, 24)
                        .accessibilityLabel(statusText)
                }

                GeometryReader { geometry in
                    stage
                        .onAppear {
                            refitFont(containerSize: geometry.size)
                        }
                        .onChange(of: measurementKey) { _, _ in
                            refitFont(containerSize: geometry.size)
                        }
                        .onChange(of: sessionManager.projectorFontSize) { _, _ in
                            refitFont(containerSize: geometry.size)
                        }
                        .onChange(of: sessionManager.projectorStyle) { _, _ in
                            refitFont(containerSize: geometry.size)
                        }
                }
            }
        }
        .onAppear {
            connection.connect()
        }
        .onDisappear {
            connection.disconnect()
        }
    }

    private var measurementKey: String {
        visibleEntries
            .map { "\($0.id)|\($0.original)|\($0.translation)" }
            .joined(separator: "\n")
    }

    @ViewBuilder
    private var stage: some View {
        if visibleEntries.isEmpty {
            Text("Waiting for live captions")
                .font(.system(size: min(fittedFontSize, 64), weight: .semibold))
                .foregroundStyle(Color.white.opacity(0.35))
                .textCase(.uppercase)
                .tracking(4)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityLabel("Waiting for live captions")
        } else {
            switch sessionManager.projectorStyle {
            case .focus:
                focusStage
            case .split:
                splitStage
            case .stack:
                stackStage
            }
        }
    }

    private var focusStage: some View {
        VStack(alignment: .center, spacing: 28) {
            Spacer(minLength: 0)
            ForEach(visibleEntries) { entry in
                VStack(alignment: .center, spacing: 10) {
                    if showsSource(entry) {
                        ProjectorCaptionText(
                            text: entry.original,
                            stableLength: entry.stableOriginalLength,
                            isPartial: entry.state == .partial,
                            fontSize: fittedFontSize * 0.38,
                            weight: .medium,
                            color: .white.opacity(0.48),
                            alignment: .center,
                            layoutDirection: sourceDirection
                        )
                    }
                    ProjectorCaptionText(
                        text: displayTranslation(for: entry),
                        stableLength: translationStableLength(for: entry),
                        isPartial: entry.state == .partial,
                        fontSize: fittedFontSize,
                        weight: .semibold,
                        color: .white,
                        alignment: .center,
                        layoutDirection: targetDirection
                    )
                }
            }
        }
        .padding(.horizontal, 72)
        .padding(.vertical, 56)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
    }

    private var splitStage: some View {
        HStack(alignment: .bottom, spacing: 0) {
            splitColumn(
                title: session.config.source_lang,
                field: .original,
                direction: sourceDirection
            )
            Rectangle()
                .fill(Color.white.opacity(0.16))
                .frame(width: 1)
                .padding(.vertical, 48)
                .accessibilityHidden(true)
            splitColumn(
                title: session.config.target_lang,
                field: .translation,
                direction: targetDirection
            )
        }
        .padding(.horizontal, 36)
        .padding(.vertical, 28)
    }

    private func splitColumn(
        title: String,
        field: ProjectorCaptionField,
        direction: LayoutDirection
    ) -> some View {
        VStack(alignment: direction == .rightToLeft ? .trailing : .leading, spacing: 22) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(Color.white.opacity(0.45))
                .textCase(.uppercase)
                .tracking(1.5)
                .frame(maxWidth: .infinity, alignment: direction == .rightToLeft ? .trailing : .leading)
            Spacer(minLength: 0)
            ForEach(visibleEntries) { entry in
                ProjectorCaptionText(
                    text: field.text(from: entry),
                    stableLength: field.stableLength(from: entry),
                    isPartial: entry.state == .partial,
                    fontSize: fittedFontSize * 0.82,
                    weight: .semibold,
                    color: field == .translation ? .white : .white.opacity(0.82),
                    alignment: direction == .rightToLeft ? .trailing : .leading,
                    layoutDirection: direction
                )
            }
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
    }

    private var stackStage: some View {
        let alignment: HorizontalAlignment = targetDirection == .rightToLeft ? .trailing : .leading
        return VStack(alignment: alignment, spacing: 32) {
            Spacer(minLength: 0)
            ForEach(visibleEntries) { entry in
                VStack(alignment: alignment, spacing: 8) {
                    if showsSource(entry) {
                        ProjectorCaptionText(
                            text: entry.original,
                            stableLength: entry.stableOriginalLength,
                            isPartial: entry.state == .partial,
                            fontSize: fittedFontSize * 0.72,
                            weight: .medium,
                            color: .white.opacity(0.62),
                            alignment: targetDirection == .rightToLeft ? .trailing : .leading,
                            layoutDirection: sourceDirection
                        )
                    }
                    ProjectorCaptionText(
                        text: displayTranslation(for: entry),
                        stableLength: translationStableLength(for: entry),
                        isPartial: entry.state == .partial,
                        fontSize: fittedFontSize,
                        weight: .semibold,
                        color: .white,
                        alignment: targetDirection == .rightToLeft ? .trailing : .leading,
                        layoutDirection: targetDirection
                    )
                }
                .padding(.bottom, 4)
                .overlay(alignment: .bottom) {
                    Rectangle()
                        .fill(Color.white.opacity(0.12))
                        .frame(height: 1)
                        .accessibilityHidden(true)
                }
            }
        }
        .padding(.horizontal, 64)
        .padding(.vertical, 48)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
    }

    private var sourceDirection: LayoutDirection {
        isRtlLanguage(session.config.source_lang) ? .rightToLeft : .leftToRight
    }

    private var targetDirection: LayoutDirection {
        isRtlLanguage(session.config.target_lang) ? .rightToLeft : .leftToRight
    }

    private func showsSource(_ entry: TranscriptUtterance) -> Bool {
        !entry.original.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !entry.translation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func translationStableLength(for entry: TranscriptUtterance) -> Int {
        entry.translation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? entry.stableOriginalLength
            : entry.stableTranslationLength
    }

    private func displayTranslation(for entry: TranscriptUtterance) -> String {
        let translation = entry.translation.trimmingCharacters(in: .whitespacesAndNewlines)
        if translation.isEmpty {
            return entry.original
        }
        return entry.translation
    }

    private func refitFont(containerSize: CGSize) {
        let maxFont = CGFloat(sessionManager.projectorFontSize)
        guard !visibleEntries.isEmpty else {
            fittedFontSize = maxFont
            return
        }

        let style = sessionManager.projectorStyle
        let horizontalInset: CGFloat = style == .split ? 160 : 144
        let usableWidth = max(containerSize.width - horizontalInset, 200)
        let usableHeight = max(containerSize.height - 140, 200)
        let columnWidth = style == .split ? usableWidth / 2 : usableWidth

        var next = maxFont
        while next > 36 {
            if measuredHeight(fontSize: next, columnWidth: columnWidth, style: style) <= usableHeight {
                break
            }
            next -= 2
        }
        fittedFontSize = next
    }

    private func measuredHeight(
        fontSize: CGFloat,
        columnWidth: CGFloat,
        style: ProjectorPresentationStyle
    ) -> CGFloat {
        switch style {
        case .focus:
            return visibleEntries.reduce(0) { total, entry in
                let source = showsSource(entry) ? blockHeight(
                    entry.original,
                    fontSize: fontSize * 0.38,
                    width: columnWidth
                ) : 0
                let translation = blockHeight(
                    displayTranslation(for: entry),
                    fontSize: fontSize,
                    width: columnWidth
                )
                return total + source + translation + 38
            }
        case .split:
            let sourceHeight = visibleEntries.reduce(CGFloat(36)) { total, entry in
                total + blockHeight(entry.original, fontSize: fontSize * 0.82, width: columnWidth) + 22
            }
            let translationHeight = visibleEntries.reduce(CGFloat(36)) { total, entry in
                total + blockHeight(
                    displayTranslation(for: entry),
                    fontSize: fontSize * 0.82,
                    width: columnWidth
                ) + 22
            }
            return max(sourceHeight, translationHeight)
        case .stack:
            return visibleEntries.reduce(0) { total, entry in
                let source = showsSource(entry) ? blockHeight(
                    entry.original,
                    fontSize: fontSize * 0.72,
                    width: columnWidth
                ) : 0
                let translation = blockHeight(
                    displayTranslation(for: entry),
                    fontSize: fontSize,
                    width: columnWidth
                )
                return total + source + translation + 44
            }
        }
    }

    private func blockHeight(_ text: String, fontSize: CGFloat, width: CGFloat) -> CGFloat {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return 0 }
        let font = NSFont.systemFont(ofSize: fontSize, weight: .semibold)
        let bounding = (trimmed as NSString).boundingRect(
            with: CGSize(width: max(width, 40), height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: [.font: font]
        )
        return bounding.height
    }
}

private enum ProjectorCaptionField {
    case original
    case translation

    func text(from entry: TranscriptUtterance) -> String {
        switch self {
        case .original:
            entry.original.isEmpty ? " " : entry.original
        case .translation:
            entry.translation.isEmpty ? entry.original : entry.translation
        }
    }

    func stableLength(from entry: TranscriptUtterance) -> Int {
        switch self {
        case .original:
            entry.stableOriginalLength
        case .translation:
            entry.translation.isEmpty ? entry.stableOriginalLength : entry.stableTranslationLength
        }
    }
}

private struct ProjectorCaptionText: View {
    let text: String
    let stableLength: Int
    let isPartial: Bool
    let fontSize: CGFloat
    let weight: Font.Weight
    let color: Color
    let alignment: Alignment
    let layoutDirection: LayoutDirection

    private var stable: String {
        guard isPartial else { return text }
        return String(text.prefix(stableLength))
    }

    private var unstable: String {
        guard isPartial else { return "" }
        return String(text.dropFirst(stableLength))
    }

    var body: some View {
        (
            Text(stable).foregroundStyle(color.opacity(isPartial ? 0.85 : 1))
            + Text(unstable).foregroundStyle(color.opacity(0.62))
        )
        .font(.system(size: fontSize, weight: weight))
        .lineSpacing(4)
        .multilineTextAlignment(layoutDirection == .rightToLeft ? .trailing : .leading)
        .frame(maxWidth: .infinity, alignment: alignment)
        .environment(\.layoutDirection, layoutDirection)
    }
}
