import AppKit
import SwiftUI

struct ProjectorView: View {
    @ObservedObject var connection: ProjectorConnection
    @ObservedObject var sessionManager: SessionManager
    @EnvironmentObject private var session: SessionController

    @State private var fittedFontSize: CGFloat = 72

    private var visibleEntries: [TranscriptUtterance] {
        connection.transcript.entries
            .filter { !$0.translation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
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
        let alignment: HorizontalAlignment = targetDirection == .rightToLeft ? .trailing : .leading
        let frameAlignment: Alignment = targetDirection == .rightToLeft ? .bottomTrailing : .bottomLeading
        return VStack(alignment: alignment, spacing: 24) {
            Spacer(minLength: 0)
            ForEach(visibleEntries) { entry in
                ProjectorCaptionText(
                    text: entry.translation,
                    stableLength: entry.stableTranslationLength,
                    isPartial: entry.state == .partial,
                    fontSize: fittedFontSize,
                    weight: .semibold,
                    alignment: frameAlignment,
                    layoutDirection: targetDirection
                )
            }
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: frameAlignment)
    }

    private var splitStage: some View {
        HStack(alignment: .center, spacing: 40) {
            if targetDirection == .rightToLeft {
                splitColumn(title: session.config.target_lang, field: .translation, direction: targetDirection)
                splitRule
                splitColumn(title: session.config.source_lang, field: .original, direction: sourceDirection)
            } else {
                splitColumn(title: session.config.source_lang, field: .original, direction: sourceDirection)
                splitRule
                splitColumn(title: session.config.target_lang, field: .translation, direction: targetDirection)
            }
        }
        .padding(.horizontal, 48)
        .padding(.vertical, 40)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    }

    private var splitRule: some View {
        Rectangle()
            .fill(Color.white.opacity(0.12))
            .frame(width: 1)
            .padding(.vertical, 48)
            .accessibilityHidden(true)
    }

    private func splitColumn(
        title: String,
        field: ProjectorCaptionField,
        direction: LayoutDirection
    ) -> some View {
        let textAlignment: Alignment = direction == .rightToLeft ? .trailing : .leading
        return VStack(alignment: direction == .rightToLeft ? .trailing : .leading, spacing: 22) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(Color.white.opacity(0.45))
                .textCase(.uppercase)
                .tracking(1.5)
                .frame(maxWidth: .infinity, alignment: textAlignment)
            ForEach(visibleEntries) { entry in
                ProjectorCaptionText(
                    text: field.text(from: entry),
                    stableLength: field.stableLength(from: entry),
                    isPartial: entry.state == .partial,
                    fontSize: fittedFontSize * field.scale,
                    weight: field.weight,
                    alignment: textAlignment,
                    layoutDirection: direction
                )
            }
        }
        .padding(.horizontal, 8)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    }

    private var stackStage: some View {
        VStack(spacing: 32) {
            ForEach(visibleEntries) { entry in
                VStack(alignment: .leading, spacing: 16) {
                    if !entry.original.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        ProjectorCaptionText(
                            text: entry.original,
                            stableLength: entry.stableOriginalLength,
                            isPartial: entry.state == .partial,
                            fontSize: fittedFontSize * 0.92,
                            weight: .semibold,
                            alignment: sourceDirection == .rightToLeft ? .trailing : .leading,
                            layoutDirection: sourceDirection
                        )
                        Rectangle()
                            .fill(Color.white.opacity(0.08))
                            .frame(height: 1)
                            .accessibilityHidden(true)
                    }
                    ProjectorCaptionText(
                        text: entry.translation,
                        stableLength: entry.stableTranslationLength,
                        isPartial: entry.state == .partial,
                        fontSize: fittedFontSize,
                        weight: .semibold,
                        alignment: targetDirection == .rightToLeft ? .trailing : .leading,
                        layoutDirection: targetDirection
                    )
                }
            }
        }
        .padding(.horizontal, 64)
        .padding(.vertical, 48)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    }

    private var sourceDirection: LayoutDirection {
        isRtlLanguage(session.config.source_lang) ? .rightToLeft : .leftToRight
    }

    private var targetDirection: LayoutDirection {
        isRtlLanguage(session.config.target_lang) ? .rightToLeft : .leftToRight
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
                total + blockHeight(entry.translation, fontSize: fontSize, width: columnWidth) + 24
            }
        case .split:
            let sourceHeight = visibleEntries.reduce(CGFloat(28)) { total, entry in
                total + blockHeight(entry.original, fontSize: fontSize * 0.72, width: columnWidth) + 22
            }
            let translationHeight = visibleEntries.reduce(CGFloat(28)) { total, entry in
                total + blockHeight(entry.translation, fontSize: fontSize, width: columnWidth) + 22
            }
            return max(sourceHeight, translationHeight)
        case .stack:
            return visibleEntries.reduce(0) { total, entry in
                let source = entry.original.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? 0
                    : blockHeight(entry.original, fontSize: fontSize * 0.92, width: columnWidth) + 16
                let translation = blockHeight(entry.translation, fontSize: fontSize, width: columnWidth)
                return total + source + translation + 32
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

    var scale: CGFloat {
        switch self {
        case .original: 0.72
        case .translation: 1
        }
    }

    var weight: Font.Weight {
        switch self {
        case .original: .medium
        case .translation: .semibold
        }
    }

    func text(from entry: TranscriptUtterance) -> String {
        switch self {
        case .original: entry.original
        case .translation: entry.translation
        }
    }

    func stableLength(from entry: TranscriptUtterance) -> Int {
        switch self {
        case .original: entry.stableOriginalLength
        case .translation: entry.stableTranslationLength
        }
    }
}

private struct ProjectorCaptionText: View {
    let text: String
    let stableLength: Int
    let isPartial: Bool
    let fontSize: CGFloat
    let weight: Font.Weight
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
            Text(stable).foregroundStyle(Color.white.opacity(isPartial ? 0.85 : 1))
            + Text(unstable).foregroundStyle(Color.white.opacity(0.65))
        )
        .font(.system(size: fontSize, weight: weight))
        .lineSpacing(4)
        .multilineTextAlignment(layoutDirection == .rightToLeft ? .trailing : .leading)
        .frame(maxWidth: .infinity, alignment: alignment)
        .environment(\.layoutDirection, layoutDirection)
    }
}
