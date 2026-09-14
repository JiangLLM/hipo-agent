"""Retrieval/selection experiment suite for the paper (offline, recorded WebArena banks).
Q1 comparisons: random / BM25 / BM25+content / dense (3 embedders) / hybrid / dense+threshold / ours(as-run gate);
   paired bootstrap CIs on recall@1 and decision accuracy; paired difference ours - best baseline.
Q2 ablations of OUR read path: (a) pool size k handed to the gate: relevant-in-top-k for each ranker (k=1..10);
   (b) embedding text: title / description / title+description (ours) / +content; (c) layer filter: L2-only pool vs L1+L2 pool
   (crowding of relevant L2 out of top-5); (d) scope filter: own-site pool vs all-sites pool (cross-site distractors);
   (e) the LLM step's marginal value: relevant-in-top-5 vs as-run recall@1.
Q3 challenge: per-site (map = near-identical task texts), bank-size buckets, distractor load.
Ground truth = same intent-template provenance (see eval_retrieval_methods.py)."""
import json, os, sys, collections, numpy as np
sys.path.insert(0, 'scripts'); from eval_retrieval_methods import BM25, rrf, load_site, META, RUNS
from fastembed import TextEmbedding
rng = np.random.default_rng(0)
EMBEDDERS = {'bge-small': 'BAAI/bge-small-en-v1.5', 'bge-base': 'BAAI/bge-base-en-v1.5', 'MiniLM-L6': 'sentence-transformers/all-MiniLM-L6-v2'}
models = {k: TextEmbedding(model_name=v) for k, v in EMBEDDERS.items()}
def emb(name, texts): return np.asarray(list(models[name].embed(list(texts)))) if len(texts) else np.zeros((0, 1))
def cosmat(M, q): return M @ q / (np.linalg.norm(M, axis=1) * np.linalg.norm(q) + 1e-9)

SITES = {}
for site, run in RUNS.items():
    items, tasks, writes, ret, nomem = load_site(site, run)
    # all L1+L2 items with source task (for the layer-filter ablation) from write events
    allmem = {it['title']: it for it in json.load(open(run + '/memory.json'))['reasoning']}
    l1w = []
    tpl_of = {e['task_id']: e['template_id'] for e in tasks}
    for l in open(run + '/events.jsonl'):
        e = json.loads(l)
        if e.get('kind') == 'wa_write_l1' and e['item']['title'] in allmem:
            l1w.append({'t': e['t'], 'task': e['task'], 'title': e['item']['title'], 'tpl': tpl_of.get(e['task'], META[e['task']].get('intent_template_id'))})
    SITES[site] = dict(items=items, tasks=tasks, writes=writes, ret=ret, allmem=allmem, l1w=l1w)
    print(f"[{site}] tasks={len(tasks)} L2={len(writes)} L1={len(l1w)}", file=sys.stderr)

# ---- precompute embeddings: 4 text variants x 3 models for L2 items; queries x 3 models ----
VARIANTS = {'title': lambda it: it['title'], 'description': lambda it: it['description'], 'title+description': lambda it: f"{it['title']}. {it['description']}", 'title+description+content': lambda it: f"{it['title']}. {it['description']} {it['content']}"}
E = {}; QE = {}
for site, D in SITES.items():
    titles = [w['title'] for w in D['writes']]; D['titles'] = titles
    for m in EMBEDDERS:
        QE[(site, m)] = emb(m, [META[e['task_id']]['intent'] for e in D['tasks']])
        for v, f in VARIANTS.items():
            if m != 'bge-small' and v != 'title+description': continue
            E[(site, m, v)] = emb(m, [f(D['items'][t]) for t in titles])
    E[(site, 'bge-small', 'L1')] = emb('bge-small', [f"{D['allmem'][w['title']]['title']}. {D['allmem'][w['title']]['description']}" for w in D['l1w']])
    print(f"[{site}] embeddings done", file=sys.stderr)

def rank_by(scores): return list(np.argsort(-scores))
per_task = []   # one record per (site, task) with selections/ranks of every method
for site, D in SITES.items():
    items, tasks, writes, ret = D['items'], D['tasks'], D['writes'], D['ret']
    texts_td = [f"{items[t]['title']}. {items[t]['description']}" for t in D['titles']]
    texts_full = [texts_td[i] + " " + items[t]['content'] for i, t in enumerate(D['titles'])]
    # cross-site distractor pool: all other sites' full L2 banks (title+description, bge-small)
    other_titles, other_E, other_tpl = [], [], []
    for s2, D2 in SITES.items():
        if s2 == site: continue
        other_titles += [f"{s2}::{t}" for t in D2['titles']]; other_E.append(E[(s2, 'bge-small', 'title+description')]); other_tpl += [w['tpl'] for w in D2['writes']]
    other_E = np.vstack(other_E)
    for qi, e in enumerate(tasks):
        tid, tpl = e['task_id'], e['template_id']
        idx = [i for i, w in enumerate(writes) if w['t'] < e['t']]
        if not idx: continue
        rel = {writes[i]['title'] for i in idx if writes[i]['tpl'] == tpl}; has_rel = bool(rel)
        intent = META[tid]['intent']
        rec = {'site': site, 'task': tid, 'has_rel': has_rel, 'n_cands': len(idx), 'n_rel': len(rel), 'sel': {}, 'rank_rel': {}, 'top5_rel': {}}
        cand_titles = [writes[i]['title'] for i in idx]
        def record(name, scores):
            order = rank_by(scores); ranked = [cand_titles[j] for j in order]
            rec['sel'][name] = ranked[0] if (len(ranked) and (np.max(scores) > 0 or 'bm25' not in name)) else None
            if has_rel:
                rec['rank_rel'][name] = next((r for r, t in enumerate(ranked) if t in rel), None)
            return order
        bm = BM25([texts_td[i] for i in idx]).scores(intent); ob = record('bm25', bm)
        record('bm25+content', BM25([texts_full[i] for i in idx]).scores(intent))
        cos = {}
        for m in EMBEDDERS:
            cos[m] = cosmat(E[(site, m, 'title+description')][idx], QE[(site, m)][qi]); record(f'dense[{m}]', cos[m])
        for v in VARIANTS:
            if v == 'title+description': continue
            record(f'dense-text[{v}]', cosmat(E[(site, 'bge-small', v)][idx], QE[(site, 'bge-small')][qi]))
        od = rank_by(cos['bge-small']); ra = {i: r for r, i in enumerate(ob)}; rb = {i: r for r, i in enumerate(od)}; fz = rrf(ra, rb)
        record('hybrid', np.asarray([fz[i] for i in range(len(idx))]))
        for tau in (0.55, 0.60, 0.65):
            top = int(np.argmax(cos['bge-small'])); rec['sel'][f'dense+thr{tau}'] = cand_titles[top] if cos['bge-small'][top] >= tau else None
        rec['sel']['random'] = cand_titles[int(rng.integers(len(idx)))]
        got = ret.get(tid, []); rec['sel']['ours(as-run)'] = got[0] if got else None
        # (c) layer filter ablation: pool = L2 + L1 written before this task; does a relevant L2 stay in dense top-5?
        l1idx = [i for i, w in enumerate(D['l1w']) if w['t'] < e['t']]
        if has_rel:
            sc_l2 = cos['bge-small']; sc_l1 = cosmat(E[(site, 'bge-small', 'L1')][l1idx], QE[(site, 'bge-small')][qi]) if l1idx else np.zeros(0)
            merged = sorted([(s, 'L2', cand_titles[j]) for j, s in enumerate(sc_l2)] + [(s, 'L1', None) for s in sc_l1], key=lambda x: -x[0])
            rec['top5_rel']['L2-only pool'] = any(t in rel for t in [cand_titles[j] for j in od[:5]])
            rec['top5_rel']['L1+L2 pool'] = any(x[1] == 'L2' and x[2] in rel for x in merged[:5])
            rec['l1_share_top5'] = float(np.mean([x[1] == 'L1' for x in merged[:5]])) if merged else 0.0
            # (d) scope filter ablation: add all other sites' L2 banks as distractors
            sc_o = cosmat(other_E, QE[(site, 'bge-small')][qi])
            merged2 = sorted([(s, cand_titles[j]) for j, s in enumerate(sc_l2)] + [(s, None) for s in sc_o], key=lambda x: -x[0])
            rec['top5_rel']['own-site pool'] = rec['top5_rel']['L2-only pool']
            rec['top5_rel']['all-sites pool'] = any(x[1] in rel for x in merged2[:5])
            rec['sel_noscope_dense'] = merged2[0][1]   # None => a foreign-site item would have been injected
            rec['foreign_share_top5'] = float(np.mean([x[1] is None for x in merged2[:5]]))
        per_task.append(rec)
json.dump(per_task, open('runs/retrieval_suite_wa.json', 'w'), ensure_ascii=False, default=float)

# ---------------- metrics ----------------
def summarize(recs, method):
    hit = inj = wr = wo = ab = 0
    for r in recs:
        s = r['sel'].get(method, None)
        if r['has_rel']: wr += 1
        else: wo += 1
        if s is not None:
            inj += 1
            if r['has_rel']:
                # relevance check needs the rel set; recompute cheaply via rank_rel presence for rankers, else via site data
                pass
    return None
# rebuild rel sets for scoring
REL = {}
for site, D in SITES.items():
    for e in D['tasks']:
        idx = [w for w in D['writes'] if w['t'] < e['t']]
        REL[(site, e['task_id'])] = {w['title'] for w in idx if w['tpl'] == e['template_id']}
def score(recs, method):
    c = collections.Counter(); per = []
    for r in recs:
        rel = REL[(r['site'], r['task'])]; s = r['sel'].get(method)
        c['tasks'] += 1
        if r['has_rel']: c['with_rel'] += 1
        else: c['without_rel'] += 1
        ok = False
        if s is not None:
            c['inj'] += 1
            if s in rel: c['hit'] += 1; ok = True
        elif not r['has_rel']: c['abstain_ok'] += 1; ok = True
        per.append((int(r['has_rel'] and s in rel) if r['has_rel'] else None, int(ok)))
    rec1 = [x for x, _ in per if x is not None]; acc = [y for _, y in per]
    return c, np.asarray(rec1), np.asarray(acc)
def bci(x, B=3000):
    if len(x) == 0: return (float('nan'),)*3
    s = rng.choice(x, (B, len(x))).mean(1); return x.mean(), np.percentile(s, 2.5), np.percentile(s, 97.5)
METHODS = ['random', 'bm25', 'bm25+content', 'dense[bge-small]', 'dense[bge-base]', 'dense[MiniLM-L6]', 'hybrid', 'dense+thr0.55', 'dense+thr0.6', 'dense+thr0.65', 'ours(as-run)']
OUT = {'comparison': [], 'recall_at_k': {}, 'ablation_text': [], 'ablation_layer': {}, 'ablation_scope': {}, 'per_site': [], 'bank_size': []}
print("\n## Q1 比较：每种方法只准选一条或弃权（五站合计）\n")
print("| method | recall@1 [95% CI] | precision | 无相关时正确弃权 | 决策准确率 [95% CI] | 注入率 |\n|---|---|---|---|---|---|")
ACC = {}
for m in METHODS:
    c, r1, acc = score(per_task, m); ACC[m] = acc
    mr, lo, hi = bci(r1); ma, alo, ahi = bci(acc)
    prec = c['hit']/max(c['inj'],1); ab = c['abstain_ok']/max(c['without_rel'],1)
    OUT['comparison'].append(dict(method=m, recall=mr, recall_ci=[lo,hi], precision=prec, abstain=ab, acc=ma, acc_ci=[alo,ahi], inject_rate=c['inj']/c['tasks']))
    print(f"| {m} | {mr:.2f} [{lo:.2f}, {hi:.2f}] | {prec:.2f} | {ab:.2f} | {ma:.2f} [{alo:.2f}, {ahi:.2f}] | {c['inj']/c['tasks']:.2f} |")
best = max((m for m in METHODS if m != 'ours(as-run)'), key=lambda m: ACC[m].mean())
d = ACC['ours(as-run)'] - ACC[best]; s = rng.choice(d, (3000, len(d))).mean(1)
print(f"\n配对差（决策准确率）ours − {best}: {d.mean():+.3f}，95% CI [{np.percentile(s,2.5):+.3f}, {np.percentile(s,97.5):+.3f}]，赢 {int((d>0).sum())} / 输 {int((d<0).sum())} / 平 {int((d==0).sum())}")
OUT['paired_vs_best'] = dict(best=best, diff=d.mean(), ci=[np.percentile(s,2.5), np.percentile(s,97.5)], win=int((d>0).sum()), lose=int((d<0).sum()))

print("\n## Q2(a) 交给门控的池子大小 k：相关经验落在各排序器 top-k 里的比例（有相关经验的题）\n")
withrel = [r for r in per_task if r['has_rel']]
print("| k | " + " | ".join(['bm25', 'bm25+content', 'dense[bge-small]', 'dense[bge-base]', 'dense[MiniLM-L6]', 'hybrid']) + " |\n|---|" + "---|"*6)
for k in (1, 2, 3, 5, 7, 10):
    row = []
    for m in ['bm25', 'bm25+content', 'dense[bge-small]', 'dense[bge-base]', 'dense[MiniLM-L6]', 'hybrid']:
        v = np.mean([r['rank_rel'].get(m) is not None and r['rank_rel'][m] < k for r in withrel]); row.append(v); OUT['recall_at_k'].setdefault(m, {})[k] = v
    print(f"| {k} | " + " | ".join(f"{v:.2f}" for v in row) + " |")
c, r1, _ = score(per_task, 'ours(as-run)'); print(f"\n对照：我们的门控从 dense top-5 池子里最终选对的比例 = {r1.mean():.2f}（池子里有相关的比例 {OUT['recall_at_k']['dense[bge-small]'][5]:.2f}，即 LLM 那一步在池子有货时选对 {r1.mean()/OUT['recall_at_k']['dense[bge-small]'][5]:.2f}）")

print("\n## Q2(b) 嵌入什么文本（dense[bge-small]，有相关经验的题）\n")
print("| 嵌入文本 | recall@1 | 相关在 top-5 |\n|---|---|---|")
for v in VARIANTS:
    m = 'dense[bge-small]' if v == 'title+description' else f'dense-text[{v}]'
    r1 = np.mean([r['rank_rel'].get(m) == 0 for r in withrel]); r5 = np.mean([r['rank_rel'].get(m) is not None and r['rank_rel'][m] < 5 for r in withrel])
    OUT['ablation_text'].append(dict(text=v, recall1=r1, recall5=r5)); print(f"| {v}{'（我们）' if v=='title+description' else ''} | {r1:.2f} | {r5:.2f} |")

print("\n## Q2(c) 先按 layer 过滤再取 top-k（有相关经验的题）\n")
for pool in ('L2-only pool', 'L1+L2 pool'):
    v = np.mean([r['top5_rel'][pool] for r in withrel]); OUT['ablation_layer'][pool] = v
print(f"相关 L2 落在 dense top-5：只看 L2 的池子 {OUT['ablation_layer']['L2-only pool']:.2f} vs L1+L2 混池 {OUT['ablation_layer']['L1+L2 pool']:.2f}；混池的 top-5 里平均 {np.mean([r['l1_share_top5'] for r in withrel]):.0%} 是 L1（系统从不注入 L1）。")
print("\n## Q2(d) 先按 scope（本站）过滤（有相关经验的题）\n")
for pool in ('own-site pool', 'all-sites pool'):
    v = np.mean([r['top5_rel'][pool] for r in withrel]); OUT['ablation_scope'][pool] = v
fs = np.mean([r['foreign_share_top5'] for r in withrel]); top1_foreign = np.mean([r['sel_noscope_dense'] is None for r in withrel])
OUT['ablation_scope']['foreign_share_top5'] = fs; OUT['ablation_scope']['top1_foreign'] = top1_foreign
print(f"相关经验落在 dense top-5：本站池 {OUT['ablation_scope']['own-site pool']:.2f} vs 五站混池 {OUT['ablation_scope']['all-sites pool']:.2f}；混池 top-5 里 {fs:.0%} 是别站的经验，top-1 有 {top1_foreign:.0%} 会把别站经验注进来。")

print("\n## Q3 挑战：分站 / 库越大越难？\n")
print("| 站 | 题数 | 有相关 | bm25 | dense[bge-small] | hybrid | ours(as-run) | ours 决策准确率 |\n|---|---|---|---|---|---|---|---|")
for site in RUNS:
    recs = [r for r in per_task if r['site'] == site]; row = {}
    for m in ('bm25', 'dense[bge-small]', 'hybrid', 'ours(as-run)'):
        c, r1, acc = score(recs, m); row[m] = (r1.mean(), acc.mean())
    OUT['per_site'].append(dict(site=site, n=len(recs), with_rel=int(sum(r['has_rel'] for r in recs)), **{m: row[m][0] for m in row}, ours_acc=row['ours(as-run)'][1]))
    print(f"| {site} | {len(recs)} | {sum(r['has_rel'] for r in recs)} | {row['bm25'][0]:.2f} | {row['dense[bge-small]'][0]:.2f} | {row['hybrid'][0]:.2f} | {row['ours(as-run)'][0]:.2f} | {row['ours(as-run)'][1]:.2f} |")
print("\n| 候选库大小 | 题数（有相关） | bm25 | dense[bge-small] | hybrid | ours(as-run) |\n|---|---|---|---|---|---|")
for lo, hi in ((1, 10), (11, 30), (31, 60), (61, 1000)):
    recs = [r for r in per_task if lo <= r['n_cands'] <= hi]; row = {}
    for m in ('bm25', 'dense[bge-small]', 'hybrid', 'ours(as-run)'):
        c, r1, acc = score(recs, m); row[m] = r1.mean() if len(r1) else float('nan')
    OUT['bank_size'].append(dict(bucket=f"{lo}-{hi}", n=len(recs), with_rel=int(sum(r['has_rel'] for r in recs)), **row))
    print(f"| {lo}–{hi if hi<1000 else '+'} | {len(recs)}（{sum(r['has_rel'] for r in recs)}） | " + " | ".join(f"{row[m]:.2f}" for m in ('bm25', 'dense[bge-small]', 'hybrid', 'ours(as-run)')) + " |")
json.dump(OUT, open('runs/retrieval_suite_summary.json', 'w'), ensure_ascii=False, default=float)
