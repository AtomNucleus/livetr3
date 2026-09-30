import SwiftUI

/// Keep space already occupied by a caption, so corrections don't pull nearby text upward.
struct StableCaptionLayout: Layout {
    var fontSize: Double

    struct Cache {
        var width: CGFloat?
        var fontSize: Double?
        var height: CGFloat = 0
    }

    func makeCache(subviews: Subviews) -> Cache { Cache() }

    func updateCache(_ cache: inout Cache, subviews: Subviews) {
        // Text and partial/final changes retain the reservation for this field.
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) -> CGSize {
        guard let child = subviews.first else { return .zero }
        let measured = child.sizeThatFits(ProposedViewSize(width: proposal.width, height: nil))
        guard let width = proposal.width, width.isFinite else { return measured }

        if cache.width != width || cache.fontSize != fontSize {
            cache.width = width
            cache.fontSize = fontSize
            cache.height = measured.height
        } else {
            cache.height = max(cache.height, measured.height)
        }
        return CGSize(width: width, height: cache.height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) {
        subviews.first?.place(
            at: bounds.origin,
            anchor: .topLeading,
            proposal: ProposedViewSize(width: bounds.width, height: nil)
        )
    }
}
