import SwiftUI

/// Follow layout growth, rather than restarting a scroll animation for each token.
struct LiveCaptionScrollView<Content: View>: View {
    @ViewBuilder let content: () -> Content
    @State private var contentSize: CGSize = .zero
    private let bottomID = "live-caption-bottom"

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(spacing: 0) {
                    content()
                    Color.clear
                        .frame(height: 1)
                        .id(bottomID)
                }
                .background {
                    GeometryReader { geometry in
                        Color.clear.preference(
                            key: CaptionContentSizeKey.self,
                            value: geometry.size
                        )
                    }
                }
            }
            .onPreferenceChange(CaptionContentSizeKey.self) { size in
                contentSize = size
            }
            .task(id: contentSize) {
                guard contentSize.height > 0 else { return }
                // Preferences arrive during layout. Scroll after the updated anchor exists.
                await Task.yield()
                guard !Task.isCancelled else { return }
                var transaction = Transaction()
                transaction.disablesAnimations = true
                withTransaction(transaction) {
                    proxy.scrollTo(bottomID, anchor: .bottom)
                }
            }
        }
    }
}

private struct CaptionContentSizeKey: PreferenceKey {
    static let defaultValue: CGSize = .zero

    static func reduce(value: inout CGSize, nextValue: () -> CGSize) {
        let next = nextValue()
        value = CGSize(width: max(value.width, next.width), height: max(value.height, next.height))
    }
}
