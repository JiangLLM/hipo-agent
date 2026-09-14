import json, numpy as np, matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt; from matplotlib import rcParams
BLUE, ORANGE, AQUA, GRAY, INK, INK2, GRID = '#2a78d6', '#eb6834', '#1baf7a', '#b8b7b2', '#0b0b0b', '#52514e', '#e6e5e1'
rcParams.update({'font.size': 9, 'axes.edgecolor': GRID, 'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2, 'axes.spines.top': False, 'axes.spines.right': False,
                 'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.6, 'axes.titlecolor': INK, 'axes.titlesize': 9.5, 'axes.titleweight': 'bold', 'legend.frameon': False, 'figure.dpi': 200})
S = json.load(open('runs/retrieval_suite_summary.json'))
def save(fig, name): fig.tight_layout(); fig.savefig(f'paper/figures/{name}.png', bbox_inches='tight'); fig.savefig(f'paper/figures/{name}.pdf', bbox_inches='tight'); plt.close(fig)
# ---- R1: recall@1 (x, with CI) vs precision (y), GT-A ----
lab = {'random': 'random', 'bm25': 'BM25', 'bm25+content': 'BM25 +content', 'dense[bge-small]': 'dense bge-small', 'dense[bge-base]': 'dense bge-base', 'dense[MiniLM-L6]': 'dense MiniLM', 'hybrid': 'hybrid RRF',
       'dense+thr0.55': 'abstain <.55', 'dense+thr0.6': 'abstain <.60', 'dense+thr0.65': 'abstain <.65', 'dense+thr0.7': 'abstain <.70', 'dense+thr0.75': 'abstain <.75', 'dense+tau*(per-site, test-tuned)': 'per-site τ* (test-tuned)', 'ours(as-run)': 'ours: dense top-5 → LLM picks 1 or none'}
off = {'random': (0.02, 0), 'bm25': (0.03, 0.05), 'bm25+content': (0.03, 0.10), 'dense[bge-small]': (0.03, -0.05), 'dense[bge-base]': (-0.03, -0.09), 'dense[MiniLM-L6]': (-0.03, -0.045), 'hybrid': (0.03, 0.0),
       'dense+thr0.55': (-0.03, -0.03), 'dense+thr0.6': (-0.03, 0.03), 'dense+thr0.65': (-0.03, 0.03), 'dense+thr0.7': (0.03, -0.035), 'dense+thr0.75': (0.03, 0.0), 'dense+tau*(per-site, test-tuned)': (0.03, 0.035), 'ours(as-run)': (0.0, 0.06)}
fig, ax = plt.subplots(figsize=(5.8, 4.0))
for c in S['comparison']['relA']:
    m = c['method']
    if m == 'always-abstain': continue
    ours = m.startswith('ours'); abst = 'thr' in m or 'tau' in m or ours
    ax.errorbar(c['recall'], c['precision'], xerr=[[c['recall'] - c['recall_ci'][0]], [c['recall_ci'][1] - c['recall']]], fmt='none', ecolor=BLUE if ours else GRAY, elinewidth=0.9, capsize=0, zorder=2)
    ax.scatter(c['recall'], c['precision'], s=80 if ours else 42, color=BLUE if ours else GRAY, marker='D' if abst else 'o', zorder=4, edgecolors='white', linewidths=1)
    dx, dy = off[m]; ha = 'right' if dx < 0 else ('center' if dx == 0 else 'left')
    ax.annotate(lab[m], (c['recall'], c['precision']), xytext=(c['recall'] + dx, c['precision'] + dy), fontsize=7, color=INK if ours else INK2, ha=ha, va='center', arrowprops=dict(arrowstyle='-', color=GRID, lw=0.6) if abs(dy) > 0.04 else None)
ax.set_xlim(0, 0.9); ax.set_ylim(0, 1.0); ax.set_xlabel('same-template selection rate when a same-template lesson existed (recall@1; bar = 95% CI)'); ax.set_ylabel('precision (injected lesson was same-template)')
ax.text(0.02, 0.95, '◆ can abstain   ● always injects   (always-abstain: recall 0, no injections)', fontsize=7.5, color=INK2); ax.set_title('Q1 · Which read path selects a same-template lesson (WebArena, 752 tasks)', loc='left')
save(fig, 'R1_retrieval_comparison')
# ---- R2: recall@k + the LLM step ----
fig, ax = plt.subplots(figsize=(5.2, 3.2)); ks = [1, 2, 3, 5, 7, 10]; L = S['llm_step']
for m, c, lb in (('bm25', ORANGE, 'BM25'), ('dense[bge-small]', BLUE, 'dense bge-small'), ('hybrid', AQUA, 'hybrid RRF'), ('dense[bge-base]', GRAY, 'dense bge-base')):
    ax.plot(ks, [S['recall_at_k'][m][str(k)] for k in ks], color=c, linewidth=2, marker='o', markersize=4, zorder=3, label=lb)
ax.scatter([5], [L['pool5']], s=60, color=BLUE, zorder=5, edgecolors='white'); ax.scatter([1], [L['recall']], s=90, color=BLUE, marker='D', zorder=6, edgecolors='white')
ax.annotate('', xy=(1.15, L['recall']), xytext=(4.85, L['pool5']), arrowprops=dict(arrowstyle='->', color=BLUE, lw=1.2))
ax.text(5.3, 0.535, f"◆ ours: LLM picks 1 of the dense top-5\n{L['pool5']:.2f} in pool → {L['recall']:.2f} chosen; picks right {L['pick_ok']:.2f} when present", fontsize=7.5, color=INK, ha='left')
ax.legend(fontsize=7.5, loc='upper left'); ax.set_xticks(ks); ax.set_xlim(0.7, 10.6); ax.set_ylim(0.5, 1.0); ax.set_xlabel('k (pool size handed to the selector)'); ax.set_ylabel('same-template lesson within top-k'); ax.grid(axis='x', visible=False)
ax.set_title('Q2 · Pool size and the LLM step (363 tasks with a same-template lesson)', loc='left'); save(fig, 'R2_pool_size_llm_step')
# ---- R3: ablations ----
fig, axes = plt.subplots(1, 3, figsize=(8.6, 2.9), gridspec_kw={'width_ratios': [4, 2, 2]})
ax = axes[0]; T = S['ablation_text']; x = np.arange(len(T))
ax.bar(x - 0.19, [t['recall1'] for t in T], 0.36, color=GRAY, label='recall@1'); ax.bar(x + 0.19, [t['recall5'] for t in T], 0.36, color=BLUE, label='in top-5')
for i, t in enumerate(T): ax.text(x[i] + 0.19, t['recall5'] + 0.015, f"{t['recall5']:.2f}", ha='center', fontsize=7, color=INK2); ax.text(x[i] - 0.19, t['recall1'] + 0.015, f"{t['recall1']:.2f}", ha='center', fontsize=7, color=INK2)
ax.set_xticks(x); ax.set_xticklabels(['title', 'description', 'title +\ndescription\n(ours)', '+ content'], fontsize=7.5); ax.set_ylim(0, 1); ax.set_title('(b) what text is embedded', loc='left'); ax.legend(fontsize=7, loc='upper left'); ax.grid(axis='x', visible=False); ax.set_ylabel('rate', fontsize=7.5)
for ax, key, keys, ticks, title in ((axes[1], 'ablation_layer', ('L2-only pool', 'L1+L2 pool'), ['L2-only\n(ours)', 'L1 + L2\nmixed'], '(c) layer filter before top-k'), (axes[2], 'ablation_scope', ('own-site pool', 'all-sites pool'), ['own site\n(ours)', 'all 5 sites\nmixed'], '(d) scope filter before top-k')):
    vals = [S[key][k] for k in keys]; ax.bar([0, 1], vals, 0.55, color=[BLUE, GRAY])
    for i, v in enumerate(vals): ax.text(i, v + 0.015, f"{v:.2f}", ha='center', fontsize=7.5, color=INK2)
    ax.set_xticks([0, 1]); ax.set_xticklabels(ticks, fontsize=7.5); ax.set_ylim(0, 1); ax.set_title(title, loc='left'); ax.grid(axis='x', visible=False); ax.set_ylabel('same-template lesson in dense top-5', fontsize=7.5)
save(fig, 'R3_read_path_ablations')
# ---- R4: per site (with always-abstain accuracy) + bank size stratified by site ----
fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.1), gridspec_kw={'width_ratios': [3, 2.4]})
ax = axes[0]; P = S['per_site']; x = np.arange(len(P)); w = 0.2
for j, (m, c, lb) in enumerate((('bm25', ORANGE, 'BM25'), ('dense', GRAY, 'dense'), ('hybrid', AQUA, 'hybrid'), ('ours', BLUE, 'ours'))):
    ax.bar(x + (j - 1.5) * w, [p[m] for p in P], w, color=c, label=lb)
ax.set_xticks(x); ax.set_xticklabels([f"{p['site']}\n(n={p['with_rel']})" for p in P], fontsize=7.5); ax.set_ylim(0, 1.05); ax.set_ylabel('recall@1 (same-template)'); ax.legend(fontsize=7, ncol=4, loc='upper right'); ax.grid(axis='x', visible=False)
ax.set_title('Q3 · per site — map: near-identical task texts', loc='left')
ax = axes[1]; BS = S['bank_size_by_site']
for site, c in (('shopping', BLUE), ('shopping_admin', ORANGE), ('gitlab', AQUA)):
    rows = BS[site]; xs = np.arange(len(rows))
    ax.plot(xs, [r['ours(as-run)'] for r in rows], color=c, linewidth=2, marker='o', markersize=4, label=f'{site} — ours')
    ax.plot(xs, [r['hybrid'] for r in rows], color=c, linewidth=1.2, linestyle='--', marker='o', markersize=3, alpha=0.8)
ax.set_xticks(range(4)); ax.set_xticklabels(['1–10', '11–30', '31–60', '61+'], fontsize=7.5); ax.set_xlabel('candidate bank size when the task ran'); ax.set_ylim(0.2, 1.05); ax.set_ylabel('recall@1'); ax.grid(axis='x', visible=False)
ax.legend(fontsize=7, loc='lower left', title='solid = ours, dashed = hybrid', title_fontsize=7)
ax.set_title('Q3 · bigger bank, per site (gitlab has no 61+ bucket)', loc='left'); save(fig, 'R4_challenge')
print('ok')
