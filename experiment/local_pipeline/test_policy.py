import pytest
from policy import CommitPolicy, Mailbox, Span
from runtime import message


def test_stability_and_cadence_then_final_negation_correction():
    p = CommitPolicy()
    assert p.update(1, 'We did send twenty books', False, 0, 1) is None
    assert p.update(1, 'We did send twenty books today', False, .25, 2).text == 'We did send twenty books'
    assert p.update(1, 'We did send twenty books today', False, .5, 2) is None
    assert p.update(1, 'We did not send twenty books', True, .6, 3).text == 'We did not send twenty books'
    assert p.update(1, 'obsolete draft', False, 2, 3) is None


def test_short_final_and_empty_final_are_explicit():
    p = CommitPolicy()
    assert p.update(1, 'No.', True, 1, 1).text == 'No.'
    assert p.update(2, '', True, 2, 2).text == ''


def test_whole_prefix_preserves_words_and_names():
    p = CommitPolicy()
    text = 'Maria sent 23 books, not 22, to Paul.'
    p.update(1, text, False, 0, 1)
    assert p.update(1, text, False, 1, 2).text == text


def test_pending_coalesces_but_never_evicts_other_finals():
    q = Mailbox(2)
    q.put(Span(1, 'draft', False, 0, 0))
    q.put(Span(1, 'corrected', True, 1, 1))
    q.put(Span(1, 'stale', False, 2, 2))
    q.put(Span(2, 'another final', True, 2, 2))
    with pytest.raises(RuntimeError, match='overflow'):
        q.put(Span(3, 'new', True, 3, 3))
    q.close()
    assert q.get().text == 'corrected'
    assert q.get().line == 2
    assert q.get() is None


def test_official_template_shape():
    item = message('Do not send 23 books.')[0]['content'][0]
    assert item == dict(type='text', source_lang_code='en', target_lang_code='es', text='Do not send 23 books.')


def test_translation_rejects_truncation_and_empty_stop(monkeypatch):
    import sys
    import types
    from runtime import Translator
    tokenizer = types.SimpleNamespace(apply_chat_template=lambda *a, **k:[1,2])
    translator = object.__new__(Translator)
    translator.model, translator.tokenizer, translator.sampler = None, tokenizer, None
    for text, reason in [('No envíe', 'length'), ('', 'stop')]:
        fake = types.SimpleNamespace(stream_generate=lambda *a, **k:iter([
            types.SimpleNamespace(text=text, finish_reason=reason)]))
        monkeypatch.setitem(sys.modules, 'mlx_lm', fake)
        with pytest.raises(RuntimeError, match='Incomplete/empty'):
            translator.translate('Do not send.', lambda _:None)


def test_translation_context_overflow_is_explicit(monkeypatch):
    import sys
    import types
    from runtime import Translator
    translator = object.__new__(Translator)
    translator.model, translator.sampler = None, None
    translator.tokenizer = types.SimpleNamespace(apply_chat_template=lambda *a, **k:[1]*2000)
    monkeypatch.setitem(sys.modules, 'mlx_lm', types.SimpleNamespace(stream_generate=None))
    with pytest.raises(ValueError, match='2K'):
        translator.translate('long text', lambda _:None)


def test_replay_routes_each_asr_pass_once_and_drains_finals(tmp_path, monkeypatch):
    import types
    import numpy as np
    import replay as runner
    from moonshine_voice import TranscriptEventListener
    monkeypatch.setattr(runner, 'guard', lambda:None)
    monkeypatch.setattr(runner.time, 'sleep', lambda _:None)
    class Stream:
        def __init__(self): self.calls=0
        def add_listener(self, listener): self.listener=listener
        def start(self): pass
        def close(self): pass
        def add_audio(self, audio, rate):
            self.calls+=1
            if self.calls>2: return
            line=types.SimpleNamespace(line_id=1,text='We did not send twenty-three books.',
                start_time=0,duration=.04,last_transcription_latency_ms=1)
            event=types.SimpleNamespace(line=line)
            if self.calls==1: self.listener.on_line_started(event)
            else: self.listener.on_line_updated(event)
            self.listener.on_line_text_changed(event)
        def stop(self):
            self.listener.on_line_completed(types.SimpleNamespace(line=types.SimpleNamespace(
                line_id=1,text='We did not send twenty-three books.',start_time=0,
                duration=.04,last_transcription_latency_ms=1)))
    class Translator:
        def translate(self, text, publish):
            publish('No enviamos veintitrés libros. ')
            return 'No enviamos veintitrés libros.'
    stream=Stream()
    asr=types.SimpleNamespace(create_stream=lambda **kwargs:stream)
    rows=runner.replay(Translator(),asr,np.zeros(641,dtype='float32'),tmp_path/'events.jsonl')
    assert len([r for r in rows if r['type']=='asr_partial'])==2
    assert len([r for r in rows if r['type']=='spanish_final'])==1
    assert not [r for r in rows if r['type']=='error']
    assert next(r for r in rows if r['type']=='feed_done')['samples']==641
    result=runner.summarize(rows,'We did not send twenty-three books.',641/16000)
    assert result['asr_score']['word_errors']==0
    assert result['missing_translation_lines']==[]
    assert result['duplicated_final_count']==0
    assert result['usable_final_prefix_growth']['first_translation_seconds'] is not None
