import AppKit
import SwiftUI

struct ProjectorView: View {
    @ObservedObject var connection: ProjectorConnection
    @ObservedObject var sessionManager: SessionManager
    let sourceLanguage: String
    let targetLanguage: String

    @AppStorage(ProjectorPresentationStyle.storageKey)
    private var presentationStyleRawValue = ProjectorPresentationStyle.translationFocus.rawValue

    @State private var fittedFontSize: CGFloat = 72

    private var presentationStyle: ProjectorPresentationStyle {
        ProjectorPresentationStyle(rawValue: presentationStyleRawValue) ?? .translationFocus
    }

    private var targetEntries: [TranscriptUtterance] {
        connection.transcript.entries
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

            GeometryReader { geometry in
                VStack(spacing: 0) {
                    HStack(alignment: .top, spacing: 20) {
                        if let statusText {
                            Text(statusText)
                                .font(.system(size: 18, weight: .semibold))
                                .foregroundStyle(Color.orange)
                                .textCase(.uppercase)
                                .tracking(1.5)
                                .lineLimit(1)
                                .truncationMode(.tail)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.trailing, 220)
                        }
                        Spacer(minLength: 0)
                    }
                    .frame(height: 32, alignment: .top)

                    Spacer(minLength: 18)

                    if targetEntries.isEmpty {
                        Text("Waiting for live captions")
                            .font(.system(size: min(fittedFontSize * 0.56, 64), weight: .semibold))
                            .foregroundStyle(Color.white.opacity(0.62))
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else {
                        VStack(spacing: 18) {
                            ForEach(targetEntries) { entry in
                                ProjectorCaptionCard(
                                    entry: entry,
                                    style: presentationStyle,
                                    fontSize: fittedFontSize,
                                    sourceLanguage: sourceLanguage,
                                    targetLanguage: targetLanguage
                                )
                            }
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                    }
                }
                .padding(.horizontal, 64)
                .padding(.top, 38)
                .padding(.bottom, 44)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                .onAppear {
                    refitFont(containerSize: geometry.size)
                }
                .onChange(of: targetEntries) { _, _ in
                    refitFont(containerSize: geometry.size)
                }
                .onChange(of: sessionManager.projectorFontSize) { _, _ in
                    refitFont(containerSize: geometry.size)
                }
                .onChange(of: presentationStyleRawValue) { _, _ in
                    refitFont(containerSize: geometry.size)
                }
                .onChange(of: statusText) { _, _ in
                    refitFont(containerSize: geometry.size)
                }
                .onChange(of: geometry.size) { _, newSize in
                    refitFont(containerSize: newSize)
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

    private func refitFont(containerSize: CGSize) {
        let maximumFont = CGFloat(sessionManager.projectorFontSize)
        guard !targetEntries.isEmpty else {
            fittedFontSize = maximumFont
            return
        }

        let usableWidth = max(containerSize.width - 180, 260)
        let usableHeight = max(containerSize.height - 170, 260)
        var candidate = maximumFont

        while candidate > 22 {
            let estimatedHeight = targetEntries.reduce(CGFloat.zero) { total, entry in
                total + estimatedCardHeight(entry, fontSize: candidate, width: usableWidth)
            } + CGFloat(max(0, targetEntries.count - 1)) * 18

            if estimatedHeight <= usableHeight {
                break
            }
            candidate -= 2
        }

        fittedFontSize = max(candidate, 22)
    }

    private func estimatedCardHeight(_ entry: TranscriptUtterance, fontSize: CGFloat, width: CGFloat) -> CGFloat {
        let original = entry.original
        let translation = entry.translation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && entry.state == .partial
            ? "Translating…"
            : entry.translation

        switch presentationStyle {
        case .translationFocus:
            let originalHeight = laneHeight(
                text: original,
                fontSize: fontSize * 0.48,
                width: width,
                lineLimit: 2
            )
            let translationHeight = laneHeight(
                text: translation,
                fontSize: fontSize,
                width: width,
                lineLimit: 4
            )
            return 54 + originalHeight + translationHeight

        case .sideBySide:
            let columnWidth = max((width - 42) / 2, 140)
            let originalHeight = laneHeight(
                text: original,
                fontSize: fontSize * 0.66,
                width: columnWidth,
                lineLimit: 4
            )
            let translationHeight = laneHeight(
                text: translation,
                fontSize: fontSize * 0.66,
                width: columnWidth,
                lineLimit: 4
            )
            return 40 + max(originalHeight, translationHeight)

        case .balancedStack:
            let laneFontSize = fontSize * 0.76
            return 55
                + laneHeight(text: original, fontSize: laneFontSize, width: width, lineLimit: 3)
                + laneHeight(text: translation, fontSize: laneFontSize, width: width, lineLimit: 3)
        }
    }

    private func laneHeight(text: String, fontSize: CGFloat, width: CGFloat, lineLimit: Int) -> CGFloat {
        let labelHeight: CGFloat = text.isEmpty ? 0 : 22
        guard !text.isEmpty else { return labelHeight }

        let font = NSFont.systemFont(ofSize: fontSize, weight: .semibold)
        let bounding = (text as NSString).boundingRect(
            with: CGSize(width: width, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: [.font: font]
        )
        let lineHeight = max(font.ascender - font.descender + font.leading, fontSize)
        let estimatedLines = max(1, Int(ceil(bounding.height / lineHeight)))
        let displayedLines = min(lineLimit, estimatedLines)
        return labelHeight + CGFloat(displayedLines) * lineHeight + 8
    }
}

private struct ProjectorCaptionCard: View {
    let entry: TranscriptUtterance
    let style: ProjectorPresentationStyle
    let fontSize: CGFloat
    let sourceLanguage: String
    let targetLanguage: String

    private var displayedTranslation: String {
        if entry.translation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           entry.state == .partial {
            return "Translating…"
        }
        return entry.translation
    }

    var body: some View {
        Group {
            switch style {
            case .translationFocus:
                VStack(alignment: .leading, spacing: 14) {
                    lane(
                        title: sourceLanguage,
                        text: entry.original,
                        stableLength: entry.stableOriginalLength,
                        fontSize: fontSize * 0.48,
                        lineLimit: 2,
                        tint: .white.opacity(0.74)
                    )
                    lane(
                        title: targetLanguage,
                        text: displayedTranslation,
                        stableLength: entry.stableTranslationLength,
                        fontSize: fontSize,
                        lineLimit: 4,
                        tint: .white
                    )
                }

            case .sideBySide:
                HStack(alignment: .top, spacing: 24) {
                    lane(
                        title: sourceLanguage,
                        text: entry.original,
                        stableLength: entry.stableOriginalLength,
                        fontSize: fontSize * 0.66,
                        lineLimit: 4,
                        tint: .white.opacity(0.78)
                    )

                    Rectangle()
                        .fill(Color.white.opacity(0.2))
                        .frame(width: 2, height: 88)

                    lane(
                        title: targetLanguage,
                        text: displayedTranslation,
                        stableLength: entry.stableTranslationLength,
                        fontSize: fontSize * 0.66,
                        lineLimit: 4,
                        tint: .white
                    )
                }

            case .balancedStack:
                VStack(alignment: .leading, spacing: 14) {
                    lane(
                        title: sourceLanguage,
                        text: entry.original,
                        stableLength: entry.stableOriginalLength,
                        fontSize: fontSize * 0.76,
                        lineLimit: 3,
                        tint: .white.opacity(0.88)
                    )

                    Rectangle()
                        .fill(Color.white.opacity(0.2))
                        .frame(height: 1)

                    lane(
                        title: targetLanguage,
                        text: displayedTranslation,
                        stableLength: entry.stableTranslationLength,
                        fontSize: fontSize * 0.76,
                        lineLimit: 3,
                        tint: .white
                    )
                }
            }
        }
        .padding(.horizontal, 26)
        .padding(.vertical, 20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(Color.white.opacity(entry.state == .partial ? 0.055 : 0.085))
                .overlay {
                    RoundedRectangle(cornerRadius: 20, style: .continuous)
                        .strokeBorder(Color.white.opacity(entry.state == .partial ? 0.12 : 0.2), lineWidth: 1)
                }
        }
    }

    @ViewBuilder
    private func lane(
        title: String,
        text: String,
        stableLength: Int,
        fontSize: CGFloat,
        lineLimit: Int,
        tint: Color
    ) -> some View {
        if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            ProjectorCaptionLane(
                title: title,
                text: text,
                stableLength: stableLength,
                isPartial: entry.state == .partial,
                fontSize: fontSize,
                lineLimit: lineLimit,
                tint: tint
            )
        }
    }
}

private struct ProjectorCaptionLane: View {
    let title: String
    let text: String
    let stableLength: Int
    let isPartial: Bool
    let fontSize: CGFloat
    let lineLimit: Int
    let tint: Color

    private var stableText: String {
        isPartial ? String(text.prefix(stableLength)) : text
    }

    private var unstableText: String {
        isPartial ? String(text.dropFirst(stableLength)) : ""
    }

    private var layoutDirection: LayoutDirection {
        ProjectorTextDirection.direction(for: text)
    }

    private var alignment: HorizontalAlignment {
        layoutDirection == .rightToLeft ? .trailing : .leading
    }

    var body: some View {
        VStack(alignment: alignment, spacing: 6) {
            Text(title.uppercased())
                .font(.system(size: 15, weight: .bold, design: .rounded))
                .foregroundStyle(tint.opacity(0.7))
                .tracking(2)

            (
                Text(stableText).foregroundColor(tint.opacity(isPartial ? 0.9 : 1))
                + Text(unstableText).foregroundColor(tint.opacity(0.68))
            )
            .font(.system(size: fontSize, weight: .semibold))
            .lineSpacing(max(2, fontSize * 0.045))
            .multilineTextAlignment(layoutDirection == .rightToLeft ? .trailing : .leading)
            .lineLimit(lineLimit)
            .truncationMode(.tail)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: layoutDirection == .rightToLeft ? .trailing : .leading)
            .environment(\.layoutDirection, layoutDirection)
        }
        .frame(
            maxWidth: .infinity,
            alignment: layoutDirection == .rightToLeft ? .trailing : .leading
        )
    }
}

private enum ProjectorTextDirection {
    static func direction(for text: String) -> LayoutDirection {
        guard let firstLetter = text.unicodeScalars.first(where: CharacterSet.letters.contains) else {
            return .leftToRight
        }
        let value = firstLetter.value
        let rightToLeft = (0x0590...0x08FF).contains(value)
            || (0xFB1D...0xFDFF).contains(value)
            || (0xFE70...0xFEFF).contains(value)
        return rightToLeft ? .rightToLeft : .leftToRight
    }
}
