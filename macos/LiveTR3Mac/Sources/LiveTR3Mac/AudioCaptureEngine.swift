import AVFoundation
import CoreAudio
import Foundation

struct AudioInputDevice: Identifiable, Equatable {
    let id: String
    let name: String
}

final class AudioCaptureEngine {
    private let engine = AVAudioEngine()
    private let targetSampleRate: Double = 16_000
    private let frameSize = 320
    private let processingQueue = DispatchQueue(label: "com.livetr3.audio-capture")

    private var onFrame: ((Data) -> Void)?
    private var onLevel: ((Float) -> Void)?
    private var resampleRatio: Double = 1
    private var pendingSamples: [Float] = []
    private var isPaused = false

    static func listInputDevices() -> [AudioInputDevice] {
        let session = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.microphone, .external],
            mediaType: .audio,
            position: .unspecified
        )
        return session.devices.map { device in
            AudioInputDevice(id: device.uniqueID, name: device.localizedName)
        }
    }

    func start(deviceID: String?, onFrame: @escaping (Data) -> Void, onLevel: @escaping (Float) -> Void) throws {
        stop()
        self.onFrame = onFrame
        self.onLevel = onLevel
        isPaused = false
        pendingSamples = []

        if let deviceID, !deviceID.isEmpty {
            try setDefaultInputDevice(uid: deviceID)
        }

        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        resampleRatio = format.sampleRate / targetSampleRate

        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1_024, format: format) { [weak self] buffer, _ in
            self?.processingQueue.async {
                self?.process(buffer: buffer)
            }
        }

        engine.prepare()
        try engine.start()
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        pendingSamples = []
        onFrame = nil
        onLevel = nil
    }

    func setPaused(_ paused: Bool) {
        processingQueue.async { [weak self] in
            self?.isPaused = paused
        }
    }

    func switchDevice(_ deviceID: String?) throws {
        let wasRunning = engine.isRunning
        if wasRunning {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
        }

        if let deviceID, !deviceID.isEmpty {
            try setDefaultInputDevice(uid: deviceID)
        }

        if wasRunning {
            let input = engine.inputNode
            let format = input.outputFormat(forBus: 0)
            resampleRatio = format.sampleRate / targetSampleRate
            pendingSamples = []

            input.installTap(onBus: 0, bufferSize: 1_024, format: format) { [weak self] buffer, _ in
                self?.processingQueue.async {
                    self?.process(buffer: buffer)
                }
            }
            try engine.start()
        }
    }

    private func process(buffer: AVAudioPCMBuffer) {
        guard let channelData = buffer.floatChannelData else { return }
        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)

        var mono = [Float](repeating: 0, count: frameCount)
        if channelCount == 1 {
            mono.withUnsafeMutableBufferPointer { destination in
                destination.baseAddress?.assign(from: channelData[0], count: frameCount)
            }
        } else {
            for index in 0..<frameCount {
                var sum: Float = 0
                for channel in 0..<channelCount {
                    sum += channelData[channel][index]
                }
                mono[index] = sum / Float(channelCount)
            }
        }

        var sumSquares: Float = 0
        for sample in mono {
            sumSquares += sample * sample
        }
        let rms = sqrt(sumSquares / Float(max(frameCount, 1)))
        onLevel?(rms)

        let resampled = resampleLinear(mono, ratio: resampleRatio)
        pendingSamples.append(contentsOf: resampled)
        emitFrames()
    }

    private func emitFrames() {
        guard !isPaused else { return }
        while pendingSamples.count >= frameSize {
            let frame = Array(pendingSamples.prefix(frameSize))
            pendingSamples.removeFirst(frameSize)
            let data = frame.withUnsafeBufferPointer { Data(buffer: $0) }
            onFrame?(data)
        }
    }

    private func resampleLinear(_ input: [Float], ratio: Double) -> [Float] {
        guard ratio != 1 else { return input }
        let outputLength = Int(Double(input.count) / ratio)
        guard outputLength > 0 else { return [] }

        var output = [Float](repeating: 0, count: outputLength)
        for index in 0..<outputLength {
            let source = Double(index) * ratio
            let lower = Int(source)
            let upper = min(lower + 1, input.count - 1)
            let fraction = Float(source - Double(lower))
            output[index] = input[lower] + (input[upper] - input[lower]) * fraction
        }
        return output
    }

    private func setDefaultInputDevice(uid targetUID: String) throws {
        var deviceID = AudioDeviceID(0)
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )

        var dataSize: UInt32 = 0
        var status = AudioObjectGetPropertyDataSize(
            AudioObjectID(kAudioObjectSystemObject),
            &address,
            0,
            nil,
            &dataSize
        )
        guard status == noErr else {
            throw LiveTR3SessionError(message: "Could not enumerate audio devices.")
        }

        let deviceCount = Int(dataSize) / MemoryLayout<AudioDeviceID>.size
        var deviceIDs = [AudioDeviceID](repeating: 0, count: deviceCount)
        status = AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject),
            &address,
            0,
            nil,
            &dataSize,
            &deviceIDs
        )
        guard status == noErr else {
            throw LiveTR3SessionError(message: "Could not read audio devices.")
        }

        for id in deviceIDs {
            var uidAddress = AudioObjectPropertyAddress(
                mSelector: kAudioDevicePropertyDeviceUID,
                mScope: kAudioObjectPropertyScopeGlobal,
                mElement: kAudioObjectPropertyElementMain
            )
            var uid: CFString = "" as CFString
            var uidSize = UInt32(MemoryLayout<CFString>.size)
            status = AudioObjectGetPropertyData(id, &uidAddress, 0, nil, &uidSize, &uid)
            if status == noErr, (uid as String) == targetUID {
                deviceID = id
                break
            }
        }

        guard deviceID != 0 else {
            throw LiveTR3SessionError(message: "Selected microphone was not found.")
        }

        var defaultInput = deviceID
        var defaultAddress = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultInputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        status = AudioObjectSetPropertyData(
            AudioObjectID(kAudioObjectSystemObject),
            &defaultAddress,
            0,
            nil,
            UInt32(MemoryLayout<AudioDeviceID>.size),
            &defaultInput
        )
        guard status == noErr else {
            throw LiveTR3SessionError(message: "Could not switch microphone input.")
        }
    }
}
