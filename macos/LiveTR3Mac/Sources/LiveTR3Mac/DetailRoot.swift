import SwiftUI

struct DetailRoot: View {
    @EnvironmentObject private var runtime: LiveTR3Runtime
    let selection: LiveTR3Section

    var body: some View {
        ZStack {
            OperatorWorkspace()
                .environmentObject(runtime)
                .opacity(selection == .operatorPanel ? 1 : 0)
                .allowsHitTesting(selection == .operatorPanel)
                .accessibilityHidden(selection != .operatorPanel)

            selectedWorkspace
                .opacity(selection == .operatorPanel ? 0 : 1)
                .allowsHitTesting(selection != .operatorPanel)
                .accessibilityHidden(selection == .operatorPanel)
        }
        .navigationTitle(selection.title)
    }

    @ViewBuilder
    private var selectedWorkspace: some View {
        switch selection {
        case .operatorPanel:
            EmptyView()
        case .projector:
            ProjectorWorkspace()
                .environmentObject(runtime)
        case .runtime:
            RuntimeWorkspace()
                .environmentObject(runtime)
        case .archive:
            ArchiveWorkspace()
        }
    }
}
