import Foundation

/// Resource paths are resolved at launch, so a distributed app can be moved.
struct BundledEngineConfiguration {
    let resources: URL
    let applicationSupport: URL

    var dataDirectory: URL { applicationSupport.appending(path: "LiveTR3 Gemma MTP") }
    var socket: URL { dataDirectory.appending(path: "Runtime/engine.sock") }
    var logs: URL { dataDirectory.appending(path: "logs") }

    func environment(inheriting original: [String: String]) -> [String: String] {
        var result = original
        let engine = resources.appending(path: "Engine")
        result["MODEL_PATH"] = engine.appending(path: "models/gemma-target").path
        result["LIVETR3_MTP_MODEL"] = engine.appending(path: "models/gemma-mtp").path
        result["LIVETR3_GEMMA_MTP"] = "1"
        result["PYTHONHOME"] = engine.appending(path: "python").path
        result["PYTHONDONTWRITEBYTECODE"] = "1"
        result["PYTHONNOUSERSITE"] = "1"
        result["HF_HUB_OFFLINE"] = "1"
        result["TRANSFORMERS_OFFLINE"] = "1"
        result["HF_HOME"] = dataDirectory.appending(path: "cache/huggingface").path
        result["LIVETR3_ARCHIVE_ROOT"] = original["LIVETR3_ARCHIVE_ROOT"]
            ?? dataDirectory.appending(path: "sessions").path
        return result
    }
}
