import SwiftUI

enum ProjectorPresentationStyle: String, CaseIterable, Identifiable {
    case focus
    case split
    case stack
    case rollUp

    var id: String { rawValue }

    var title: String {
        switch self {
        case .focus: "Focus"
        case .split: "Split"
        case .stack: "Stack"
        case .rollUp: "Roll-up"
        }
    }

    var detail: String {
        switch self {
        case .focus: "Large translation only"
        case .split: "Source and translation side by side"
        case .stack: "Source and translation stacked together"
        case .rollUp: "Continuous translation that scrolls up line by line"
        }
    }

    var symbolName: String {
        switch self {
        case .focus: "rectangle.center.inset.filled"
        case .split: "rectangle.split.2x1"
        case .stack: "rectangle.split.1x2"
        case .rollUp: "text.append"
        }
    }
}

struct ProjectorLookPicker: View {
    @Binding var selection: ProjectorPresentationStyle
    var iconsOnly = false

    var body: some View {
        Picker("Projector Look", selection: $selection) {
            ForEach(ProjectorPresentationStyle.allCases) { style in
                Group {
                    if iconsOnly {
                        Image(systemName: style.symbolName)
                    } else {
                        Label(style.title, systemImage: style.symbolName)
                    }
                }
                .accessibilityLabel(style.title)
                .tag(style)
            }
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .help("Projector look: \(selection.title) — \(selection.detail)")
        .accessibilityLabel("Projector look")
        .accessibilityValue(selection.title)
        .accessibilityHint(selection.detail)
    }
}
