import Foundation

/// Masks swear words and slurs in caption text before it reaches any screen or export.
enum ProfanityFilter {
    static let storageKey = "LiveTR3.filtersProfanity"

    /// On unless the operator turned it off.
    static var isEnabled: Bool {
        UserDefaults.standard.object(forKey: storageKey) as? Bool ?? true
    }

    // Stems match any ending ("fuck" covers "fucking", "fucked"); words match exactly.
    // Words with ordinary or Bible meanings (hell, damn, piss, whore, cock, ass as donkey) are left alone.
    private static let stems = [
        // English
        "fuck", "motherfuck", "shit", "bullshit", "bitch", "asshole", "cunt", "twat", "dickhead",
        "faggot", "nigg", "n1gg", "slut",
        // Spanish
        "mierd", "pendej", "cabr[oó]n", "joder", "jodid", "ching[aoáó]", "maric[oó]n", "pu[nñ]et",
        "mamabich", "mamaguevo", "hijueputa",
    ]
    private static let words = [
        "fag", "fags", "nigga", "niggas", "niggaz", "dumbass", "jackass", "bastard", "bastards",
        "puta", "putas", "puto", "putos", "co[nñ]o", "carajo", "verga", "culo",
    ]

    private static let expression: NSRegularExpression = {
        let pattern = "\\b(?:(?:\(stems.joined(separator: "|")))\\w*|(?:\(words.joined(separator: "|"))))\\b"
        // A literal pattern; a failure here is a programming error caught by the tests.
        return try! NSRegularExpression(pattern: pattern, options: [.caseInsensitive])
    }()

    static func clean(_ text: String) -> String {
        guard !text.isEmpty else { return text }
        let range = NSRange(text.startIndex..., in: text)
        let matches = expression.matches(in: text, range: range)
        guard !matches.isEmpty else { return text }
        var result = text
        for match in matches.reversed() {
            guard let wordRange = Range(match.range, in: result) else { continue }
            result.replaceSubrange(wordRange, with: String(repeating: "*", count: result[wordRange].count))
        }
        return result
    }
}
