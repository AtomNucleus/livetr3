import SwiftUI

struct DetailRoot: View {
    @EnvironmentObject private var runtime: LiveTR3Runtime
    let selection: LiveTR3Section

    var body: some View {
        Group {
            switch selection {
            case .operatorPanel:
                OperatorWorkspace()
                    .environmentObject(runtime)
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
        .navigationTitle(selection.title)
    }
}
