import SwiftUI

struct DualPaneView: View {
    let entries: [TranscriptUtterance]
    let sourceLanguage: String
    let targetLanguage: String

    var body: some View {
        VStack(spacing: 0) {
            transcriptPane(
                title: sourceLanguage,
                field: .original,
                layoutDirection: isRtlLanguage(sourceLanguage) ? .rightToLeft : .leftToRight
            )
            Divider().overlay(Color.white.opacity(0.08))
            transcriptPane(
                title: targetLanguage,
                field: .translation,
                layoutDirection: isRtlLanguage(targetLanguage) ? .rightToLeft : .leftToRight
            )
        }
        .background(Color(red: 0.07, green: 0.07, blue: 0.08))
    }

    @ViewBuilder
    private func transcriptPane(
        title: String,
        field: TranscriptLineView.TranscriptField,
        layoutDirection: LayoutDirection
    ) -> some View {
        VStack(spacing: 0) {
            HStack {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
                Spacer()
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .background(Color(red: 0.1, green: 0.1, blue: 0.11))

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        ForEach(entries) { entry in
                            TranscriptLineView(
                                entry: entry,
                                field: field,
                                layoutDirection: layoutDirection
                            )
                            .id(entry.id)
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 14)
                }
                .onChange(of: entries.count) { _, _ in
                    if let last = entries.last {
                        withAnimation(.easeOut(duration: 0.15)) {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }
                .onChange(of: entries.last?.translation) { _, _ in
                    if let last = entries.last {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
