"""Offline analyses from recorded paired runs (no rollouts needed):
  A. N-sensitivity: subsample the 8 recorded rollouts to N in {1,2,3,4,6,8}; gate firing rate,
     regime distribution, detectability of the majority-right regime, nomem pass@N / mean@N.
  B. Fluke prevalence and the fluke-no-op counterfactual (RB-style: count flukes as successes).
  C. Delta by baseline difficulty (nomem nc bucket) pooled over paired tasks, bootstrap 95% CI.
Outputs a JSON with everything and prints markdown tables."""
import json, glob, collections, itertools, random, math
import numpy as np
RUNS = {
    'shopping': 'runs/wa_fleet_shopping_all_20260811_191401_20260811_191415',
    'shopping_admin': 'runs/wa_fleet_shopping_admin_all_20260818_005633_20260818_005647',
    'gitlab': 'runs/wa_fleet_gitlab_all_20260815_172053_20260815_172110',
    'reddit': 'runs/wa_fleet_reddit_all_20260814_002621_20260814_002652',
    'map': 'runs/wa_fleet_map_readonly_20260813_103741_20260813_103743',
}
def load(run):
    J = collections.defaultdict(dict); T = {}
    for l in open(run + '/events.jsonl'):
        e = json.loads(l); k = e.get('kind')
        if k == 'wa_judge': J[(e['tag'], e['task_id'])][e['rollout']] = e['outcome']
        elif k == 'wa_task': T[(e['tag'], e['task_id'])] = e
    return J, T
def regime(outs):
    keep = [o for o in outs if o != 'fluke']; ncg = sum(o == 'genuine' for o in keep); nk = len(keep)
    if nk <= 1 or ncg == nk: return None                      # gate closed
    if ncg == 0: return 'all_wrong'
    if ncg * 2 == nk: return 'split'
    return 'majority_right' if ncg * 2 > nk else 'majority_wrong'
rng = random.Random(0)
out = {'N_sensitivity': {}, 'fluke': {}, 'difficulty': {}}
# ---------- A + B ----------
Ns = [1, 2, 3, 4, 6, 8]
agg = {N: collections.Counter() for N in Ns}; passk = {N: [] for N in Ns}; meank = {N: [] for N in Ns}
fl = collections.Counter(); cf = collections.Counter()
for site, run in RUNS.items():
    J, T = load(run)
    for (tag, tid), outs in J.items():
        if len(outs) < 8: continue
        seq = [outs[r] for r in sorted(outs)]
        if tag == 'nomem':
            rew = [1 if o in ('genuine', 'fluke') else 0 for o in seq]
            for N in Ns:
                combos = list(itertools.combinations(range(8), N)); combos = rng.sample(combos, min(30, len(combos)))
                passk[N] += [max(rew[i] for i in c) for c in combos]; meank[N] += [sum(rew[i] for i in c) / N for c in combos]
        if tag != 'withmem': continue
        # fluke prevalence (both arms counted below)
        full = regime(seq)
        for N in Ns:
            combos = list(itertools.combinations(range(8), N)); combos = rng.sample(combos, min(30, len(combos)))
            for c in combos:
                r = regime([seq[i] for i in c]); agg[N]['tasks'] += 1
                if r: agg[N]['fires'] += 1; agg[N][r] += 1
                if full == 'majority_right': agg[N]['mr_total'] += 1; agg[N]['mr_detected'] += int(r == 'majority_right')
        # B: counterfactual — flukes counted as genuine
        cf['tasks'] += 1
        rb = regime(['genuine' if o == 'fluke' else o for o in seq])
        if full != rb: cf['decision_changed'] += 1
        if full is None and rb is not None: cf['rb_writes_extra'] += 1
        if full is not None and rb is None: cf['gate_closes_under_rb'] += 1
        if any(o == 'fluke' for o in seq): cf['tasks_with_fluke'] += 1
        if full is not None and any(o == 'fluke' for o in seq): cf['writes_with_fluke_source'] += 1
    for (tag, tid), outs in J.items():
        for o in outs.values():
            fl[(site, tag, o)] += 1
out['N_sensitivity'] = {N: {**agg[N], 'nomem_passN': float(np.mean(passk[N])), 'nomem_meanN': float(np.mean(meank[N]))} for N in Ns}
out['fluke'] = {'per_site': {f"{s}/{t}/{o}": v for (s, t, o), v in fl.items()}, 'counterfactual': dict(cf)}
print("### A. N 敏感性（从 8 条实录 rollout 里抽 N 条，每题最多 30 个子集；五站 withmem 臂）")
print("| N | 闸门开启率 | 全错 | 多数错 | 半对半错 | 多数对 | 多数对档可检出率 | nomem pass@N | nomem mean@N |\n|---|---|---|---|---|---|---|---|---|")
for N in Ns:
    a = agg[N]; t = a['tasks']; f = a['fires'] or 1
    print(f"| {N} | {a['fires']/t:.2f} | {a['all_wrong']/f:.2f} | {a['majority_wrong']/f:.2f} | {a['split']/f:.2f} | {a['majority_right']/f:.2f} | {a['mr_detected']/max(a['mr_total'],1):.2f} | {np.mean(passk[N]):.3f} | {np.mean(meank[N]):.3f} |")
print("\n### B. 蒙对（fluke）流行率与 no-op 反事实")
print("| 站 | 臂 | 正确 rollout 数 | 其中 fluke | fluke 占正确的比例 |\n|---|---|---|---|---|")
for site in RUNS:
    for tag in ('nomem', 'withmem'):
        g = fl[(site, tag, 'genuine')]; k = fl[(site, tag, 'fluke')]
        print(f"| {site} | {tag} | {g+k} | {k} | {k/max(g+k,1):.3f} |")
c = cf
print(f"\n把 fluke 当成功（ReasoningBank 式）会改变 {c['decision_changed']}/{c['tasks']} 道题的写入决策：{c['rb_writes_extra']} 道我们不写它会写，{c['gate_closes_under_rb']} 道我们写它不写；{c['tasks_with_fluke']} 道题含至少一条 fluke，其中 {c['writes_with_fluke_source']} 次 L2 写入的源任务含 fluke（fluke 已剔出对比）。")
# ---------- C ----------
rows = []
for site, run in RUNS.items():
    J, T = load(run)
    for (tag, tid), e in T.items():
        if tag != 'nomem' or ('withmem', tid) not in T: continue
        w = T[('withmem', tid)]
        if not e['n'] or not w['n']: continue
        rows.append({'site': site, 'task': tid, 'nomem': e['nc'] / e['n'], 'withmem': w['nc'] / w['n'], 'injected': bool(w.get('ret_titles'))})
def boot(xs, B=2000):
    xs = np.asarray(xs); m = xs.mean(); bs = [rng.choice(xs.tolist()) for _ in range(0)]
    r = np.random.default_rng(0); samp = r.choice(xs, (B, len(xs))).mean(1); return m, np.percentile(samp, 2.5), np.percentile(samp, 97.5)
buckets = [('0/8（基线全错）', lambda x: x == 0), ('1–3/8', lambda x: 0 < x < 0.5), ('4–6/8', lambda x: 0.5 <= x < 0.875), ('7/8', lambda x: abs(x - 0.875) < 1e-9), ('8/8（基线全对）', lambda x: x == 1)]
print("\n### C. 记忆增益按基线难度分档（五站配对题合计，Δ = withmem − nomem 的 8 条命中率，百分点）")
print("| 基线 nomem 命中 | 题数 | 其中吃到注入 | Δ 均值 | 95% CI | Δ（只算吃到注入的） |\n|---|---|---|---|---|---|")
out['difficulty'] = []
for name, pred in buckets:
    sel = [r for r in rows if pred(r['nomem'])]
    if not sel: continue
    d = [100 * (r['withmem'] - r['nomem']) for r in sel]; m, lo, hi = boot(d)
    inj = [100 * (r['withmem'] - r['nomem']) for r in sel if r['injected']]; mi = np.mean(inj) if inj else float('nan')
    print(f"| {name} | {len(sel)} | {len(inj)} | {m:+.1f} | [{lo:+.1f}, {hi:+.1f}] | {mi:+.1f} |")
    out['difficulty'].append({'bucket': name, 'n': len(sel), 'n_injected': len(inj), 'delta': m, 'ci': [lo, hi], 'delta_injected': mi})
d = [100 * (r['withmem'] - r['nomem']) for r in rows]; m, lo, hi = boot(d)
print(f"| 全部 | {len(rows)} | {sum(r['injected'] for r in rows)} | {m:+.1f} | [{lo:+.1f}, {hi:+.1f}] | {np.mean([100*(r['withmem']-r['nomem']) for r in rows if r['injected']]):+.1f} |")
out['difficulty_rows'] = rows
json.dump(out, open('runs/paper_offline_analyses.json', 'w'), ensure_ascii=False, default=float)

# ---------- C2: regression-to-the-mean controls ----------
print("\n### C2. 同一分档里吃到注入 vs 没吃到注入（剂量对照；没吃到的那列就是纯回归均值/噪声）")
print("| 基线 nomem 命中 | 吃到注入 n | Δ | 没吃到 n | Δ | 差（记忆净效应） |\n|---|---|---|---|---|---|")
out['difficulty_dose'] = []
for name, pred in buckets:
    sel = [r for r in rows if pred(r['nomem'])]
    a = [100 * (r['withmem'] - r['nomem']) for r in sel if r['injected']]; b = [100 * (r['withmem'] - r['nomem']) for r in sel if not r['injected']]
    ma = np.mean(a) if a else float('nan'); mb = np.mean(b) if b else float('nan')
    print(f"| {name} | {len(a)} | {ma:+.1f} | {len(b)} | {mb:+.1f} | {ma-mb:+.1f} |")
    out['difficulty_dose'].append({'bucket': name, 'n_inj': len(a), 'd_inj': ma, 'n_noinj': len(b), 'd_noinj': mb})
# nomem-vs-nomem control: two independent admin full-set runs (0816 vs 0818), stratify by the FIRST run's nomem bucket
A = 'runs/wa_fleet_shopping_admin_all_20260816_202148_20260816_202200'; B = 'runs/wa_fleet_shopping_admin_all_20260818_005633_20260818_005647'
_, TA = load(A); _, TB = load(B)
print("\n### C3. 无记忆 vs 无记忆的两次独立全集跑（admin 0816 → 0818），按第一次的命中分档：这是没有任何记忆时的回归均值大小")
print("| 0816 nomem 命中 | 题数 | Δ(0818 nomem − 0816 nomem) | 同分档 0816 nomem→withmem Δ | 同分档 0818 nomem→withmem Δ |\n|---|---|---|---|---|")
out['rtm_control'] = []
for name, pred in buckets:
    ids = [tid for (tag, tid), e in TA.items() if tag == 'nomem' and e['n'] and pred(e['nc'] / e['n']) and ('nomem', tid) in TB and TB[('nomem', tid)]['n'] and ('withmem', tid) in TA and ('withmem', tid) in TB and TA[('withmem', tid)]['n'] and TB[('withmem', tid)]['n']]
    if not ids: continue
    d_nn = np.mean([100 * (TB[('nomem', t)]['nc'] / TB[('nomem', t)]['n'] - TA[('nomem', t)]['nc'] / TA[('nomem', t)]['n']) for t in ids])
    d_a = np.mean([100 * (TA[('withmem', t)]['nc'] / TA[('withmem', t)]['n'] - TA[('nomem', t)]['nc'] / TA[('nomem', t)]['n']) for t in ids])
    d_b = np.mean([100 * (TB[('withmem', t)]['nc'] / TB[('withmem', t)]['n'] - TB[('nomem', t)]['nc'] / TB[('nomem', t)]['n']) for t in ids])
    print(f"| {name} | {len(ids)} | {d_nn:+.1f} | {d_a:+.1f} | {d_b:+.1f} |")
    out['rtm_control'].append({'bucket': name, 'n': len(ids), 'd_nomem_nomem': d_nn, 'd_mem_0816': d_a, 'd_mem_0818': d_b})
json.dump(out, open('runs/paper_offline_analyses.json', 'w'), ensure_ascii=False, default=float)
