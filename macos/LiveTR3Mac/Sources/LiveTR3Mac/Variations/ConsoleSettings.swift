import SwiftUI

// MARK: - Settings, grouped by task (per HIG_SETTINGS_FINDINGS)
//
// Controls are split into scannable, task-based groups with the most important
// caption-setup controls first, and rarely changed controls (custom vocabulary,
// advanced timing) behind progressive-disclosure. Each group is an independent
// control fragment so variations can reflow them into popovers, sidebars,
// inspectors, sheets, or glass panels without changing behavior.

// MARK: Individual control groups

struct CaptionSetupControls: View {
    @ObservedObject var model: ConsoleModel

    var body: some View {
        HStack(alignment: .bottom, spacing: 12) {
            LanguageMenuPicker(title: "Source language", selection: model.sourceBinding)
            Button("Swap next", action: model.swapDirection)
                .buttonStyle(.bordered)
            LanguageMenuPicker(title: "Target language", selection: model.targetBinding)
        }
    }
}

struct InputControls: View {
    @ObservedObject var model: ConsoleModel

    var body: some View {
        HStack(alignment: .bottom, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Microphone")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Picker("Microphone", selection: model.deviceBinding) {
                    Text("System default").tag("")
                    ForEach(model.devices) { device in
                        Text(device.name).tag(device.id)
                    }
                }
                .labelsHidden()
                .frame(maxWidth: 260)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("Voice activity")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Text("Silero VAD")
                    .font(.subheadline)
            }

            Toggle("Polish finals", isOn: model.polishBinding)
                .font(.subheadline)
        }
    }
}

struct OutputControls: View {
    @ObservedObject var model: ConsoleModel

    var body: some View {
        HStack(alignment: .bottom, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Projector font size")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                HStack {
                    Slider(value: $model.projectorFontSize, in: 36...144, step: 2)
                        .frame(minWidth: 160)
                    Text("\(Int(model.projectorFontSize))px")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(width: 48, alignment: .trailing)
                }
            }
            Button("Open Projector", action: model.openProjector)
                .buttonStyle(.borderedProminent)
        }
    }
}

struct SessionActionControls: View {
    @ObservedObject var model: ConsoleModel

    var body: some View {
        HStack(spacing: 8) {
            Button("Commit Now", action: model.commitNow)
                .disabled(model.status != .running)
            Button("Skip Next Polish", action: model.skipNextPolish)
                .disabled(model.status != .running || !model.config.polish_enabled)
            Button("Clear Transcript", action: model.clearTranscript)
        }
        .buttonStyle(.bordered)
    }
}

struct ExportControls: View {
    @ObservedObject var model: ConsoleModel

    var body: some View {
        HStack(spacing: 8) {
            Button("TXT", action: model.exportTXT)
            Button("SRT", action: model.exportSRT)
            Button("VTT", action: model.exportVTT)
        }
        .buttonStyle(.bordered)
    }
}

struct CustomVocabEditor: View {
    @ObservedObject var model: ConsoleModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Comma-separated vocabulary hints")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            TextEditor(text: model.customVocabBinding)
                .font(.body)
                .frame(minHeight: 72)
                .overlay {
                    RoundedRectangle(cornerRadius: 6)
                        .strokeBorder(.separator)
                }
        }
    }
}

struct AdvancedTimingControls: View {
    @ObservedObject var model: ConsoleModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Toggle("Code-switch aware prompting", isOn: model.codeSwitchBinding)
            HStack(spacing: 12) {
                ConsoleNumberField(title: "Partial interval (s)", value: model.doubleBinding(\.partial_interval_seconds, default: 0.25))
                ConsoleNumberField(title: "Max utterance (s)", value: model.doubleBinding(\.max_utterance_seconds, default: 12))
                ConsoleNumberField(title: "Silero threshold", value: model.doubleBinding(\.silero_threshold, default: 0.5))
            }
            HStack(spacing: 12) {
                ConsoleNumberField(title: "Speech pad (ms)", value: model.doubleBinding(\.speech_pad_ms, default: 300))
                ConsoleNumberField(title: "Min silence (ms)", value: model.doubleBinding(\.min_silence_ms, default: 150))
            }
        }
    }
}

// MARK: Panel presenter (custom section headers) — good for popovers / glass surfaces

struct ConsoleSettingsPanel: View {
    @ObservedObject var model: ConsoleModel
    var includeSessionActions = true

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            section("Caption setup") { CaptionSetupControls(model: model) }
            section("Input") { InputControls(model: model) }
            section("Output") { OutputControls(model: model) }
            if includeSessionActions {
                section("Live session actions") { SessionActionControls(model: model) }
            }
            section("Export") { ExportControls(model: model) }

            DisclosureGroup("Custom vocabulary") {
                CustomVocabEditor(model: model).padding(.top, 8)
            }
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .textCase(.uppercase)

            DisclosureGroup("Advanced timing") {
                AdvancedTimingControls(model: model).padding(.top, 8)
            }
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .textCase(.uppercase)
        }
        .padding(16)
    }

    @ViewBuilder
    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            content()
        }
        .padding(.bottom, 4)
        .overlay(alignment: .bottom) { Divider() }
    }
}

// MARK: Form presenter (native grouped sections) — good for sidebars / inspectors

struct ConsoleSettingsForm: View {
    @ObservedObject var model: ConsoleModel

    var body: some View {
        Form {
            Section("Caption setup") {
                CaptionSetupControls(model: model)
            }
            Section("Input") {
                InputControls(model: model)
            }
            Section("Output") {
                OutputControls(model: model)
            }
            Section("Live session actions") {
                SessionActionControls(model: model)
            }
            Section("Export") {
                ExportControls(model: model)
            }
            Section {
                DisclosureGroup("Custom vocabulary") {
                    CustomVocabEditor(model: model)
                }
                DisclosureGroup("Advanced timing") {
                    AdvancedTimingControls(model: model)
                }
            }
        }
        .formStyle(.grouped)
    }
}
