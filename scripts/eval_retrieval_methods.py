"""Offline comparison of retrieval/selection methods on the recorded WebArena L2 banks.

Replays each site's withmem stream: at task i the candidate bank is the set of L2 items
written by earlier tasks (same site). Ground truth for "the right experience" is provenance:
an item is RELEVANT to task i iff its source task shares task i's intent template
(same-template siblings are where the measured effect lives; cross-template ~0).

Methods (each selects exactly ONE item or abstains):
  bm25@1      Okapi BM25 over "title. description" (same text the system embeds)
  bm25full@1  BM25 over title+description+content
  dense@1     cosine top-1 with bge-small (the run's own embeddings; query embedded with fastembed)
  dense+thr   dense@1 but abstain when cosine < tau
  hybrid@1    reciprocal-rank fusion of bm25 and dense, top-1
  asrun       what the run actually injected (dense top-5 -> LLM select_lesson, or nothing)
  llm-direct  (online) LLM picks from the WHOLE candidate bank, may abstain      [needs gateway]
  ours-replay (online) dense top-5 -> LLM select_lesson, may abstain             [needs gateway]

Metrics per site: recall@1 on tasks with >=1 relevant candidate; precision of injections;
correct-abstain rate on tasks with no relevant candidate; overall decision accuracy;
plus recovery of the run's outcome-validated saves (delta nc >= +4) and avoidance of poisons (<= -4).
"""
import json, math, re, sys, os, collections, argparse
import numpy as np

sys.path.insert(0, 'src')
META = {t['task_id']: t for t in json.load(open('.venv-wa/lib/python3.11/site-packages/webarena/test.raw.json'))}
RUNS = {
    'shopping': 'runs/wa_fleet_shopping_all_20260811_191401_20260811_191415',
    'shopping_admin': 'runs/wa_fleet_shopping_admin_all_20260818_005633_20260818_005647',
    'gitlab': 'runs/wa_fleet_gitlab_all_20260815_172053_20260815_172110',
    'reddit': 'runs/wa_fleet_reddit_all_20260814_002621_20260814_002652',
    'map': 'runs/wa_fleet_map_readonly_20260813_103741_20260813_103743',
}
TOK = re.compile(r"[a-z0-9]+")
def tok(s): return TOK.findall(s.lower())

class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = [tok(d) for d in docs]; self.k1, self.b = k1, b
        self.N = len(self.docs); self.avg = sum(len(d) for d in self.docs) / max(self.N, 1)
        self.df = collections.Counter(); [self.df.update(set(d)) for d in self.docs]
        self.tf = [collections.Counter(d) for d in self.docs]
    def scores(self, q):
        q = tok(q); out = np.zeros(self.N)
        for i, tf in enumerate(self.tf):
            L = len(self.docs[i]); s = 0.0
            for w in q:
                if w not in tf: continue
                idf = math.log(1 + (self.N - self.df[w] + 0.5) / (self.df[w] + 0.5))
                s += idf * tf[w] * (self.k1 + 1) / (tf[w] + self.k1 * (1 - self.b + self.b * L / self.avg))
            out[i] = s
        return out

def load_site(site, run):
    items = {it['title']: it for it in json.load(open(run + '/memory.json'))['reasoning'] if it.get('layer') == 'L2'}
    tasks, writes, ret, tpl_of = [], [], {}, {}
    nomem = {}
    for l in open(run + '/events.jsonl'):
        e = json.loads(l); k = e.get('kind')
        if k == 'wa_task':
            tpl_of[e['task_id']] = e['template_id']
            if e['tag'] == 'withmem': tasks.append(e)
            else: nomem[e['task_id']] = e
        elif k == 'wa_write_l2' and e['item']['title'] in items:
            writes.append({'t': e['t'], 'task': e['task'], 'title': e['item']['title'], 'nc': e.get('nc'), 'n': e.get('n')})
        elif k == 'wa_retrieve' and e['tag'] == 'withmem':
            ret[e['task_id']] = e.get('titles', [])
    for w in writes: w['tpl'] = tpl_of.get(w['task'], META[w['task']].get('intent_template_id'))
    tasks.sort(key=lambda e: e['t'])
    return items, tasks, writes, ret, nomem

class _Item:
    def __init__(self, d): self.title, self.content, self.description = d['title'], d['content'], d.get('description', '')

def rrf(rank_a, rank_b, k=60):
    return {i: 1/(k+rank_a[i]) + 1/(k+rank_b[i]) for i in rank_a}

def evaluate(site, run, embedder, taus=(0.55, 0.60, 0.65), online=None):
    items, tasks, writes, ret, nomem = load_site(site, run)
    qtexts = [META[e['task_id']]['intent'] for e in tasks]
    qemb = np.asarray(list(embedder.embed(qtexts))) if embedder else None
    methods = ['random@1', 'bm25@1', 'bm25full@1', 'dense@1'] + [f'dense+thr{t}' for t in taus] + ['hybrid@1', 'asrun']
    if online: methods += ['llm-direct', 'ours-replay', 'llm-over-bm25@5', 'llm-over-hybrid@5']
    S = {m: collections.Counter() for m in methods}
    rng = np.random.default_rng(0)
    rows = []
    for qi, e in enumerate(tasks):
        tid, tpl = e['task_id'], e['template_id']
        cands = [w for w in writes if w['t'] < e['t']]
        if not cands:
            for m in methods: S[m]['no_cands'] += 1
            continue
        rel = {w['title'] for w in cands if w['tpl'] == tpl}
        has_rel = bool(rel)
        texts = [f"{items[w['title']]['title']}. {items[w['title']]['description']}" for w in cands]
        full = [t + " " + items[w['title']]['content'] for t, w in zip(texts, cands)]
        sel = {}
        bm = BM25(texts).scores(qtexts[qi]); sel['bm25@1'] = cands[int(bm.argmax())]['title'] if bm.max() > 0 else None
        bf = BM25(full).scores(qtexts[qi]); sel['bm25full@1'] = cands[int(bf.argmax())]['title'] if bf.max() > 0 else None
        M = np.asarray([items[w['title']]['embedding'] for w in cands]); q = qemb[qi]
        cos = M @ q / (np.linalg.norm(M, axis=1) * np.linalg.norm(q) + 1e-9)
        top = int(cos.argmax()); sel['dense@1'] = cands[top]['title']
        for t in taus: sel[f'dense+thr{t}'] = cands[top]['title'] if cos[top] >= t else None
        ra = {i: r for r, i in enumerate(np.argsort(-bm))}; rb = {i: r for r, i in enumerate(np.argsort(-cos))}
        f = rrf(ra, rb); sel['hybrid@1'] = cands[max(f, key=f.get)]['title']
        got = ret.get(tid, []); sel['asrun'] = got[0] if got else None
        sel['random@1'] = cands[int(rng.integers(len(cands)))]['title']
        # ranking diagnostics: is a relevant item inside the top-5 pool each ranker would hand to an LLM gate?
        if has_rel:
            for name, order in (('bm25', np.argsort(-bm)), ('dense', np.argsort(-cos)), ('hybrid', sorted(f, key=f.get, reverse=True))):
                S[f'_{name}_rel_in_top5'] = S.get(f'_{name}_rel_in_top5', 0) + int(any(cands[int(i)]['title'] in rel for i in list(order)[:5]))
            S['_with_rel_total'] = S.get('_with_rel_total', 0) + 1
        if online:
            brain, intent = online, qtexts[qi]
            pool5 = lambda order: [items[cands[int(i)]['title']] for i in list(order)[:5]]
            def pick(pool):
                r = brain.select_lesson(intent, [_Item(x) for x in pool]); return r.title if r is not None else None
            sel['ours-replay'] = pick(pool5(np.argsort(-cos)))
            sel['llm-over-bm25@5'] = pick(pool5(np.argsort(-bm)))
            sel['llm-over-hybrid@5'] = pick(pool5(sorted(f, key=f.get, reverse=True)))
            sel['llm-direct'] = pick([items[w['title']] for w in cands])
        # outcome labels from the run itself
        nm = nomem.get(tid); delta = (e['nc'] - nm['nc']) if nm and e['n'] and nm['n'] else None
        for m in methods:
            s = sel[m]; S[m]['tasks'] += 1
            if has_rel: S[m]['with_rel'] += 1
            else: S[m]['without_rel'] += 1
            if s is not None:
                S[m]['injected'] += 1
                if s in rel: S[m]['hit'] += 1
                elif has_rel: S[m]['wrong_item'] += 1
                else: S[m]['false_inject'] += 1
            else:
                if has_rel: S[m]['missed_abstain'] += 1
                else: S[m]['correct_abstain'] += 1
            # recovery of the run's validated saves / avoidance of poisons (only where asrun injected)
            if got and delta is not None:
                if delta >= 4: S[m]['saves'] += 1; S[m]['save_recovered'] += int(s == got[0])
                if delta <= -4: S[m]['poisons'] += 1; S[m]['poison_avoided'] += int(s != got[0])
        rows.append({'site': site, 'task': tid, 'tpl': tpl, 'has_rel': has_rel, 'n_cands': len(cands), 'delta': delta, 'sel': sel, 'rel': sorted(rel)})
    return S, rows

def report(S, title):
    print(f"\n### {title}")
    diag = {k: v for k, v in S.items() if isinstance(k, str) and k.startswith('_')}
    if diag.get('_with_rel_total'):
        n = diag['_with_rel_total']
        print("相关经验落在各排序器 top-5 池子里的比例（LLM 门控能救回的上限）："
              + "，".join(f"{k.split('_')[1]} {diag[k]/n:.2f}" for k in ('_bm25_rel_in_top5', '_dense_rel_in_top5', '_hybrid_rel_in_top5') if k in diag))
    print("| method | tasks | 有相关经验的题 | recall@1 | 注入数 | precision | 无相关时正确弃权 | 决策准确率 | 救活复现 | 中毒避开 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for m, c in S.items():
        if isinstance(m, str) and m.startswith('_'): continue
        wr, wo = c['with_rel'], c['without_rel']; inj = c['injected']
        rec = c['hit']/wr if wr else float('nan'); prec = c['hit']/inj if inj else float('nan')
        ab = c['correct_abstain']/wo if wo else float('nan'); acc = (c['hit']+c['correct_abstain'])/max(c['tasks'],1)
        sv = f"{c['save_recovered']}/{c['saves']}" if c['saves'] else "—"; po = f"{c['poison_avoided']}/{c['poisons']}" if c['poisons'] else "—"
        if m == 'asrun': sv, po = '（定义）', '（定义）'
        print(f"| {m} | {c['tasks']} | {wr} | {rec:.2f} | {inj} | {prec:.2f} | {ab:.2f} | {acc:.2f} | {sv} | {po} |")

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='runs/retrieval_eval_wa.json')
    ap.add_argument('--online', action='store_true', help='also run LLM selection arms through the gateway (needs VPN)')
    ap.add_argument('--sites', default=','.join(RUNS)); a = ap.parse_args()
    from fastembed import TextEmbedding
    emb = TextEmbedding(model_name='BAAI/bge-small-en-v1.5')
    brain = None
    if a.online:
        from dotenv import load_dotenv; load_dotenv('.env')
        from hippo.llm import LLMClient; from hippo.wa.brain import WaBrain
        brain = WaBrain(LLMClient(model='gpt-5.6-sol', embed_model='local/BAAI/bge-small-en-v1.5'))
    pooled = collections.defaultdict(collections.Counter); pooled_diag = {}; allrows = []
    for site in a.sites.split(','):
        run = RUNS[site]
        S, rows = evaluate(site, run, emb, online=brain); allrows += rows
        report(S, f"{site}  ({os.path.basename(run)})")
        for m, c in S.items():
            if isinstance(c, int): pooled_diag[m] = pooled_diag.get(m, 0) + c
            else: pooled[m].update(c)
    pooled.update(pooled_diag); report(pooled, "五站合计")
    json.dump(allrows, open(a.out, 'w'), ensure_ascii=False)
    print(f"\nrows -> {a.out}")
