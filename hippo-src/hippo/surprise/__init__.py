"""Surprise = the gate deciding whether an experience deserves memory.

Three switchable sources (cfg.surprise.source):
  * store_all       — no gate (ablation upper bound on writes), score = 1.
  * memory_pred     — write when the agent failed or couldn't derive from memory.
  * traj_divergence — N-trajectory contrastive signal: mixed success/failure is gold;
                      all-failed also surprising; all-success+expected is settled.

Returns (score, write?, signals) where signals are logged for post-hoc A/B analysis.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SurpriseResult:
    score: float
    write: bool
    signals: dict


def compute_surprise(cfg, trajs, outcomes, predicted_solvable: bool) -> SurpriseResult:
    n = max(len(outcomes), 1)
    frac_success = sum(1 for o in outcomes if o.success) / n
    any_success = frac_success > 0
    mixed = 0.0 < frac_success < 1.0
    all_failed = frac_success == 0.0
    src = cfg.surprise.source

    if src == "store_all":
        return SurpriseResult(1.0, True, {"source": src, "frac_success": frac_success})

    if src == "memory_pred":
        if predicted_solvable and not any_success:
            score = 1.0            # expected to solve from memory, but failed
        elif not predicted_solvable:
            score = 1.0            # couldn't derive from memory
        else:
            score = 0.0            # predicted solvable and succeeded -> nothing new
        sig = {"source": src, "frac_success": frac_success, "predicted_solvable": predicted_solvable}
        return SurpriseResult(score, score >= cfg.surprise.threshold, sig)

    if src == "traj_divergence":
        outcome_mix = 1.0 if mixed else (1.0 if all_failed else 0.0)
        mem_pred = 0.0 if predicted_solvable else 1.0
        score = cfg.surprise.w_outcome_mix * outcome_mix + cfg.surprise.w_mem_pred * mem_pred
        sig = {"source": src, "frac_success": frac_success, "mixed": mixed,
               "all_failed": all_failed, "outcome_mix": outcome_mix,
               "mem_pred": mem_pred, "predicted_solvable": predicted_solvable}
        return SurpriseResult(score, score >= cfg.surprise.threshold, sig)

    raise ValueError(f"unknown surprise.source: {src!r}")
