import Foundation

enum ProjectorPresentationStyle: String, CaseIterable, Equatable, Identifiable {
    case translationFocus
    case sideBySide
    case balancedStack

    static let storageKey = "LiveTR3.projector.presentationStyle"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .translationFocus: "Translation Focus"
        case .sideBySide: "Side by Side"
        case .balancedStack: "Balanced Stack"
        }
    }

    var description: String {
        switch self {
        case .translationFocus: "Large translation with a smaller source transcript"
        case .sideBySide: "Source and translation in separate columns"
        case .balancedStack: "Source and translation stacked at similar sizes"
        }
    }
}
