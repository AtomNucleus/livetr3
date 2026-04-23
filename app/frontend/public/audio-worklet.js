class LiveTR3AudioWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetSampleRate = 16000;
    this.frameSize = 320;
    this.pending = [];
    this.phase = 0;
    this.levelFrames = 0;
    this.levelSum = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0] || input[0].length === 0) return true;

    const mono = input[0];
    const ratio = sampleRate / this.targetSampleRate;
    while (this.phase < mono.length) {
      const i = Math.floor(this.phase);
      const sample = Math.max(-1, Math.min(1, mono[i] || 0));
      this.pending.push(sample);
      this.levelSum += sample * sample;
      this.levelFrames += 1;
      this.phase += ratio;

      if (this.pending.length === this.frameSize) {
        const frame = new Float32Array(this.pending);
        this.port.postMessage({ type: "pcm", buffer: frame.buffer }, [frame.buffer]);
        this.pending = [];
      }
    }
    this.phase -= mono.length;

    if (this.levelFrames >= this.targetSampleRate / 10) {
      const rms = Math.sqrt(this.levelSum / this.levelFrames);
      this.port.postMessage({ type: "level", rms });
      this.levelFrames = 0;
      this.levelSum = 0;
    }
    return true;
  }
}

registerProcessor("livetr3-audio-worklet", LiveTR3AudioWorklet);

