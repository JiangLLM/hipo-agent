"""Paper figures from the offline analyses (runs/paper_offline_analyses.json, runs/retrieval_eval_wa.json).
Style follows the dataviz method: one axis per chart, categorical hues in fixed validated order
(blue #2a78d6, orange #eb6834, aqua #1baf7a), emphasis = one hue + gray, hairline recessive grid,
text in ink tokens, thin marks, sparing direct labels."""
import json, collections, numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import rcParams
BLUE, ORANGE, AQUA, GRAY, INK, INK2, GRID = '#2a78d6', '#eb6834', '#1baf7a', '#b8b7b2', '#0b0b0b', '#52514e', '#e6e5e1'
rcParams.update({'font.size': 9, 'axes.edgecolor': GRID, 'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2,
                 'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.6,
                 'axes.titlecolor': INK, 'axes.titlesize': 10, 'axes.titleweight': 'bold', 'legend.frameon': False, 'figure.dpi': 200})
A = json.load(open('runs/paper_offline_analyses.json'))
def save(fig, name):
    fig.tight_layout(); fig.savefig(f'paper/figures/{name}.png', bbox_inches='tight'); fig.savefig(f'paper/figures/{name}.pdf', bbox_inches='tight'); plt.close(fig)

# ---- F1: gain by baseline difficulty, injected vs not (dose control) ----
rows = A['difficulty_rows']; rng = np.random.default_rng(0)
buckets = [('0/8', lambda x: x == 0), ('1–3/8', lambda x: 0 < x < 0.5), ('4–6/8', lambda x: 0.5 <= x < 0.875), ('7/8', lambda x: abs(x-0.875) < 1e-9), ('8/8', lambda x: x == 1)]
def ci(xs):
    xs = np.asarray(xs); s = rng.choice(xs, (3000, len(xs))).mean(1); return xs.mean(), np.percentile(s, 2.5), np.percentile(s, 97.5)
fig, ax = plt.subplots(figsize=(6.0, 3.1)); y = np.arange(len(buckets))[::-1]
for i, (name, pred) in enumerate(buckets):
    sel = [r for r in rows if pred(r['nomem'])]
    inj = [100*(r['withmem']-r['nomem']) for r in sel if r['injected']]; no = [100*(r['withmem']-r['nomem']) for r in sel if not r['injected']]
    m, lo, hi = ci(inj); ax.barh(y[i]+0.18, m, height=0.34, color=BLUE, zorder=3); ax.errorbar(m, y[i]+0.18, xerr=[[m-lo], [hi-m]], fmt='none', ecolor=INK2, elinewidth=0.8, capsize=2, zorder=4)
    m2, lo2, hi2 = ci(no); ax.barh(y[i]-0.18, m2, height=0.34, color=GRAY, zorder=3); ax.errorbar(m2, y[i]-0.18, xerr=[[m2-lo2], [hi2-m2]], fmt='none', ecolor=INK2, elinewidth=0.8, capsize=2, zorder=4)
    ax.text(-27.5, y[i], f"n={len(inj)} / {len(no)}", va='center', ha='left', fontsize=7.5, color=INK2)
ax.axvline(0, color=INK2, linewidth=0.8, zorder=2); ax.set_yticks(y); ax.set_yticklabels([b[0] for b in buckets]); ax.set_ylabel('No-memory success (correct rollouts / 8)')
ax.set_xlabel('Δ success rate, with-memory − no-memory (pp, mean ± 95% CI)'); ax.set_xlim(-28, 32); ax.grid(axis='y', visible=False)
ax.legend(handles=[plt.Rectangle((0,0),1,1,color=BLUE), plt.Rectangle((0,0),1,1,color=GRAY)], labels=['lesson injected', 'no lesson (dose control)'], loc='upper right', fontsize=7.5, bbox_to_anchor=(1.0, 1.02))
ax.set_title('Gain by baseline difficulty (WebArena, 761 paired tasks)', fontsize=9.5, loc='left')
save(fig, 'F1_gain_by_difficulty')

# ---- F2: N sensitivity ----
NS = A['N_sensitivity']; Ns = sorted(int(k) for k in NS)
g = lambda n, k: NS[str(n)].get(k, 0)
fire = [g(n,'fires')/max(g(n,'tasks'),1) for n in Ns]; mr = [g(n,'mr_detected')/max(g(n,'mr_total'),1) for n in Ns]
passn = [NS[str(n)]['nomem_passN'] for n in Ns]; meann = [NS[str(n)]['nomem_meanN'] for n in Ns]
fig, ax = plt.subplots(figsize=(5.6, 3.0))
for ys, c, lab in ((fire, BLUE, 'write gate opens'), (mr, ORANGE, 'majority-right regime detected'), (passn, AQUA, 'no-memory pass@N')):
    ax.plot(Ns, ys, color=c, linewidth=2, marker='o', markersize=4.5, zorder=3); ax.text(Ns[-1]+0.15, ys[-1], f"{lab}  {ys[-1]:.2f}", va='center', fontsize=7.5, color=INK2)
ax.plot(Ns, meann, color=GRAY, linewidth=1.6, linestyle='-', marker='o', markersize=3.5, zorder=2); ax.text(Ns[-1]+0.15, meann[-1]-0.03, f"no-memory mean@N  {meann[-1]:.2f}", va='center', fontsize=7.5, color=INK2)
ax.set_xticks(Ns); ax.set_xlabel('N parallel rollouts per task'); ax.set_ylabel('rate'); ax.set_ylim(0, 1.05); ax.grid(axis='x', visible=False)
ax.set_title('Sensitivity to the number of parallel rollouts N', fontsize=9.5, loc='left'); ax.set_xlim(0.8, 11.5)
save(fig, 'F2_N_sensitivity')

# ---- F3: retrieval / selection methods (recall vs precision) ----
R = json.load(open('runs/retrieval_eval_wa.json')); S = collections.defaultdict(collections.Counter)
for r in R:
    rel = set(r['rel'])
    for m, s in r['sel'].items():
        c = S[m]; c['tasks'] += 1
        if r['has_rel']: c['with_rel'] += 1
        else: c['without_rel'] += 1
        if s is not None:
            c['inj'] += 1; c['hit'] += int(s in rel)
        elif not r['has_rel']: c['abstain_ok'] += 1
labels = {'random@1': 'random', 'bm25@1': 'BM25', 'bm25full@1': 'BM25 (+content)', 'dense@1': 'dense (bge-small)', 'dense+thr0.55': 'dense, abstain <0.55', 'dense+thr0.6': 'dense, abstain <0.60', 'dense+thr0.65': 'dense, abstain <0.65', 'hybrid@1': 'hybrid (RRF)', 'asrun': 'ours: dense top-5 → LLM picks 1 or none'}
fig, ax = plt.subplots(figsize=(5.4, 3.6))
for m, c in S.items():
    if m not in labels: continue
    rec = c['hit']/c['with_rel']; prec = c['hit']/max(c['inj'],1); ours = m == 'asrun'; abst = 'thr' in m or ours
    ax.scatter(rec, prec, s=70 if ours else 40, color=BLUE if ours else GRAY, marker='D' if abst else 'o', zorder=4, edgecolors='white', linewidths=1)
    off = {'bm25@1': (0.035, 0.065), 'bm25full@1': (0.035, 0.115), 'hybrid@1': (0.035, 0.015), 'dense@1': (0.035, -0.035), 'dense+thr0.55': (-0.02, -0.035), 'dense+thr0.6': (-0.02, 0.03), 'dense+thr0.65': (-0.02, 0.03), 'random@1': (0.02, 0.0), 'asrun': (0.0, 0.05)}[m]
    ha = 'right' if off[0] < 0 else ('center' if off[0] == 0 else 'left')
    ax.annotate(labels[m], (rec, prec), xytext=(rec+off[0], prec+off[1]), fontsize=7, color=INK if ours else INK2, ha=ha, va='center', arrowprops=dict(arrowstyle='-', color=GRID, lw=0.6) if abs(off[1]) > 0.04 else None)
ax.set_xlabel('recall@1 (picked a same-template lesson when one existed)'); ax.set_ylabel('precision (injected lesson was same-template)'); ax.set_xlim(0, 0.9); ax.set_ylim(0, 0.72)
ax.text(0.02, 0.66, '◆ can abstain   ● always injects', fontsize=7.5, color=INK2)
ax.set_title('Which retrieval picks the right experience (WebArena, 752 tasks)', fontsize=9.5, loc='left')
save(fig, 'F3_retrieval_methods')

# ---- F4: source-regime attribution (from PAPER_DIRECTION_REVIEW.md, 1258 paired tasks over 9 runs) ----
reg = [('no lesson (control)', 508, 0.5, -0.5, 1.4), ('all failed', 313, 0.2, -2.7, 3.1), ('majority failed', 197, 2.7, -1.5, 6.9), ('split 50/50', 34, -2.9, -10.5, 4.7), ('majority right', 206, 5.7, 2.7, 8.8)]
fig, ax = plt.subplots(figsize=(5.4, 2.8)); y = np.arange(len(reg))[::-1]
for i, (name, n, m, lo, hi) in enumerate(reg):
    emph = 'majority right' in name; ax.errorbar(m, y[i], xerr=[[m-lo], [hi-m]], fmt='o', color=BLUE if emph else GRAY, ecolor=BLUE if emph else GRAY, elinewidth=1.6, capsize=3, markersize=6, zorder=3)
    ax.text(12.6, y[i], f"n={n}", va='center', fontsize=7.5, color=INK2)
ax.axvline(0, color=INK2, linewidth=0.8); ax.set_yticks(y); ax.set_yticklabels([r[0] for r in reg], fontsize=8); ax.set_xlim(-12, 14); ax.grid(axis='y', visible=False)
ax.set_xlabel('Δ success rate on the receiving task (pp, mean ± 95% CI)'); ax.set_ylabel('outcome profile of the writing task')
ax.set_title('Which lessons transfer, by how their source task went (1,258 paired tasks)', fontsize=9.5, loc='left')
save(fig, 'F4_source_regime')
print("figures written:", sorted(__import__('os').listdir('paper/figures')))
