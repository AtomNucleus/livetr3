import Combine
import SwiftUI

/// Roll-up audience captions: one continuous stream that fills from the bottom.
/// Words are revealed at a steady reading pace so a finished caption never lands
/// as a block, and a draft word turns final in place instead of moving.
struct ProjectorRollUpFeed {
    struct Word: Equatable, Identifiable {
        let id: String
        var text: String
        var isDraft: Bool
        var startsParagraph: Bool
    }

    /// Reading pace when little is waiting; a larger backlog drains with this time constant.
    static let baseWordsPerSecond = 3.0
    static let catchUpSeconds = 1.5
    /// A pause this long between captions starts a new paragraph.
    static let paragraphPause: TimeInterval = 2.0
    /// Only the newest words are kept; older ones have long scrolled out of view.
    static let maxWords = 120

    private(set) var words: [Word] = []
    private var entries: [TranscriptUtterance] = []
    private var revealed: [Int: Int] = [:]
    private var credit = 0.0
    private var idle = true
    private var lastTick: TimeInterval?

    mutating func receive(_ next: [TranscriptUtterance]) {
        guard !next.isEmpty else {
            self = Self()
            return
        }
        entries = next.sorted { $0.id < $1.id }
    }

    mutating func tick(at now: TimeInterval) {
        let elapsed = lastTick.map { min(1, max(0, now - $0)) } ?? 0
        lastTick = now
        let available = entries.map(Self.availableWords)
        for (entry, words) in zip(entries, available) where (revealed[entry.id] ?? 0) > words.count {
            // A shorter rewrite keeps its place; it never un-shows a later caption.
            revealed[entry.id] = words.count
        }
        let backlog = zip(entries, available).reduce(0) { $0 + $1.1.count - (revealed[$1.0.id] ?? 0) }
        if backlog == 0 {
            credit = 0
            idle = true
        } else {
            let pace = max(Self.baseWordsPerSecond, Double(backlog) / Self.catchUpSeconds)
            credit += elapsed * pace
            // The first word after a pause appears at once; the rest follow at reading pace.
            if idle { credit = max(credit, 1) }
            idle = false
            credit = min(credit, Double(backlog))
        }
        var budget = Int(credit)
        credit -= Double(budget)
        for (entry, words) in zip(entries, available) where budget > 0 {
            let shown = revealed[entry.id] ?? 0
            let step = min(budget, words.count - shown)
            if step > 0 {
                revealed[entry.id] = shown + step
                budget -= step
            }
        }
        rebuild(available)
    }

    private mutating func rebuild(_ available: [[String]]) {
        var next: [Word] = []
        var previous: TranscriptUtterance?
        for (entry, words) in zip(entries, available) {
            let count = min(revealed[entry.id] ?? 0, words.count)
            let pause = previous.flatMap { prior in
                prior.endedAt.map { entry.startedAt.timeIntervalSince($0) }
            } ?? 0
            for index in 0..<count {
                next.append(Word(id: "\(entry.id)-\(index)", text: words[index],
                                 isDraft: entry.state == .partial,
                                 startsParagraph: index == 0 && !next.isEmpty && pause >= Self.paragraphPause))
            }
            if count > 0 { previous = entry }
        }
        if next.count > Self.maxWords {
            next.removeFirst(next.count - Self.maxWords)
            next[0].startsParagraph = false
        }
        words = next
    }

    /// A streaming draft's last word may still be growing, so it waits for the next one.
    static func availableWords(_ entry: TranscriptUtterance) -> [String] {
        let text = entry.translation
        var words = text.split(whereSeparator: \.isWhitespace).map(String.init)
        if entry.state == .partial, let last = text.last, !last.isWhitespace,
           !".,;:!?…»”\")".contains(last), !words.isEmpty {
            words.removeLast()
        }
        return words
    }
}

struct ProjectorRollUpStage: View {
    let entries: [TranscriptUtterance]
    let layout: ProjectorCaptionLayout
    let targetLanguage: String
    var status: String?
    @State private var feed: ProjectorRollUpFeed
    private let clock = Timer.publish(every: 0.1, on: .main, in: .common).autoconnect()

    init(entries: [TranscriptUtterance], layout: ProjectorCaptionLayout, targetLanguage: String,
         status: String? = nil, feed: ProjectorRollUpFeed = ProjectorRollUpFeed()) {
        self.entries = entries
        self.layout = layout
        self.targetLanguage = targetLanguage
        self.status = status
        _feed = State(initialValue: feed)
    }

    var body: some View {
        let rtl = isRtlLanguage(targetLanguage)
        VStack(alignment: rtl ? .trailing : .leading, spacing: 12) {
            Text(targetLanguage).font(.system(size: 18, weight: .semibold)).foregroundStyle(.white.opacity(0.6))
            RollUpFlowLayout(wordSpacing: layout.fontSize * 0.27,
                             lineHeight: layout.fontSize * 1.22 + layout.lineSpacing,
                             paragraphSpacing: layout.fontSize * 0.5) {
                ForEach(feed.words) { word in
                    Text(word.text)
                        .font(.system(size: layout.fontSize, weight: .semibold))
                        .foregroundStyle(word.isDraft ? Color.white.opacity(0.6) : Color.white)
                        .fixedSize()
                        .layoutValue(key: StartsParagraph.self, value: word.startsParagraph)
                        .transition(.opacity)
                }
            }
            .animation(.easeOut(duration: 0.35), value: feed.words)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            // Older lines fade out at the top instead of being sliced by the edge.
            .mask(LinearGradient(stops: [.init(color: .clear, location: 0),
                                         .init(color: .black, location: 0.22)],
                                 startPoint: .top, endPoint: .bottom))
            .overlay {
                if feed.words.isEmpty {
                    Text("Listening…").font(.system(size: layout.fontSize)).foregroundStyle(.white.opacity(0.75))
                }
            }
            if let status {
                Text(status).font(.system(size: 18)).foregroundStyle(.orange)
            }
        }
        .environment(\.layoutDirection, rtl ? .rightToLeft : .leftToRight)
        .padding(layout.inset)
        .frame(width: layout.size.width, height: layout.size.height)
        .background(.black)
        .foregroundStyle(.white)
        .onAppear { update() }
        .onChange(of: entries) { _, _ in update() }
        .onReceive(clock) { _ in feed.tick(at: ProcessInfo.processInfo.systemUptime) }
    }

    private func update() {
        feed.receive(entries)
        feed.tick(at: ProcessInfo.processInfo.systemUptime)
    }
}

private struct StartsParagraph: LayoutValueKey {
    static let defaultValue = false
}

/// Wraps words into lines and anchors the newest line to the bottom edge, so
/// added lines push older ones up instead of reflowing the page.
struct RollUpFlowLayout: Layout {
    var wordSpacing: CGFloat
    var lineHeight: CGFloat
    var paragraphSpacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        proposal.replacingUnspecifiedDimensions(by: .zero)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var lines: [(startsParagraph: Bool, items: [(Int, CGSize)])] = []
        var x: CGFloat = 0
        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            let paragraph = subviews[index][StartsParagraph.self]
            if lines.isEmpty || paragraph || (x > 0 && x + size.width > bounds.width) {
                lines.append((paragraph, []))
                x = 0
            }
            lines[lines.count - 1].items.append((index, size))
            x += size.width + wordSpacing
        }
        var y = bounds.maxY
        for line in lines.reversed() {
            y -= lineHeight
            var x = bounds.minX
            for (index, size) in line.items {
                subviews[index].place(at: CGPoint(x: x, y: y), anchor: .topLeading,
                                      proposal: ProposedViewSize(size))
                x += size.width + wordSpacing
            }
            if line.startsParagraph { y -= paragraphSpacing }
        }
    }
}
