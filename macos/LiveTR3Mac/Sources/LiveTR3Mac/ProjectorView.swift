import AppKit
import SwiftUI

struct ProjectorView: View {
    @ObservedObject var connection: ProjectorConnection
    @ObservedObject var sessionManager: SessionManager

    @State private var fittedFontSize: CGFloat = 72

    private var targetEntries: [TranscriptUtterance] {
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
                }

                GeometryReader { geometry in
                    VStack(alignment: .leading, spacing: 24) {
                        Spacer(minLength: 0)
                        if targetEntries.isEmpty {
                            Text("Waiting for live captions")
                                .font(.system(size: fittedFontSize * 0.5, weight: .semibold))
                                .foregroundStyle(Color.white.opacity(0.35))
                                .textCase(.uppercase)
                                .tracking(4)
                                .frame(maxWidth: .infinity)
                        } else {
                            ForEach(targetEntries) { entry in
                                ProjectorCaptionView(
                                    entry: entry,
                                    fontSize: fittedFontSize
                                )
                            }
                        }
                    }
                    .padding(40)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                    .background(
                        RoundedRectangle(cornerRadius: 32, style: .continuous)
                            .strokeBorder(Color.white.opacity(0.1))
                            .background(
                                RoundedRectangle(cornerRadius: 32, style: .continuous)
                                    .fill(Color.white.opacity(0.03))
                            )
                    )
                    .padding(40)
                    .onAppear {
                        refitFont(containerSize: geometry.size)
                    }
                    .onChange(of: targetEntries.map(\.translation)) { _, _ in
                        refitFont(containerSize: geometry.size)
                    }
                    .onChange(of: sessionManager.projectorFontSize) { _, _ in
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

    private func refitFont(containerSize: CGSize) {
        let maxFont = CGFloat(sessionManager.projectorFontSize)
        let content = targetEntries.map(\.translation).joined(separator: "\n")
        var next = maxFont
        let usableWidth = max(containerSize.width - 160, 200)
        let usableHeight = max(containerSize.height - 160, 200)

        while next > 36 {
            let font = NSFont.systemFont(ofSize: next, weight: .semibold)
            let attributes: [NSAttributedString.Key: Any] = [.font: font]
            let bounding = (content as NSString).boundingRect(
                with: CGSize(width: usableWidth, height: .greatestFiniteMagnitude),
                options: [.usesLineFragmentOrigin, .usesFontLeading],
                attributes: attributes
            )
            let lineCount = max(1, targetEntries.count)
            let estimatedHeight = bounding.height + CGFloat(lineCount - 1) * next * 0.2
            if estimatedHeight <= usableHeight, bounding.width <= usableWidth {
                break
            }
            next -= 2
        }
        fittedFontSize = next
    }
}

private struct ProjectorCaptionView: View {
    let entry: TranscriptUtterance
    let fontSize: CGFloat

    private var isPartial: Bool { entry.state == .partial }
    private var stable: String {
        isPartial ? String(entry.translation.prefix(entry.stableTranslationLength)) : entry.translation
    }
    private var unstable: String {
        isPartial ? String(entry.translation.dropFirst(entry.stableTranslationLength)) : ""
    }

    var body: some View {
        (
            Text(stable).foregroundStyle(Color.white.opacity(isPartial ? 0.85 : 1))
            + Text(unstable).foregroundStyle(Color.white.opacity(0.65))
        )
        .font(.system(size: fontSize, weight: .semibold))
        .lineSpacing(4)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}