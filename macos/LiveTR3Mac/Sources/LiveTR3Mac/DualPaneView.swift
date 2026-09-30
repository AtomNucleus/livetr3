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
            Divider()
            transcriptPane(
                title: targetLanguage,
                field: .translation,
                layoutDirection: isRtlLanguage(targetLanguage) ? .rightToLeft : .leftToRight
            )
        }
        .background(.background)
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
            .background(.bar)

            LiveCaptionScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(entries.filter { !field.text(from: $0).isEmpty }) { entry in
                        TranscriptLineView(
                            entry: entry,
                            field: field,
                            layoutDirection: layoutDirection
                        )
                        .equatable()
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 14)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
