#!/usr/bin/env python3
"""Summarize native trace intervals; view callbacks are explicitly named proxies."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/backend/scripts'))
from recorded_validation import word_error_rate


def load(p):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def stats(values):
    return {'count': len(values), 'mean_ms': float(np.mean(values)*1000),
            'p95_ms': float(np.percentile(values,95)*1000), 'worst_ms': float(max(values)*1000)} if values else None


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    parser.add_argument('--reference', type=Path, help='Private human source reference')
    args=parser.parse_args()
    d=args.directory
    back=load(d/'backend.jsonl')
    archives=sorted((d/'archives').glob('*/transcript.json'))
    runs=[]
    traces=sorted(d.glob('[0-9]*-*.jsonl'))
    ref=(args.reference or Path(__file__).resolve().parents[1]/'app/backend/validation/sermon-clip.txt').read_text()
    for path, archive in zip(traces,archives):
        rows=load(path)
        start=next(x for x in rows if x['stage']=='replay_start')['unix']
        end=next(x for x in rows if x['stage']=='replay_end')['unix']
        subset=[x for x in back if start<=x['unix']<=end+15]
        stages=lambda name:[x for x in rows if x['stage']==name]
        frames=stages('audio_frame'); sends=stages('audio_send')
        received=[x for x in subset if x['stage']=='backend_audio']
        capture=stages('capture_process')
        converter=stages('converted')
        store=[x for x in stages('store_caption') if x.get('surface','operator')=='operator']
        captions=[x for x in stages('socket_caption') if 'utterance' in x and x.get('surface','operator')=='operator']
        views=[x for x in stages('view_text_update_proxy') if x.get('surface','operator')=='operator']
        finals=[x for x in store if x['type']=='final']
        events=json.loads(archive.read_text())
        final_payloads=[x['payload'] for x in events if x['payload']['type']=='final']
        # Char counts plus utterance/state correlate individual revisions without trace text.
        store_delays=[]
        for x in store:
            keys=('utterance','type','source_chars','translation_chars')
            match=[y for y in captions if all(y[k]==x[k] for k in keys) and 0<=x['unix']-y['unix']<1]
            if match: store_delays.append(x['unix']-match[-1]['unix'])
        view_delays=[]
        display=[x for x in stages('store_display_field') if x.get('surface')=='operator']
        if display:
            for x in views:
                match=[y for y in display if all(y[k]==x[k] for k in ['utterance','field','signature','type']) and 0<=x['unix']-y['unix']<1]
                if match: view_delays.append(x['unix']-match[-1]['unix'])
        # Older traces lacked exact display-field correlation: do not label raw revision holds as render delays.
        first_proxies=[]
        for uid in sorted(set(x['utterance'] for x in store)):
            source=next((x for x in store if x['utterance']==uid and x['source_chars']>0),None)
            target=next((x for x in store if x['utterance']==uid and x['translation_chars']>0),None)
            for field, s in [('original',source),('translation',target)]:
                v=next((x for x in views if x['utterance']==uid and x['field']==field and x['chars']>0),None)
                first_proxies.append({'utterance':uid,'field':field,'first_store_seconds':s['unix']-start if s else None,'first_view_proxy_seconds':v['unix']-start if v else None})
        complete=[x for x in subset if x['stage']=='worker_complete' and x['kind']=='ast' and x['priority']=='final']
        dispatch=[x for x in subset if x['stage']=='worker_dispatch' and x['kind']=='ast' and x['priority']=='final']
        final_lag=[]
        for payload in final_payloads:
            match=next((x for x in finals if x['utterance']==payload['utterance_id']),None)
            if match and payload.get('last_audio_frame_unix_seconds'):
                final_lag.append(match['unix']-payload['last_audio_frame_unix_seconds'])
        runs.append({'run':path.stem,'frames_sent':len(sends),'frames_received':len(received),'frames_emitted':len(frames),
                     'capture_queue':stats([x['uptime']-x['capture_uptime'] for x in capture]),
                     'convert_after_capture':stats([x['uptime']-x['capture_uptime'] for x in converter]),
                     'frame_to_send':stats([b['unix']-a['unix'] for a,b in zip(frames,sends)]),
                     'send_to_backend':stats([b['unix']-a['unix'] for a,b in zip(sends,received)]),
                     'socket_to_store':stats(store_delays),'display_to_view_update_proxy':stats(view_delays),
                     'final_worker_queue':stats([x['queue_seconds'] for x in dispatch]),
                     'final_inference':stats([x['inference_seconds'] for x in complete]),
                     'final_store_age_from_last_backend_voiced_frame':stats(final_lag),
                     'post_file_end_final_store_drain_ms':max(0,max((x['unix'] for x in finals),default=end)-end)*1000,
                     'final_count':len(finals),'duplicate_final_count':len(finals)-len(set(x['utterance'] for x in finals)),
                     'source_wer':word_error_rate(ref,' '.join(x['original'] for x in final_payloads)),
                     'errors':[x['payload'] for x in events if x['payload']['type']=='error'],
                     'first_source_and_translation_proxies':first_proxies,'archive':str(archive)})
    report={'definitions':{'cross_process':'Monotonic clocks independently anchored to Unix time once per process; clock adjustment/drift can affect submillisecond comparisons.',
                           'view_proxy':'SwiftUI onAppear/onChange for the actual cue row. No physical presentation timestamp, and LazyVStack can materialize offscreen rows.',
                           'final_age':'Last voiced frame receipt in backend to native store final; not first-word latency.',
                           'capture':'Paced file injected before native conversion at 48k; no microphone/hardware evidence.'},'runs':runs}
    (d/'summary.json').write_text(json.dumps(report,indent=2))
    for r in runs:
        print(json.dumps({k:v for k,v in r.items() if k not in ['first_source_and_translation_proxies','errors','archive']}))

if __name__=='__main__':main()
