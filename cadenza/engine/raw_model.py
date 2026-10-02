"""The direct library path: one loaded Gemma, one generation per phrase."""
from pathlib import Path
import re
import time

MODEL_ID = "mlx-community/gemma-4-e4b-it-8bit"
REVISION = "4255b21bd9a9d3fc807ef7abd80373f5e3a52a73"
# Google's AST prompt, with the two language placeholders filled in.
PROMPT = ("Transcribe the following speech segment in English, then translate it into Spanish. "
          "When formatting the answer, first output the transcription in English, then one "
          "newline, then output the string 'Spanish: ', then the translation in Spanish.")


def cached_model():
    path = Path.home() / ".cache/huggingface/hub/models--mlx-community--gemma-4-e4b-it-8bit/snapshots" / REVISION
    if not (path / "config.json").exists():
        raise FileNotFoundError(f"Cached Gemma revision missing: {path}")
    return path


def split_text(text):
    # This only separates the documented label; it never revises model wording.
    match = re.search(r"\nSpanish: ?", text)
    if not match:
        return text.strip(), ""
    return text[:match.start()].strip(), text[match.end():].strip()


def completed(text, finish_reason):
    source, translation = split_text(text)
    return finish_reason == "stop" and bool(source and translation)


class Gemma:
    def __init__(self, model_path=None):
        from mlx_vlm import load
        self.model, self.processor = load(str(model_path or cached_model()))

    def phrase(self, wav, progress=lambda *args: None, prompt=PROMPT):
        import soundfile as sf
        from mlx_vlm import stream_generate
        from mlx_vlm.prompt_utils import apply_chat_template
        info = sf.info(wav)
        if info.samplerate != 16000 or info.channels != 1 or not 0 < info.duration <= 29:
            raise ValueError("Expected mono 16 kHz audio, at most 29 seconds")
        formatted = apply_chat_template(self.processor, self.model.config, prompt, num_audios=1)
        start = time.monotonic()
        text, first_source, first_spanish, last = "", None, None, None
        for last in stream_generate(self.model, self.processor, formatted, audio=[str(wav)],
                                    max_tokens=512, temperature=0.0):
            text += last.text
            source, spanish = split_text(text)
            elapsed = time.monotonic() - start
            if source and first_source is None:
                first_source = elapsed
            if spanish and first_spanish is None:
                first_spanish = elapsed
            progress(text, source, spanish)
        reason = getattr(last, "finish_reason", None)
        source, spanish = split_text(text)
        return dict(raw=text, source=source, spanish=spanish,
                    complete=completed(text, reason), finish_reason=reason,
                    first_source=first_source, first_spanish=first_spanish,
                    inference=time.monotonic() - start)


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", nargs="+")
    args = parser.parse_args()
    gemma = Gemma()
    # Multiple files share one loaded model; no LiveTR3 imports or framework.
    for wav in args.audio:
        print(json.dumps(dict(audio=wav, **gemma.phrase(wav)), ensure_ascii=False), flush=True)
