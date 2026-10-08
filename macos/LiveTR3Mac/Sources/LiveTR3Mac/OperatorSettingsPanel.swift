import SwiftUI

/// Session settings shown in the operator window's inspector.
struct OperatorSettingsPanel: View {
    @ObservedObject var session: SessionController
    @ObservedObject var sessionManager: SessionManager

    @State private var customVocabText = ""

    var body: some View {
        Form {
            languageSection
            inputSection
            projectorSection
            vocabularySection
            advancedSection
        }
        .formStyle(.grouped)
        .onAppear {
            customVocabText = session.config.custom_vocab.joined(separator: ", ")
        }
    }

    private var languageSection: some View {
        Section("Languages") {
            languagePicker("From", symbol: "waveform", selection: sourceBinding)
            languagePicker("To", symbol: "captions.bubble", selection: targetBinding)
        }
    }

    private var inputSection: some View {
        Section("Input") {
            Picker(selection: $session.selectedDeviceID) {
                Text("System Default").tag("")
                ForEach(session.devices) { device in
                    Text(device.name).tag(device.id)
                }
            } label: {
                Label("Microphone", systemImage: "mic")
            }
            .onChange(of: session.selectedDeviceID) { _, newValue in
                session.setSelectedDeviceID(newValue)
            }

            Toggle(isOn: polishBinding) {
                Label("Polish Finals", systemImage: "wand.and.sparkles")
            }

            LabeledContent {
                Text("Silero")
            } label: {
                Label("Voice Detection", systemImage: "person.wave.2")
            }
        }
    }

    private var projectorSection: some View {
        Section {
            LabeledContent {
                ProjectorLookPicker(selection: $sessionManager.projectorStyle, iconsOnly: true)
                    .fixedSize()
            } label: {
                Label("Look", systemImage: "display")
            }

            LabeledContent {
                HStack {
                    Slider(value: $sessionManager.projectorFontSize, in: 36...144, step: 2)
                    Text("\(Int(sessionManager.projectorFontSize)) pt")
                        .monospacedDigit()
                        .foregroundStyle(.secondary)
                        .frame(width: 48, alignment: .trailing)
                }
            } label: {
                Label("Size", systemImage: "textformat.size")
            }
        } header: {
            Text("Projector")
        } footer: {
            Text(sessionManager.projectorStyle.detail)
        }
    }

    private var vocabularySection: some View {
        Section {
            TextEditor(text: $customVocabText)
                .font(.body)
                .frame(minHeight: 64)
                .scrollContentBackground(.hidden)
                .accessibilityLabel("Custom vocabulary")
                .onChange(of: customVocabText) { _, value in
                    var next = session.config
                    next.custom_vocab = value
                        .split(separator: ",")
                        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                        .filter { !$0.isEmpty }
                    session.updateConfig(next)
                }
        } header: {
            Text("Vocabulary")
        } footer: {
            Text("Names and terms, separated by commas.")
        }
    }

    private var advancedSection: some View {
        Section {
            DisclosureGroup {
                Toggle("Code-Switch Aware Prompting", isOn: codeSwitchBinding)
                numberField("Partial Interval", unit: "s", value: partialIntervalBinding)
                numberField("Max Utterance", unit: "s", value: maxUtteranceBinding)
                numberField("Silero Threshold", unit: nil, value: sileroThresholdBinding)
                numberField("Speech Pad", unit: "ms", value: speechPadBinding)
                numberField("Min Silence", unit: "ms", value: minSilenceBinding)
            } label: {
                Label("Advanced Timing", systemImage: "timer")
            }
        }
    }

    private func languagePicker(_ title: String, symbol: String, selection: Binding<String>) -> some View {
        Picker(selection: selection) {
            ForEach(LiveTR3Language.allCases) { language in
                Text(language.rawValue).tag(language.rawValue)
            }
        } label: {
            Label(title, systemImage: symbol)
        }
    }

    private func numberField(_ title: String, unit: String?, value: Binding<Double>) -> some View {
        LabeledContent(title) {
            HStack(spacing: 4) {
                TextField(title, value: value, format: .number)
                    .labelsHidden()
                    .multilineTextAlignment(.trailing)
                    .frame(width: 64)
                    .onSubmit { session.updateConfig(session.config) }
                if let unit {
                    Text(unit)
                        .foregroundStyle(.secondary)
                        .frame(width: 22, alignment: .leading)
                }
            }
        }
    }

    private var sourceBinding: Binding<String> {
        Binding(
            get: { session.config.source_lang },
            set: { newValue in
                var next = session.config
                next.source_lang = newValue
                session.updateConfig(next)
            }
        )
    }

    private var targetBinding: Binding<String> {
        Binding(
            get: { session.config.target_lang },
            set: { newValue in
                var next = session.config
                next.target_lang = newValue
                session.updateConfig(next)
            }
        )
    }

    private var polishBinding: Binding<Bool> {
        Binding(
            get: { session.config.polish_enabled },
            set: { newValue in
                var next = session.config
                next.polish_enabled = newValue
                session.updateConfig(next)
            }
        )
    }

    private var codeSwitchBinding: Binding<Bool> {
        Binding(
            get: { session.config.code_switching_enabled ?? false },
            set: { newValue in
                var next = session.config
                next.code_switching_enabled = newValue
                session.updateConfig(next)
            }
        )
    }

    private var partialIntervalBinding: Binding<Double> {
        configDoubleBinding(keyPath: \.partial_interval_seconds, defaultValue: 0.75)
    }

    private var maxUtteranceBinding: Binding<Double> {
        configDoubleBinding(keyPath: \.max_utterance_seconds, defaultValue: 6)
    }

    private var sileroThresholdBinding: Binding<Double> {
        configDoubleBinding(keyPath: \.silero_threshold, defaultValue: 0.5)
    }

    private var speechPadBinding: Binding<Double> {
        configDoubleBinding(keyPath: \.speech_pad_ms, defaultValue: 300)
    }

    private var minSilenceBinding: Binding<Double> {
        configDoubleBinding(keyPath: \.min_silence_ms, defaultValue: 600)
    }

    private func configDoubleBinding(
        keyPath: WritableKeyPath<ClientConfig, Double?>,
        defaultValue: Double
    ) -> Binding<Double> {
        Binding(
            get: { session.config[keyPath: keyPath] ?? defaultValue },
            set: { newValue in
                var next = session.config
                next[keyPath: keyPath] = newValue
                session.updateConfig(next)
            }
        )
    }
}
