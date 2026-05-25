import SwiftUI

struct ProjectorWorkspace: View {
    @EnvironmentObject private var runtime: LiveTR3Runtime
    @Environment(\.openWindow) private var openWindow
    @AppStorage("LiveTR3.projectorFontSize") private var projectorFontSize = 72.0

    private var projectorSessionID: String {
        URLComponents(url: LiveTR3Routes.projectorURL, resolvingAgainstBaseURL: false)?
            .queryItems?
            .first(where: { $0.name == "session" })?
            .value ?? "native"
    }

    var body: some View {
        Form {
            Section {
                Button {
                    openWindow(id: "projector")
                } label: {
                    Label("Open Projector Window", systemImage: "rectangle.on.rectangle")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            } header: {
                Text("Audience Window")
            } footer: {
                Text("Opens the separate native projector window for the room display.")
            }

            Section {
                LabeledContent {
                    Text("\(Int(projectorFontSize)) px")
                        .monospacedDigit()
                } label: {
                    Text("Text size")
                }

                Slider(value: $projectorFontSize, in: 36...144, step: 2) {
                    Text("Projector text size")
                } minimumValueLabel: {
                    Text("A")
                        .font(.caption)
                } maximumValueLabel: {
                    Text("A")
                        .font(.title3)
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("Preview")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    Text("Live captions appear here")
                        .font(.system(size: min(42, max(18, projectorFontSize * 0.42)), weight: .bold))
                        .lineLimit(2)
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding(.vertical, 20)
                        .padding(.horizontal, 16)
                        .background(.black, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                        .foregroundStyle(.white)
                }
            } header: {
                Text("Caption Text")
            } footer: {
                Text("This updates the projector window live and matches the existing web operator range.")
            }

            Section {
                LabeledContent {
                    Label(runtime.state.label, systemImage: runtime.state.symbolName)
                        .foregroundStyle(runtime.state.tint)
                } label: {
                    Text("Runtime")
                }
                LabeledContent("Session", value: projectorSessionID)
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
        .padding(24)
    }
}

struct ProjectorWindow: View {
    @EnvironmentObject private var runtime: LiveTR3Runtime
    @AppStorage("LiveTR3.projectorFontSize") private var projectorFontSize = 72.0

    var body: some View {
        Group {
            if runtime.state == .ready {
                WebOperatorView(
                    url: LiveTR3Routes.projectorURL,
                    reloadToken: runtime.webReloadToken,
                    projectorFontSize: projectorFontSize
                )
            } else {
                RuntimeOverlay(state: runtime.state, message: runtime.statusMessage)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(.black)
    }
}
