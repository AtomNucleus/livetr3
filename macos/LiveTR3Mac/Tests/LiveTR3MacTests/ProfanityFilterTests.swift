import XCTest
@testable import LiveTR3Mac

final class ProfanityFilterTests: XCTestCase {
    func testMasksSwearWordsAndSlurs() {
        XCTAssertEqual(ProfanityFilter.clean("What the fuck is this shit"), "What the **** is this ****")
        XCTAssertEqual(ProfanityFilter.clean("Fucking hell"), "******* hell")
        XCTAssertEqual(ProfanityFilter.clean("you nigga"), "you *****")
        XCTAssertEqual(ProfanityFilter.clean("NIGGERS"), "*******")
        XCTAssertEqual(ProfanityFilter.clean("Ese pendejo, coño, qué mierda"), "Ese *******, ****, qué ******")
        XCTAssertEqual(ProfanityFilter.clean("cabrón"), "******")
    }

    func testLeavesOrdinaryWordsAlone() {
        let clean = "The class will assess Scunthorpe, hell and damnation, the cockerel, shiitake and Dickens. Construimos computadoras."
        XCTAssertEqual(ProfanityFilter.clean(clean), clean)
    }

    func testStoreMasksCaptionsOnlyWhenEnabled() async {
        await MainActor.run {
            let on = TranscriptStore(filtersProfanity: { true })
            on.handle(.caption(type: .final, utteranceID: 1, original: "oh shit", translation: "ay mierda"))
            XCTAssertEqual(on.entries[0].original, "oh ****")
            XCTAssertEqual(on.entries[0].translation, "ay ******")
            XCTAssertEqual(on.displayEntries[0].original, "oh ****")

            let off = TranscriptStore(filtersProfanity: { false })
            off.handle(.caption(type: .final, utteranceID: 1, original: "oh shit", translation: "ay mierda"))
            XCTAssertEqual(off.entries[0].original, "oh shit")
        }
    }
}
