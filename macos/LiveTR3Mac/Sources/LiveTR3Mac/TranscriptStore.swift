import Foundation

@MainActor
final class TranscriptStore: ObservableObject {
    @Published private(set) var entries: [TranscriptUtterance] = []
    @Published private(set) var displayEntries: [TranscriptUtterance] = [] {
        didSet {
            guard LatencyTrace.shared.isEnabled else { return }
            for entry in displayEntries {
                let previous = oldValue.first { $0.id == entry.id }
                for (field, text, oldText) in [("original", entry.original, previous?.original),
                                               ("translation", entry.translation, previous?.translation)] {
                    if text != oldText || previous?.state != entry.state {
                        LatencyTrace.shared.record("store_display_field", ["surface": traceLabel, "utterance": entry.id, "field": field, "chars": text.count, "signature": text.hashValue, "type": String(describing: entry.state)])
                    }
                }
            }
        }
    }
    @Published private(set) var lastError: String?
    @Published private(set) var partialTickAt: Date?
    @Published private(set) var workerStatus: (state: WorkerState, message: String)?

    private enum Field: Hashable { case original, translation }
    private struct RevisionKey: Hashable {
        let utteranceID: Int
        let field: Field
    }
    private struct Revision {
        var text: String
        let sequence: Int
    }
    private let traceLabel: String
    private let revisionDelayNanoseconds: UInt64
    private var revisionSequence = 0
    private var revisions: [RevisionKey: Revision] = [:]
    private var revisionTasks: [RevisionKey: Task<Void, Never>] = [:]

    init(revisionDelayNanoseconds: UInt64 = 250_000_000, traceLabel: String = "operator") {
        self.traceLabel = traceLabel
        self.revisionDelayNanoseconds = revisionDelayNanoseconds
    }

    func handle(_ message: LiveTR3ServerMessage) {
        switch message {
        case .error(let message):
            lastError = message
        case .status(let state, let message):
            workerStatus = (state, message)
            if state == .ready {
                lastError = nil
            }
        case .speechStart(let utteranceID):
            guard !entries.contains(where: { $0.id == utteranceID }) else { return }
            partialTickAt = Date()
        case .level:
            break
        case .caption(let type, let utteranceID, let original, let translation):
            LatencyTrace.shared.record("store_caption", LocalEngineConnection.traceFields(message).merging(["surface": traceLabel]) { _, next in next })
            lastError = nil
            if type == .partial {
                partialTickAt = Date()
            }

            let existing = entries.first(where: { $0.id == utteranceID })
            // Delayed stream callbacks must never turn a completed caption back into a draft.
            if type == .partial, let existing, existing.state != .partial { return }
            if type == .final, existing?.state == .polished { return }
            if type != .partial {
                cancelRevision(RevisionKey(utteranceID: utteranceID, field: .original))
                cancelRevision(RevisionKey(utteranceID: utteranceID, field: .translation))
            }
            let previousOriginal = existing?.original ?? ""
            let previousTranslation = existing?.translation ?? ""

            let updated = TranscriptUtterance(
                id: utteranceID,
                original: original,
                translation: translation,
                state: type,
                stableOriginalLength: type == .partial
                    ? longestCommonPrefixLength(previousOriginal, original)
                    : original.count,
                stableTranslationLength: type == .partial
                    ? longestCommonPrefixLength(previousTranslation, translation)
                    : translation.count,
                startedAt: existing?.startedAt ?? Date(),
                endedAt: type == .partial ? existing?.endedAt : Date()
            )

            if let index = entries.firstIndex(where: { $0.id == utteranceID }) {
                entries[index] = updated
            } else {
                entries.append(updated)
            }

            var displayed = updated
            if let index = displayEntries.firstIndex(where: { $0.id == utteranceID }) {
                let previous = displayEntries[index]
                if type == .partial {
                    displayed.original = draftText(previous: previous.original, candidate: original,
                                                   key: RevisionKey(utteranceID: utteranceID, field: .original))
                    displayed.translation = draftText(previous: previous.translation, candidate: translation,
                                                      key: RevisionKey(utteranceID: utteranceID, field: .translation))
                    displayed.stableOriginalLength = longestCommonPrefixLength(previous.original, displayed.original)
                    displayed.stableTranslationLength = longestCommonPrefixLength(previous.translation, displayed.translation)
                }
                if displayEntries[index] != displayed {
                    displayEntries[index] = displayed
                }
            } else {
                displayEntries.append(displayed)
            }
        }
    }

    func clearError() {
        lastError = nil
    }

    func clear() {
        for task in revisionTasks.values { task.cancel() }
        revisionTasks.removeAll()
        revisions.removeAll()
        entries = []
        displayEntries = []
        lastError = nil
        workerStatus = nil
        partialTickAt = nil
    }

    private func draftText(previous: String, candidate: String, key: RevisionKey) -> String {
        if candidate.hasPrefix(previous) {
            cancelRevision(key)
            return candidate
        }
        // A restarted decode hasn't caught up to the visible text yet.
        if previous.hasPrefix(candidate) {
            cancelRevision(key)
            return previous
        }
        if let pending = revisions[key], candidate.hasPrefix(pending.text) {
            // Token growth doesn't restart the settling window and starve the display.
            revisions[key]?.text = candidate
            return previous
        }

        cancelRevision(key)
        revisionSequence += 1
        let sequence = revisionSequence
        revisions[key] = Revision(text: candidate, sequence: sequence)
        let delay = revisionDelayNanoseconds
        revisionTasks[key] = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: delay) } catch { return }
            guard let self, let revision = self.revisions[key], revision.sequence == sequence else { return }
            self.revisions.removeValue(forKey: key)
            self.revisionTasks.removeValue(forKey: key)
            guard let index = self.displayEntries.firstIndex(where: { $0.id == key.utteranceID }),
                  self.displayEntries[index].state == .partial else { return }
            var displayed = self.displayEntries[index]
            switch key.field {
            case .original:
                displayed.stableOriginalLength = longestCommonPrefixLength(displayed.original, revision.text)
                displayed.original = revision.text
            case .translation:
                displayed.stableTranslationLength = longestCommonPrefixLength(displayed.translation, revision.text)
                displayed.translation = revision.text
            }
            self.displayEntries[index] = displayed
        }
        return previous
    }

    private func cancelRevision(_ key: RevisionKey) {
        revisionTasks.removeValue(forKey: key)?.cancel()
        revisions.removeValue(forKey: key)
    }
}
