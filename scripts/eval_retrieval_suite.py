"""Retrieval/selection experiment suite (offline, recorded WebArena banks). See RETRIEVAL_METHODS_EVAL.md.
Pool cutoff = the task's live wa_retrieve timestamp (never its own L2). Two relevance definitions:
  GT-A same-template provenance;  GT-B same-template AND the source task had >=1 genuine success.
Arms: random / always-abstain / BM25 / BM25+content / dense (3 embedders) / hybrid RRF / dense+tau (tau grid, plus
per-site test-tuned tau = an optimistic baseline) / ours(as-run gate). Paired bootstrap over tasks."""
import json, sys, collections, numpy as np
sys.path.insert(0, 'scripts'); from eval_retrieval_methods import BM25, rrf, load_site, META, RUNS
from fastembed import TextEmbedding
rng = np.random.default_rng(0)
EMBEDDERS = {'bge-small': 'BAAI/bge-small-en-v1.5', 'bge-base': 'BAAI/bge-base-en-v1.5', 'MiniLM-L6': 'sentence-transformers/all-MiniLM-L6-v2'}
models = {k: TextEmbedding(model_name=v) for k, v in EMBEDDERS.items()}
def emb(name, texts): return np.asarray(list(models[name].embed(list(texts)))) if len(texts) else np.zeros((0, 1))
def cosmat(M, q): return M @ q / (np.linalg.norm(M, axis=1) * np.linalg.norm(q) + 1e-9)
TAUS = (0.55, 0.60, 0.65, 0.70, 0.75)
SITES = {}
for site, run in RUNS.items():
    items, tasks, writes, ret, nomem = load_site(site, run)
    allmem = {it['title']: it for it in json.load(open(run + '/memory.json'))['reasoning']}
    tpl_of = {e['task_id']: e['template_id'] for e in tasks}; l1w = []
    for l in open(run + '/events.jsonl'):
        e = json.loads(l)
        if e.get('kind') == 'wa_write_l1' and e['item']['title'] in allmem:
            l1w.append({'t': e['t'], 'task': e['task'], 'title': e['item']['title'], 'tpl': tpl_of.get(e['task'], META[e['task']].get('intent_template_id'))})
    SITES[site] = dict(items=items, tasks=tasks, writes=writes, ret=ret, nomem=nomem, allmem=allmem, l1w=l1w, titles=[w['title'] for w in writes])
VARIANTS = {'title': lambda it: it['title'], 'description': lambda it: it['description'], 'title+description': lambda it: f"{it['title']}. {it['description']}", 'title+description+content': lambda it: f"{it['title']}. {it['description']} {it['content']}"}
E, QE = {}, {}
for site, D in SITES.items():
    for m in EMBEDDERS:
        QE[(site, m)] = emb(m, [META[e['task_id']]['intent'] for e in D['tasks']])
        for v, f in VARIANTS.items():
            if m != 'bge-small' and v != 'title+description': continue
            E[(site, m, v)] = emb(m, [f(D['items'][t]) for t in D['titles']])
    E[(site, 'bge-small', 'L1')] = emb('bge-small', [f"{D['allmem'][w['title']]['title']}. {D['allmem'][w['title']]['description']}" for w in D['l1w']])
    print(f"[{site}] embeddings done", file=sys.stderr)

per_task = []
for site, D in SITES.items():
    items, tasks, writes, ret, nomem = D['items'], D['tasks'], D['writes'], D['ret'], D['nomem']
    texts_td = [f"{items[t]['title']}. {items[t]['description']}" for t in D['titles']]; texts_full = [texts_td[i] + " " + items[t]['content'] for i, t in enumerate(D['titles'])]
    other_E = np.vstack([E[(s2, 'bge-small', 'title+description')] for s2 in SITES if s2 != site])
    for qi, e in enumerate(tasks):
        tid, tpl = e['task_id'], e['template_id']
        if tid not in ret: continue                       # no live retrieve record (all rollouts died) -> excluded from all arms
        cut = ret[tid]['t']
        idx = [i for i, w in enumerate(writes) if w['t'] < cut]
        if not idx: continue
        cand = [writes[i]['title'] for i in idx]
        relA = {writes[i]['title'] for i in idx if writes[i]['tpl'] == tpl}
        relB = {writes[i]['title'] for i in idx if writes[i]['tpl'] == tpl and (writes[i]['nc'] or 0) >= 1}
        intent = META[tid]['intent']
        rec = {'site': site, 'task': tid, 'n_cands': len(idx), 'relA': sorted(relA), 'relB': sorted(relB), 'sel': {}, 'rank': {}, 'top5': {}}
        def record(name, scores, abstain_zero=False):
            order = list(np.argsort(-scores)); ranked = [cand[j] for j in order]
            rec['sel'][name] = None if (abstain_zero and np.max(scores) <= 0) else ranked[0]
            rec['rank'][name] = ranked; return order
        bm = BM25([texts_td[i] for i in idx]).scores(intent); ob = record('bm25', bm, True)
        record('bm25+content', BM25([texts_full[i] for i in idx]).scores(intent), True)
        cos = {}
        for m in EMBEDDERS:
            cos[m] = cosmat(E[(site, m, 'title+description')][idx], QE[(site, m)][qi]); record(f'dense[{m}]', cos[m])
        for v in VARIANTS:
            if v != 'title+description': record(f'dense-text[{v}]', cosmat(E[(site, 'bge-small', v)][idx], QE[(site, 'bge-small')][qi]))
        od = list(np.argsort(-cos['bge-small'])); fz = rrf({i: r for r, i in enumerate(ob)}, {i: r for r, i in enumerate(od)})
        record('hybrid', np.asarray([fz[i] for i in range(len(idx))]))
        top = int(np.argmax(cos['bge-small'])); rec['top_cos'] = float(cos['bge-small'][top])
        for tau in TAUS: rec['sel'][f'dense+thr{tau}'] = cand[top] if cos['bge-small'][top] >= tau else None
        rec['sel']['random'] = cand[int(rng.integers(len(idx)))]; rec['sel']['always-abstain'] = None
        got = ret[tid]['titles']; rec['sel']['ours(as-run)'] = got[0] if got else None
        # ablations (c)(d): does a relevant L2 survive in dense top-5 under wider pools
        l1idx = [i for i, w in enumerate(D['l1w']) if w['t'] < cut]
        sc_l1 = cosmat(E[(site, 'bge-small', 'L1')][l1idx], QE[(site, 'bge-small')][qi]) if l1idx else np.zeros(0)
        merged = sorted([(s, cand[j]) for j, s in enumerate(cos['bge-small'])] + [(s, None) for s in sc_l1], key=lambda x: -x[0])[:5]
        rec['top5']['L2-only'] = [cand[j] for j in od[:5]]; rec['top5']['L1+L2'] = [x[1] for x in merged]
        sc_o = cosmat(other_E, QE[(site, 'bge-small')][qi])
        merged2 = sorted([(s, cand[j]) for j, s in enumerate(cos['bge-small'])] + [(s, 'FOREIGN') for s in sc_o], key=lambda x: -x[0])[:5]
        rec['top5']['all-sites'] = [x[1] for x in merged2]
        # outcome of this task (for the validity check of the relevance label)
        nm = nomem.get(tid); rec['delta'] = (e['nc'] - nm['nc']) if nm and e['n'] and nm['n'] else None
        rec['src_nc'] = {writes[i]['title']: (writes[i]['nc'] or 0) for i in idx}; rec['tpl_of'] = {writes[i]['title']: writes[i]['tpl'] for i in idx}; rec['tpl'] = tpl
        per_task.append(rec)
json.dump(per_task, open('runs/retrieval_suite_wa.json', 'w'), ensure_ascii=False, default=float)

# ------------- scoring -------------
def score(recs, method, gt='relA'):
    c = collections.Counter(); rec1, acc = [], []
    for r in recs:
        rel = set(r[gt]); s = r['sel'].get(method); has = bool(rel)
        c['tasks'] += 1; c['with_rel' if has else 'without_rel'] += 1
        ok = False
        if s is not None:
            c['inj'] += 1
            if s in rel: c['hit'] += 1; ok = True
        elif not has: c['abstain_ok'] += 1; ok = True
        if has: rec1.append(int(s in rel))
        acc.append(int(ok))
    return c, np.asarray(rec1), np.asarray(acc)
def bci(x, B=3000):
    if len(x) == 0: return (float('nan'),) * 3
    s = rng.choice(x, (B, len(x))).mean(1); return float(x.mean()), float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5))
def paired(a, b):
    d = a - b; s = rng.choice(d, (3000, len(d))).mean(1)
    return dict(diff=float(d.mean()), ci=[float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5))], win=int((d > 0).sum()), lose=int((d < 0).sum()), tie=int((d == 0).sum()))
# per-site test-tuned tau (optimistic baseline)
for site in RUNS:
    recs = [r for r in per_task if r['site'] == site]
    best = max(TAUS + (0.5, 0.8, 0.85), key=lambda t: np.mean([int((r['top_cos'] >= t and r['sel']['dense[bge-small]'] in r['relA']) or (r['top_cos'] < t and not r['relA'])) for r in recs]))
    for r in recs: r['sel']['dense+tau*(per-site, test-tuned)'] = r['sel']['dense[bge-small]'] if r['top_cos'] >= best else None; r['tau_star'] = best
METHODS = ['random', 'always-abstain', 'bm25', 'bm25+content', 'dense[bge-small]', 'dense[bge-base]', 'dense[MiniLM-L6]', 'hybrid'] + [f'dense+thr{t}' for t in TAUS] + ['dense+tau*(per-site, test-tuned)', 'ours(as-run)']
OUT = {'n_tasks': len(per_task), 'comparison': {}, 'paired': {}, 'recall_at_k': {}, 'ablation_text': [], 'ablation_layer': {}, 'ablation_scope': {}, 'per_site': [], 'bank_size_by_site': {}, 'validity': {}, 'tau_star': {s: [r['tau_star'] for r in per_task if r['site'] == s][0] for s in RUNS}}
for gt, name in (('relA', 'GT-A 同模板'), ('relB', 'GT-B 同模板且来源题至少一次真成功')):
    wr = sum(1 for r in per_task if r[gt]); print(f"\n## Q1 比较 · {name}（{len(per_task)} 题，其中 {wr} 题库里有相关经验）\n")
    print("| 方法 | recall@1 [95% CI] | precision | 无相关时正确弃权 | 决策准确率 [95% CI] | 注入率 |\n|---|---|---|---|---|---|")
    OUT['comparison'][gt] = []; ACC = {}; REC = {}
    for m in METHODS:
        c, r1, acc = score(per_task, m, gt); ACC[m], REC[m] = acc, r1
        mr, lo, hi = bci(r1); ma, alo, ahi = bci(acc); prec = c['hit'] / max(c['inj'], 1); ab = c['abstain_ok'] / max(c['without_rel'], 1)
        OUT['comparison'][gt].append(dict(method=m, recall=mr, recall_ci=[lo, hi], precision=prec, abstain=ab, acc=ma, acc_ci=[alo, ahi], inject_rate=c['inj'] / c['tasks']))
        print(f"| {m} | {mr:.2f} [{lo:.2f}, {hi:.2f}] | {prec:.2f} | {ab:.2f} | {ma:.2f} [{alo:.2f}, {ahi:.2f}] | {c['inj']/c['tasks']:.2f} |")
    OUT['paired'][gt] = {}
    print("\n配对差 ours − 对照（逐题 bootstrap；recall 只在有相关经验的题上算）：\n\n| 对照 | Δ决策准确率 [95% CI] | 赢/输/平 | Δrecall@1 [95% CI] |\n|---|---|---|---|")
    for b in ('bm25+content', 'hybrid', 'dense[bge-small]', 'dense+tau*(per-site, test-tuned)', 'always-abstain'):
        pa = paired(ACC['ours(as-run)'], ACC[b]); pr = paired(REC['ours(as-run)'], REC[b]) if len(REC[b]) else None
        OUT['paired'][gt][b] = dict(acc=pa, recall=pr)
        print(f"| {b} | {pa['diff']:+.3f} [{pa['ci'][0]:+.3f}, {pa['ci'][1]:+.3f}] | {pa['win']}/{pa['lose']}/{pa['tie']} | " + (f"{pr['diff']:+.3f} [{pr['ci'][0]:+.3f}, {pr['ci'][1]:+.3f}]" if pr else "—") + " |")
print(f"\n每站测试集上调出来的 τ*：{OUT['tau_star']}（这是偷看答案的乐观基线）")
# validity of the label: outcome deltas of as-run injections by label
inj = [r for r in per_task if r['sel']['ours(as-run)'] is not None and r['delta'] is not None]
def dsum(rs): 
    x = np.asarray([r['delta'] for r in rs], float); m, lo, hi = bci(x) if len(x) else (float('nan'),)*3; return f"{m:+.2f} [{lo:+.2f}, {hi:+.2f}] (n={len(x)})"
same = [r for r in inj if r['sel']['ours(as-run)'] in r['relA']]; cross = [r for r in inj if r['sel']['ours(as-run)'] not in r['relA']]
same_ok = [r for r in same if r['src_nc'].get(r['sel']['ours(as-run)'], 0) >= 1]; same_zero = [r for r in same if r['src_nc'].get(r['sel']['ours(as-run)'], 0) == 0]
abst = [r for r in per_task if r['sel']['ours(as-run)'] is None and r['delta'] is not None]
OUT['validity'] = dict(same=dsum(same), cross=dsum(cross), same_src_ok=dsum(same_ok), same_src_zero=dsum(same_zero), abstained=dsum(abst))
print("\n## 标签的结果效度：实跑注入后 Δ（withmem − nomem 的 8 条命中数）\n")
print(f"| 注入的经验 | Δ [95% CI] |\n|---|---|\n| 同模板 | {OUT['validity']['same']} |\n| 跨模板 | {OUT['validity']['cross']} |\n| 同模板且来源题 ≥1 次真成功 | {OUT['validity']['same_src_ok']} |\n| 同模板但来源题 0 次真成功 | {OUT['validity']['same_src_zero']} |\n| 门控弃权 | {OUT['validity']['abstained']} |")
# Q2(a) recall@k
withrel = [r for r in per_task if r['relA']]
print("\n## Q2(a) 池子大小 k（GT-A，有相关经验的题）\n")
RK = ['bm25', 'bm25+content', 'dense[bge-small]', 'dense[bge-base]', 'dense[MiniLM-L6]', 'hybrid']
print("| k | " + " | ".join(RK) + " |\n|---|" + "---|" * len(RK))
for k in (1, 2, 3, 5, 7, 10):
    row = [np.mean([any(t in r['relA'] for t in r['rank'][m][:k]) for r in withrel]) for m in RK]
    for m, v in zip(RK, row): OUT['recall_at_k'].setdefault(m, {})[k] = float(v)
    print(f"| {k} | " + " | ".join(f"{v:.2f}" for v in row) + " |")
c, r1, _ = score(per_task, 'ours(as-run)'); p5 = OUT['recall_at_k']['dense[bge-small]'][5]
in5 = [r for r in withrel if any(t in r['relA'] for t in r['rank']['dense[bge-small]'][:5])]
pick_ok = np.mean([r['sel']['ours(as-run)'] in r['relA'] for r in in5]); pick_ab = np.mean([r['sel']['ours(as-run)'] is None for r in in5]); pick_wrong = 1 - pick_ok - pick_ab
out5 = [r for r in withrel if r not in in5]; ab_out = np.mean([r['sel']['ours(as-run)'] is None for r in out5]) if out5 else float('nan')
OUT['llm_step'] = dict(pool5=p5, recall=float(r1.mean()), pick_ok=float(pick_ok), pick_abstain=float(pick_ab), pick_wrong=float(pick_wrong), abstain_when_absent=float(ab_out))
print(f"\nLLM 那一步：相关经验在 dense top-5 里的题占 {p5:.2f}；池子里有货时门控选对 {pick_ok:.2f}、弃权 {pick_ab:.2f}、选错 {pick_wrong:.2f}；池子里没货时弃权 {ab_out:.2f}。最终 recall@1 = {r1.mean():.2f}。")
print("\n## Q2(b) 嵌入什么文本（dense bge-small，GT-A）\n\n| 嵌入文本 | recall@1 | 相关在 top-5 |\n|---|---|---|")
for v in VARIANTS:
    m = 'dense[bge-small]' if v == 'title+description' else f'dense-text[{v}]'
    r1v = np.mean([r['rank'][m][0] in r['relA'] for r in withrel]); r5 = np.mean([any(t in r['relA'] for t in r['rank'][m][:5]) for r in withrel])
    OUT['ablation_text'].append(dict(text=v, recall1=float(r1v), recall5=float(r5))); print(f"| {v}{'（我们）' if v == 'title+description' else ''} | {r1v:.2f} | {r5:.2f} |")
L2o = np.mean([any(t in r['relA'] for t in r['top5']['L2-only']) for r in withrel]); L12 = np.mean([any(t in r['relA'] for t in r['top5']['L1+L2'] if t) for r in withrel]); l1share = np.mean([np.mean([t is None for t in r['top5']['L1+L2']]) for r in withrel])
OUT['ablation_layer'] = {'L2-only pool': float(L2o), 'L1+L2 pool': float(L12), 'l1_share_top5': float(l1share)}
own = L2o; alls = np.mean([any(t in r['relA'] for t in r['top5']['all-sites'] if t != 'FOREIGN') for r in withrel]); fshare = np.mean([np.mean([t == 'FOREIGN' for t in r['top5']['all-sites']]) for r in withrel]); f1 = np.mean([r['top5']['all-sites'][0] == 'FOREIGN' for r in withrel])
OUT['ablation_scope'] = {'own-site pool': float(own), 'all-sites pool': float(alls), 'foreign_share_top5': float(fshare), 'top1_foreign': float(f1)}
print(f"\n## Q2(c) layer 过滤：相关 L2 在 dense top-5：只看 L2 {L2o:.2f} vs L1+L2 混池 {L12:.2f}（混池 top-5 里 {l1share:.0%} 是 L1）\n## Q2(d) scope 过滤：本站池 {own:.2f} vs 五站混池 {alls:.2f}（混池 top-5 里 {fshare:.0%} 是别站经验，top-1 {f1:.0%} 是别站）")
print("\n## Q3 分站（GT-A）\n\n| 站 | 题数 | 有相关 | BM25 | dense | hybrid | ours | 决策准确率：ours | always-abstain | τ* |\n|---|---|---|---|---|---|---|---|---|---|")
for site in RUNS:
    recs = [r for r in per_task if r['site'] == site]; row = {}
    for m in ('bm25', 'dense[bge-small]', 'hybrid', 'ours(as-run)', 'always-abstain', 'dense+tau*(per-site, test-tuned)'):
        c, r1, acc = score(recs, m); row[m] = (float(r1.mean()) if len(r1) else float('nan'), float(acc.mean()))
    OUT['per_site'].append(dict(site=site, n=len(recs), with_rel=int(sum(bool(r['relA']) for r in recs)), bm25=row['bm25'][0], dense=row['dense[bge-small]'][0], hybrid=row['hybrid'][0], ours=row['ours(as-run)'][0], ours_acc=row['ours(as-run)'][1], abstain_acc=row['always-abstain'][1], tau_acc=row['dense+tau*(per-site, test-tuned)'][1]))
    print(f"| {site} | {len(recs)} | {sum(bool(r['relA']) for r in recs)} | {row['bm25'][0]:.2f} | {row['dense[bge-small]'][0]:.2f} | {row['hybrid'][0]:.2f} | {row['ours(as-run)'][0]:.2f} | {row['ours(as-run)'][1]:.2f} | {row['always-abstain'][1]:.2f} | {row['dense+tau*(per-site, test-tuned)'][1]:.2f} |")
print("\n## Q3 库大小（GT-A，按站分层以免和站点混淆；recall@1）\n\n| 站 | 库大小 | 有相关题数 | BM25 | dense | hybrid | ours |\n|---|---|---|---|---|---|---|")
for site in RUNS:
    OUT['bank_size_by_site'][site] = []
    for lo, hi in ((1, 10), (11, 30), (31, 60), (61, 10000)):
        recs = [r for r in per_task if r['site'] == site and lo <= r['n_cands'] <= hi and r['relA']]
        if len(recs) < 8: continue
        row = {m: float(np.mean([r['sel'][m] in r['relA'] for r in recs])) for m in ('bm25', 'dense[bge-small]', 'hybrid', 'ours(as-run)')}
        OUT['bank_size_by_site'][site].append(dict(bucket=f"{lo}-{hi if hi < 10000 else '+'}", n=len(recs), **row))
        print(f"| {site} | {lo}–{hi if hi < 10000 else '+'} | {len(recs)} | {row['bm25']:.2f} | {row['dense[bge-small]']:.2f} | {row['hybrid']:.2f} | {row['ours(as-run)']:.2f} |")
json.dump(OUT, open('runs/retrieval_suite_summary.json', 'w'), ensure_ascii=False, default=float)
