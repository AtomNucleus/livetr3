"""Local text-only TranslateGemma adapter. All MLX work belongs to one thread."""
MODEL = 'mlx-community/translategemma-4b-it-4bit'
REVISION = '5788ec08c047f3f2e17808101b8d9566ac930d58'


def message(text):
    return [{'role': 'user', 'content': [{'type': 'text', 'source_lang_code': 'en',
                                        'target_lang_code': 'es', 'text': text}]}]


class Translator:
    def __init__(self, path):
        from mlx_lm import load
        from mlx_lm.sample_utils import make_sampler
        self.model, self.tokenizer = load(str(path))
        self.sampler = make_sampler(temp=0)

    def translate(self, text, publish, max_tokens=256):
        from mlx_lm import stream_generate
        prompt = self.tokenizer.apply_chat_template(message(text), tokenize=True,
                                                   add_generation_prompt=True)
        if len(prompt) + max_tokens > 2048:
            raise ValueError('TranslateGemma 2K context limit exceeded')
        result, latest = '', None
        for latest in stream_generate(self.model, self.tokenizer, prompt,
                                      max_tokens=max_tokens, sampler=self.sampler):
            result += latest.text
            if result.strip():
                publish(result)
        if latest is None or latest.finish_reason != 'stop' or not result.strip():
            raise RuntimeError('Incomplete/empty translation; tentative output is not a final')
        return result.strip()
