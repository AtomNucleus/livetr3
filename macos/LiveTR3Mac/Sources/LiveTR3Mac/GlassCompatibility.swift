import SwiftUI

/// Liquid Glass on macOS 26+, with material fallbacks for macOS 14–15.
extension View {
    @ViewBuilder
    func liveGlassSurface(cornerRadius: CGFloat, interactive: Bool = false) -> some View {
        liveGlass(in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous), interactive: interactive)
    }

    @ViewBuilder
    func liveGlassCapsule(interactive: Bool = false, tint: Color? = nil) -> some View {
        liveGlass(in: Capsule(style: .continuous), interactive: interactive, tint: tint)
    }

    @ViewBuilder
    func liveGlass<S: InsettableShape>(in shape: S, interactive: Bool = false, tint: Color? = nil) -> some View {
        if #available(macOS 26.0, *) {
            self.glassEffect(Glass.regular.tint(tint).interactive(interactive), in: shape)
        } else {
            self.background {
                shape.fill(.ultraThinMaterial)
                if let tint { shape.fill(tint.opacity(0.18)) }
            }
            .overlay { shape.strokeBorder(.white.opacity(0.14)) }
        }
    }

    /// Lets neighbouring glass shapes blend and morph together instead of stacking.
    @ViewBuilder
    func liveGlassGroup(spacing: CGFloat? = nil) -> some View {
        if #available(macOS 26.0, *) {
            GlassEffectContainer(spacing: spacing) { self }
        } else {
            self
        }
    }

    @ViewBuilder
    func liveGlassButtonStyle(prominent: Bool = false) -> some View {
        if #available(macOS 26.0, *) {
            if prominent { self.buttonStyle(.glassProminent) } else { self.buttonStyle(.glass) }
        } else {
            if prominent { self.buttonStyle(.borderedProminent) } else { self.buttonStyle(.bordered) }
        }
    }

    /// A floating bar that scroll content passes beneath, with the system scroll-edge effect on macOS 26+.
    @ViewBuilder
    func liveSafeAreaBar<Bar: View>(edge: VerticalEdge, @ViewBuilder _ bar: () -> Bar) -> some View {
        let content = bar()
        if #available(macOS 26.0, *) {
            self.safeAreaBar(edge: edge) { content }
        } else {
            self.safeAreaInset(edge: edge) { content }
        }
    }
}
