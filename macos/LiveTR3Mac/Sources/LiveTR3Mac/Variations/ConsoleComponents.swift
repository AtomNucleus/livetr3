import SwiftUI

// MARK: - Reusable building blocks shared by every interface variation.
//
// These keep the ten variations functionally identical. A variation composes
// these pieces differently; it never re-implements the underlying behavior.

/// Status dot + label + language direction.
struct ConsoleStatusBadge: View {
    @ObservedObject var model: ConsoleModel
    var compact = false

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(model.statusColor)
                .frame(width: 10, height: 10)
            Text(model.statusLabel)
                .font(.subheadline.weight(.semibold))
            if !compact {
                Text("·").foregroundStyle(.tertiary)
                Text(model.directionText)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(model.statusLabel), \(model.directionText)")
    }
}

/// Partial-result activity indicator.
struct ConsolePartialsIndicator: View {
    let active: Bool

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(Color.green)
                .frame(width: 9, height: 9)
                .opacity(active ? 1 : 0.25)
            Text("Partials")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
        }
    }
}

/// Wraps the existing waveform meter against model levels.
struct ConsoleWaveform: View {
    @ObservedObject var model: ConsoleModel

    var body: some View {
        WaveformMeterView(levels: model.levels, rms: model.levels.last ?? 0)
    }
}

/// Primary transport: Start/End + Pause/Resume.
struct ConsoleTransportControls: View {
    @ObservedObject var model: ConsoleModel
    var showPause = true

    var body: some View {
        HStack(spacing: 8) {
            Button(action: model.startStop) {
                Text(model.startStopTitle)
                    .font(.subheadline.weight(.semibold))
                    .frame(minWidth: 72)
            }
            .buttonStyle(.borderedProminent)
            .tint(model.status == .running ? .red : .accentColor)
            .disabled(model.status == .connecting)

            if showPause {
                Button(model.paused ? "Resume" : "Pause", action: model.pauseResume)
                    .buttonStyle(.bordered)
                    .disabled(model.status != .running)
            }
        }
    }
}

/// A transcript column (source or target) with a titled header and autoscroll.
struct ConsoleTranscriptPane: View {
    let title: String
    let language: String
    let entries: [TranscriptUtterance]
    let field: TranscriptLineView.TranscriptField
    var showHeader = true

    var body: some View {
        let direction: LayoutDirection = isRtlLanguage(language) ? .rightToLeft : .leftToRight
        VStack(spacing: 0) {
            if showHeader {
                HStack {
                    Text(title)
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 10)
                .background(.bar)
            }

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        ForEach(entries.filter { !field.text(from: $0).isEmpty }) { entry in
                            TranscriptLineView(
                                entry: entry,
                                field: field,
                                layoutDirection: direction
                            )
                            .id(entry.id)
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 14)
                }
                .onChange(of: entries.count) { _, _ in
                    if let last = entries.last {
                        withAnimation(.easeOut(duration: 0.15)) {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Warning / error banner strip.
struct ConsoleBannerView: View {
    let banner: ConsoleBanner

    var body: some View {
        Text(banner.text)
            .font(.subheadline)
            .foregroundStyle(banner.tint)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 20)
            .padding(.vertical, 8)
            .background(banner.tint.opacity(0.12))
    }
}

/// A language selection menu with a leading caption.
struct LanguageMenuPicker: View {
    let title: String
    @Binding var selection: String
    var maxWidth: CGFloat = 220

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Picker(title, selection: $selection) {
                ForEach(LiveTR3Language.allCases) { language in
                    Text(language.rawValue).tag(language.rawValue)
                }
            }
            .labelsHidden()
            .frame(maxWidth: maxWidth)
        }
    }
}

/// A labeled numeric tuning field.
struct ConsoleNumberField: View {
    let title: String
    @Binding var value: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            TextField(title, value: $value, format: .number)
                .textFieldStyle(.roundedBorder)
        }
        .frame(maxWidth: 180)
    }
}
