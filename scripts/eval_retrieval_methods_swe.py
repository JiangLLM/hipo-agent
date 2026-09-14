"""Offline retrieval-method comparison on the frozen SWE-bench (django) bank of 243 items.

Tasks = the 114 held-out instances of the 2026-07-13 ablations (frozen bank, k=4).
Relevance proxy (SWE has no task templates): an item is RELEVANT to a target instance iff the
gold patch of the item's SOURCE instance touches at least one file that the target's gold patch
touches (same subsystem). Methods select top-k (k=4 as in the runs, and k=1):
  bm25@k / dense@k (bge-small, the bank's own embeddings) / hybrid@k (RRF)
  asrun-plain  = dense top-4 actually injected in abl_plain (from trajectories)
  asrun-gate   = the subset the LLM gate kept in abl_gate (from trajectories), may be empty
Metrics: precision of injected items, recall (>=1 relevant selected | relevant exists),
correct abstain when nothing relevant exists (only gate can abstain), and mean injected/task.
"""
import json, re, glob, math, collections, sys
import numpy as np, pyarrow as pa
sys.path.insert(0, 'scripts'); from eval_retrieval_methods import BM25, tok, rrf
RUN = 'runs/swe_big_django_20260712_190710/'
ABL = {'plain': 'runs/abl_plain_20260713_040638/', 'gate': 'runs/abl_gate_20260713_051518/'}
f = glob.glob('/Users/yutongs/.cache/huggingface/datasets/princeton-nlp___swe-bench_verified/**/*.arrow', recursive=True)[0]
with pa.memory_map(f) as src:
    try: T = pa.ipc.open_stream(src).read_all()
    except Exception: T = pa.ipc.open_file(src).read_all()
DS = {r['instance_id']: r for r in T.to_pylist()}
def files(inst): return set(re.findall(r'^diff --git a/(\S+)', DS[inst]['patch'], re.M))
bank = json.load(open(RUN + 'memory.json'))['reasoning']
src_of = {}
for l in open(RUN + 'events.jsonl'):
    e = json.loads(l)
    if e['kind'] in ('swe_write_l1', 'swe_write_l2'): src_of.setdefault(e['item']['title'], e['instance'])
items = [b for b in bank if b['title'] in src_of]
print(f"bank items with known source: {len(items)}/{len(bank)}")
def _walk(o):
    if isinstance(o, dict):
        for v in o.values(): yield from _walk(v)
    elif isinstance(o, list):
        for v in o: yield from _walk(v)
    elif isinstance(o, str): yield o
def injected(run, inst):
    """Titles inside the <memory> block of the first withmem attempt's trajectory (JSON-walked)."""
    for fp in sorted(fp for fp in glob.glob(run + f'trajs/{inst}.*.a*.traj.json') if '.nomem.' not in fp):
        try: d = json.load(open(fp))
        except Exception: continue
        for s in _walk(d):
            if '[strategy]' in s and '{{memory}}' not in s:      # skip the Jinja template in run config
                blk = s[s.find('<memory>'):s.find('</memory>')] if '<memory>' in s else s
                return re.findall(r'\[strategy\] (.+?): ', blk)
        return []   # no rendered memory block in this attempt -> the gate abstained
    return []
targets = sorted({json.loads(l)['instance'] for l in open(ABL['plain'] + 'events.jsonl') if '"swe_task"' in l})
from fastembed import TextEmbedding
emb = TextEmbedding(model_name='BAAI/bge-small-en-v1.5')
Q = np.asarray(list(emb.embed([DS[t]['problem_statement'][:2000] for t in targets])))
texts = [f"{b['title']}. {b['description']}" for b in items]; M = np.asarray([b['embedding'] for b in items])
bm25 = BM25(texts)
methods = ['bm25@1', 'dense@1', 'hybrid@1', 'bm25@4', 'dense@4', 'hybrid@4', 'asrun-plain(dense@4)', 'asrun-gate(llm subset)']
S = {m: collections.Counter() for m in methods}
title_of = [b['title'] for b in items]
for qi, t in enumerate(targets):
    tf = files(t); rel = {b['title'] for b in items if files(src_of[b['title']]) & tf}
    q = DS[t]['problem_statement']; bm = bm25.scores(q); cos = M @ Q[qi] / (np.linalg.norm(M, axis=1) * np.linalg.norm(Q[qi]) + 1e-9)
    ra = {i: r for r, i in enumerate(np.argsort(-bm))}; rb = {i: r for r, i in enumerate(np.argsort(-cos))}; fz = rrf(ra, rb)
    order = {'bm25': list(np.argsort(-bm)), 'dense': list(np.argsort(-cos)), 'hybrid': sorted(fz, key=fz.get, reverse=True)}
    sel = {f'{n}@1': [title_of[int(o[0])]] for n, o in order.items()}
    sel.update({f'{n}@4': [title_of[int(i)] for i in o[:4]] for n, o in order.items()})
    sel['asrun-plain(dense@4)'] = injected(ABL['plain'], t); sel['asrun-gate(llm subset)'] = injected(ABL['gate'], t)
    for m in methods:
        s = sel[m]; c = S[m]; c['tasks'] += 1; c['injected'] += len(s)
        c['rel_items'] += sum(1 for x in s if x in rel)
        if rel:
            c['with_rel'] += 1; c['hit_task'] += int(any(x in rel for x in s))
        else:
            c['without_rel'] += 1; c['correct_abstain'] += int(len(s) == 0)
print(f"targets: {len(targets)}; tasks with >=1 file-overlap-relevant item in bank: {S['bm25@1']['with_rel']}")
print("\n| method | 平均注入条数/题 | 注入条目中相关比例 (precision) | 有相关时至少命中一条 (recall) | 无相关时正确弃权 |\n|---|---|---|---|---|")
for m, c in S.items():
    prec = c['rel_items'] / c['injected'] if c['injected'] else float('nan'); rec = c['hit_task'] / c['with_rel'] if c['with_rel'] else float('nan')
    ab = c['correct_abstain'] / c['without_rel'] if c['without_rel'] else float('nan')
    print(f"| {m} | {c['injected']/c['tasks']:.2f} | {prec:.2f} | {rec:.2f} | {ab:.2f} |")
