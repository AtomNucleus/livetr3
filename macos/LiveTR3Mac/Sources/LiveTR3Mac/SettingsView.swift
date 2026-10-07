import SwiftUI

struct SettingsView: View {
    @AppStorage("LiveTR3.startsRuntimeAutomatically") private var startsRuntimeAutomatically = true
    @AppStorage("LiveTR3.showsAdvancedRuntimeDetails") private var showsAdvancedRuntimeDetails = false

    var body: some View {
        Form {
            Section {
                Toggle(isOn: $startsRuntimeAutomatically) {
                    Label("Start Local Engine at Launch", systemImage: "bolt.horizontal.circle")
                }
            } header: {
                Text("Local Engine")
            } footer: {
                Text("Turn off to open LiveTR3 without starting capture services.")
            }

            Section {
                Toggle(isOn: $showsAdvancedRuntimeDetails) {
                    Label("Show Advanced Engine Details", systemImage: "stethoscope")
                }
            } header: {
                Text("Diagnostics")
            } footer: {
                Text("Informational only. Capture, transcript, and projector behavior are unchanged.")
            }
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .fixedSize(horizontal: false, vertical: true)
    }
}
