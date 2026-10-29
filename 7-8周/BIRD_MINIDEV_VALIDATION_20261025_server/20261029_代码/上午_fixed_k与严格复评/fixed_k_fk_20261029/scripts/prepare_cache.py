#!/usr/bin/env python3
"""Reuse only identical BIRD prompts and corresponding deterministic scores."""
import argparse
import hashlib
import json
from pathlib import Path

MODELS = ('qwen3_0_6b','qwen3_1_7b','qwen3_4b','qwen2_5_coder_1_5b','api_control')
def read(path):
    return [json.loads(s) for s in path.open() if s.strip()] if path.exists() else []
def key(row):
    return (row['db_id'],row['database_path'],row['gold_sql'],row['question'],
            row.get('evidence') or '',row['schema_text'])
def family(row):
    p=row['perturbation']; return f"{p['family']}_{p['level']}"
def write(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source-root',type=Path,required=True)
    ap.add_argument('--run-root',type=Path,required=True)
    a=ap.parse_args()
    source={r['variant_id']:r for r in read(a.source_root/'variants/budget_variants.jsonl')}
    target=read(a.run_root/'variants/fixed_variants.jsonl')
    if len(target)!=2000: raise ValueError('Expected 2000 fixed variants')
    summary={}
    for model in MODELS:
        cache={}
        for pred in read(a.source_root/'predictions'/f'{model}.jsonl'):
            if pred.get('error') is None and pred['variant_id'] in source:
                cache.setdefault(key(source[pred['variant_id']]),pred)
        scores={r['variant_id']:r for r in read(a.source_root/'scores'/f'{model}.jsonl')}
        out={r['variant_id']:r for r in read(a.run_root/'predictions'/f'{model}.jsonl')}
        sout={r['variant_id']:r for r in read(a.run_root/'scores'/f'{model}.jsonl')}
        reused=0
        for row in target:
            vid=row['variant_id']
            if vid in out: continue
            pred=cache.get(key(row))
            if not pred: continue
            prev=pred['variant_id']
            out[vid]={**pred,'variant_id':vid,'family':family(row),
                      'reused_prompt_from_variant_id':prev,'reused_from_run':str(a.source_root)}
            reused+=1
            score=scores.get(prev)
            if score and score.get('evaluation_status')!='evaluation_error' and score.get('predicted_sql')==pred['predicted_sql'] and score.get('gold_sql')==row['gold_sql']:
                errors=str(score.get('prediction_error') or '')+str(score.get('evaluation_error') or '')
                if not any(term in errors.lower() for term in ('timeout', 'timed out', 'interrupted')):
                    sout[vid]={**score,'variant_id':vid,'family':family(row),
                               'reused_score_from_variant_id':prev,'reused_from_run':str(a.source_root)}
        write(a.run_root/'predictions'/f'{model}.jsonl',list(out.values()))
        write(a.run_root/'scores'/f'{model}.jsonl',list(sout.values()))
        summary[model]={'predictions_cached':len(out),'scores_cached':len(sout),'new_predictions_needed':2000-len(out)}
    write(a.run_root/'cache_manifest.jsonl',[{'model':m,**x} for m,x in summary.items()])
    print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
