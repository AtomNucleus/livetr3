import XCTest
@testable import LiveTR3Mac

final class CaptionDraftDisplayTests: XCTestCase {
    @MainActor
    func testRevisionCatchesUpBeforeFinalAndTokenGrowthDoesNotRestartItsTimer() async throws {
        let store = TranscriptStore(revisionDelayNanoseconds: 60_000_000)
        store.handle(.caption(type: .partial, utteranceID: 1, original: "We can go", translation: "Podemos ir"))
        store.handle(.caption(type: .partial, utteranceID: 1, original: "We cannot go", translation: "No podemos ir"))
        XCTAssertEqual(store.displayEntries[0].original, "We can go")
        for suffix in [" today", " today because", " today because it", " today because it rains"] {
            try await Task.sleep(nanoseconds: 20_000_000)
            store.handle(.caption(type: .partial, utteranceID: 1,
                                  original: "We cannot go" + suffix, translation: "No podemos ir"))
        }
        XCTAssertEqual(store.displayEntries[0].original, "We cannot go today because it rains",
                       "Revised words must appear while speech continues, without waiting for a final")
        XCTAssertEqual(store.displayEntries[0].translation, "No podemos ir")
        XCTAssertEqual(store.displayEntries[0].state, .partial)
    }

    @MainActor
    func testBurstOfCompetingRevisionsPublishesOnlySettledCandidate() async throws {
        let store = TranscriptStore(revisionDelayNanoseconds: 60_000_000)
        store.handle(.caption(type: .partial, utteranceID: 1, original: "Nine boxes", translation: "Nueve cajas"))
        for (original, translation) in [("Five boxes", "Cinco cajas"), ("Ten boxes", "Diez cajas"), ("Six boxes", "Seis cajas")] {
            store.handle(.caption(type: .partial, utteranceID: 1, original: original, translation: translation))
        }
        XCTAssertEqual(store.displayEntries[0].original, "Nine boxes")
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(store.displayEntries[0].original, "Six boxes")
        XCTAssertEqual(store.displayEntries[0].translation, "Seis cajas")
    }

    @MainActor
    func testPendingRevisionsCannotOverwriteFinalOrLeakIntoNewSession() async throws {
        let store = TranscriptStore(revisionDelayNanoseconds: 30_000_000)
        store.handle(.caption(type: .partial, utteranceID: 1, original: "Nine boxes", translation: "Nueve cajas"))
        store.handle(.caption(type: .partial, utteranceID: 1, original: "Five boxes", translation: "Cinco cajas"))
        store.handle(.caption(type: .final, utteranceID: 1, original: "Ten boxes", translation: "Diez cajas"))
        try await Task.sleep(nanoseconds: 60_000_000)
        XCTAssertEqual(store.displayEntries, store.entries)
        XCTAssertEqual(store.displayEntries[0].original, "Ten boxes")
        store.clear()
        store.handle(.caption(type: .partial, utteranceID: 1, original: "Old words", translation: "Palabras viejas"))
        store.handle(.caption(type: .partial, utteranceID: 1, original: "Stale words", translation: "Palabras anteriores"))
        store.clear()
        store.handle(.caption(type: .partial, utteranceID: 1, original: "New words", translation: "Palabras nuevas"))
        try await Task.sleep(nanoseconds: 60_000_000)
        XCTAssertEqual(store.displayEntries[0].original, "New words")
        XCTAssertEqual(store.displayEntries[0].translation, "Palabras nuevas")
    }

    func testCompetingDraftsStayOffscreenAndFinalPreservesNegationAndQuantity() async {
        await MainActor.run {
            let store = TranscriptStore()
            store.handle(.caption(type: .partial, utteranceID: 1,
                                  original: "We can carry nine boxes", translation: "Podemos llevar nueve cajas"))
            for (original, translation) in [
                ("We can carry five boxes", "Podemos llevar cinco cajas"),
                ("We cannot carry five boxes", "No podemos llevar cinco cajas"),
                ("We cannot carry nine boxes", "No podemos llevar nueve cajas")
            ] {
                store.handle(.caption(type: .partial, utteranceID: 1, original: original, translation: translation))
                XCTAssertEqual(store.entries[0].original, original, "Canonical model results must remain untouched")
                XCTAssertEqual(store.entries[0].translation, translation)
                XCTAssertEqual(store.displayEntries[0].original, "We can carry nine boxes")
                XCTAssertEqual(store.displayEntries[0].translation, "Podemos llevar nueve cajas")
                XCTAssertEqual(store.displayEntries[0].state, .partial)
            }
            store.handle(.caption(type: .final, utteranceID: 1,
                                  original: "We cannot carry nine boxes", translation: "No podemos llevar nueve cajas"))
            XCTAssertEqual(store.displayEntries, store.entries)
            store.handle(.caption(type: .partial, utteranceID: 1, original: "We can", translation: "Podemos"))
            XCTAssertEqual(store.displayEntries, store.entries)
            XCTAssertEqual(store.displayEntries[0].state, .final)
            XCTAssertEqual(store.displayEntries[0].original, "We cannot carry nine boxes")
        }
    }

    func testRestartedDecodeRetainsBothLanesAndCompatibleTextKeepsStreaming() async {
        await MainActor.run {
            let store = TranscriptStore()
            store.handle(.caption(type: .partial, utteranceID: 7, original: "Good morning", translation: "Buenos días"))
            store.handle(.caption(type: .partial, utteranceID: 7, original: "Good", translation: ""))
            XCTAssertEqual(store.displayEntries[0].original, "Good morning")
            XCTAssertEqual(store.displayEntries[0].translation, "Buenos días")
            store.handle(.caption(type: .partial, utteranceID: 7,
                                  original: "Good morning everyone", translation: "Buenos días a todos"))
            XCTAssertEqual(store.displayEntries[0].original, "Good morning everyone")
            XCTAssertEqual(store.displayEntries[0].translation, "Buenos días a todos")
            XCTAssertEqual(store.displayEntries.count, 1)

            store.handle(.caption(type: .partial, utteranceID: 8, original: "A new sentence", translation: "Una frase nueva"))
            XCTAssertEqual(store.displayEntries.count, 2)
            XCTAssertEqual(store.displayEntries[1].original, "A new sentence")
            store.clear()
            XCTAssertTrue(store.displayEntries.isEmpty)
            store.handle(.caption(type: .partial, utteranceID: 7, original: "Fresh", translation: "Nuevo"))
            XCTAssertEqual(store.displayEntries[0].original, "Fresh")
        }
    }

    func testTranslationCanStartAfterSourceAndPolishedResultIsAuthoritative() async {
        await MainActor.run {
            let store = TranscriptStore()
            store.handle(.caption(type: .partial, utteranceID: 1, original: "Hello", translation: ""))
            store.handle(.caption(type: .partial, utteranceID: 1, original: "Hello", translation: "Hola"))
            XCTAssertEqual(store.displayEntries[0].translation, "Hola")
            store.handle(.caption(type: .final, utteranceID: 1, original: "Hello.", translation: "Hola."))
            store.handle(.caption(type: .polished, utteranceID: 1, original: "Hello!", translation: "¡Hola!"))
            XCTAssertEqual(store.displayEntries, store.entries)
            XCTAssertEqual(store.displayEntries[0].state, .polished)
            store.handle(.caption(type: .final, utteranceID: 1, original: "Hello.", translation: "Hola."))
            XCTAssertEqual(store.displayEntries[0].translation, "¡Hola!")
        }
    }
}
