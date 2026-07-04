# hippo-agent — Design

A self-evolving LLM agent built as a **Complementary Learning Systems (CLS)** machine:
a fast hippocampal buffer that encodes *surprising* experience, a consolidation
("replay") engine that distills it, and a slow semantic store that the agent retrieves
from. Lineage: **Honcho** (storage/representation style, self-built here — not its DB),
**Nemori** (prediction-error / "what deserves memory"), **ReasoningBank** (learn from
success *and* failure; LLM-as-a-Judge; append memory items).

## CLS mapping

| Component | Brain role | Job here |
|---|---|---|
| Hippocampal buffer (fast) | one-shot episodic encoding, novelty-gated | log trajectories, gate by surprise |
| Consolidation / replay | offline replay → neocortex | batch prioritized replay + distillation |
| Semantic store (slow) | structured long-term memory | dual store: reasoning + fact |

## Dual memory (two stores, different confidence policies)

- **ReasoningStore** (cross-task, append-only v1): ReasoningBank-style
  `{title, description, content}` + `certainty`. Retrieved by **query similarity**.
- **FactStore** (high-confidence, env-scoped): `{scope, statement, polarity,
  confidence, evidence}`. `polarity=negative` = a *confirmed failure* fact. Retrieved by
  **scope (env id) + similarity**. Consolidated by upsert.

## What is computed vs LLM-extracted (important)

Memory *content* is always **LLM-extracted**. "Computation" is only the **gate**:
1. **detect** (computed): observation-level prediction mismatch flags a candidate.
2. **confirm** (computed, LLM-as-a-Judge): grounds it → makes a fact "certain".
3. **extract** (LLM): writes the actual fact/strategy text.

This is the Nemori / ReasoningBank pattern (gate by a computed signal, extract with an
LLM). The `store_all` baseline = no gate (≈ Honcho/Mem0 "extract everything").

## Surprise (v1, switchable via `surprise.source`)

- `store_all`: no gate, score = 1.0 (ablation upper bound on writes).
- `memory_pred`: retrieve memory → predict solvable? → disagreement with judged outcome.
- `traj_divergence`: run N trajectories, judge each; **mixed success/failure = gold**
  (contrastive, MaTTS-style). Combined v1 score:
  `w_outcome_mix * mix + w_mem_pred * pred_err`, write iff `>= threshold`.

Routing: observation-level prediction error → **fact**; task/strategy-level → **reasoning**.

## Main loop

```
for task in stream:                     # cold start, empty memory
    mem   = retrieve(task)              # fact by scope+sim, reasoning by sim
    trajs = agent.rollout(task, mem, n=n_traj)   # concurrent
    outs  = [judge(t) for t in trajs]   # label-free, grounded on result
    s     = surprise(task, trajs, outs, mem)
    buffer.add(task, trajs, outs, s)    # fast encode
    if end_of_batch and replay.enabled:
        consolidate(buffer)             # prioritized replay → distill → write stores
    log(...)
```

## Ablation matrix (only "what/when we store" changes)

`memory.mode` × `surprise.source` × `n_traj` × `replay.enabled`. Headline comparisons:
`both+traj_divergence` (ours) vs `both+store_all` (no gate) vs `memory.mode=off` (vanilla).

## Eval

Task-stream metrics: success rate, avg steps, and **cumulative SR over the stream**
(does it learn?). Start on a light agent dataset to get a rough number; expand to the
full ReasoningBank benches (WebArena / Mind2Web / SWE-Bench-Verified) later.

## Logging

Structured JSONL, one event per line, keyed `run_id/task_id/traj_id/step_id`: steps,
retrieval hits+scores, **surprise raw signals + final score + write decision + reason**,
memory writes + provenance, judge decisions, per-call tokens/cost, task result. Plus a
per-run human summary and an ablation metrics CSV.
