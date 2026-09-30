#!/usr/bin/env python3
"""Match operator/projector revisions in one native process, then compare live/reading policies."""
import argparse
import json
from pathlib import Path
import numpy as np


def stats(values):
    return {'count':len(values),'mean_ms':float(np.mean(values)*1000),'p95_ms':float(np.percentile(values,95)*1000),'worst_ms':float(max(values)*1000)} if values else None


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);args=parser.parse_args()
    report=[]
    texts=[]
    for path,archive in zip(sorted(args.directory.glob('[0-9]*-*.jsonl')), sorted((args.directory/'archives').glob('*/transcript.json'))):
        rows=[json.loads(l) for l in path.read_text().splitlines()]
        op=[r for r in rows if r['stage']=='store_caption' and r.get('surface')=='operator']
        pj=[r for r in rows if r['stage']=='store_caption' and r.get('surface')=='projector']
        views=[r for r in rows if r['stage']=='view_text_update_proxy' and r.get('surface')=='projector']
        display=[r for r in rows if r['stage']=='store_display_field' and r.get('surface')=='projector']
        queues=[r for r in rows if r['stage']=='projector_reading_queue']
        pages=[r for r in rows if r['stage']=='projector_page_update_proxy']
        key=lambda r:(r['utterance'],r['type'],r['source_signature'],r['translation_signature'])
        matched=[]
        for r in pj:
            candidates=[o for o in op if key(o)==key(r) and abs(o['unix']-r['unix'])<1]
            if candidates: matched.append(r['unix']-min(candidates,key=lambda o:abs(o['unix']-r['unix']))['unix'])
        lag=[]
        for page in pages:
            o=next((o for o in op if o['type']=='final' and o['utterance']==page['utterance']),None)
            if o:lag.append(page['unix']-o['unix'])
        viewlag=[]
        for v in views:
            candidates=[d for d in display if all(d[k]==v[k] for k in ['utterance','field','signature','type']) and 0<=v['unix']-d['unix']<1]
            if candidates:viewlag.append(v['unix']-candidates[-1]['unix'])
        first=[]
        for uid in sorted(set(r['utterance'] for r in pj)):
            for field in ['original','translation']:
                s=next((r for r in display if r['utterance']==uid and r['field']==field and r['chars']>0),None)
                v=next((r for r in views if r['utterance']==uid and r['field']==field and r['chars']>0),None)
                first.append({'utterance':uid,'field':field,'display_to_first_view_proxy_ms':(v['unix']-s['unix'])*1000 if s and v else None})
        last_op=max((r['unix'] for r in op if r['type']=='final'),default=0)
        last_view=max((r['unix'] for r in views if r['type']=='final'),default=0)
        transcripts=json.loads(archive.read_text())
        texts.append([(r['payload']['original'],r['payload']['translation']) for r in transcripts if r['payload']['type']=='final'])
        report.append({'run':path.stem,'policy':'reading' if queues else 'live',
            'operator_finals':len([r for r in op if r['type']=='final']),
            'projector_finals':len([r for r in pj if r['type']=='final']),
            'matched_store_revision_delta':stats(matched),'display_to_projector_view_update_proxy':stats(viewlag),
            'operator_final_to_first_reading_page_proxy':stats(lag),
            'max_reading_queue_utterances':max((r['queued_utterances'] for r in queues),default=0),
            'last_final_operator_to_projector_view_proxy_ms':(last_view-last_op)*1000 if last_view else None,
            'first_field_proxies':first})
    result={'definitions':{'signed_store_delta':'Same process uptime anchored to Unix time, matched utterance/state/text hash; negative means viewer updated first.',
            'reading_page':'First onChange of current reading page for its utterance id; burst coalescing means this only matches represented page IDs.',
            'live_view':'Actual SwiftUI onAppear/onChange; update proxy, not physical projection timestamp.'},
            'identical_final_source_and_spanish_across_runs':all(t==texts[0] for t in texts), 'runs':report}
    (args.directory/'projector-summary.json').write_text(json.dumps(result,indent=2))
    for r in report:print(json.dumps({k:v for k,v in r.items() if k!='first_field_proxies'}))
    print('Identical source and Spanish:',result['identical_final_source_and_spanish_across_runs'])

if __name__=='__main__':main()
