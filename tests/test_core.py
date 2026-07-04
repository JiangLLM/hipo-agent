"""Core correctness tests (run offline, no API)."""
from __future__ import annotations

from hippo.config import load_config
from hippo.schema import Outcome
from hippo.surprise import compute_surprise


def _cfg(**over):
    argv = ["--mock"]
    for k, v in over.items():
        argv += [f"--{k}", str(v)]
    return load_config(argv)


def test_config_overrides():
    cfg = _cfg(**{"memory.mode": "off", "agent.n_traj": 3})
    assert cfg.memory.mode == "off"
    assert cfg.agent.n_traj == 3
    assert cfg.run.get("mock") is True


def _outs(*successes):
    return [Outcome(success=s, can_derive=True) for s in successes]


def test_store_all_always_writes():
    cfg = _cfg(**{"surprise.source": "store_all"})
    r = compute_surprise(cfg, [], _outs(True, True), predicted_solvable=True)
    assert r.write and r.score == 1.0


def test_memory_pred_gate():
    cfg = _cfg(**{"surprise.source": "memory_pred"})
    # predicted solvable + all succeeded -> nothing new
    assert not compute_surprise(cfg, [], _outs(True, True), True).write
    # predicted solvable but failed -> surprise
    assert compute_surprise(cfg, [], _outs(False, False), True).write
    # couldn't derive from memory -> surprise
    assert compute_surprise(cfg, [], _outs(True), False).write


def test_traj_divergence_mixed_is_gold():
    cfg = _cfg(**{"surprise.source": "traj_divergence"})
    mixed = compute_surprise(cfg, [], _outs(True, False, False), predicted_solvable=True)
    settled = compute_surprise(cfg, [], _outs(True, True, True), predicted_solvable=True)
    assert mixed.write and mixed.score > settled.score
    assert not settled.write


def test_memory_beats_no_memory_and_is_deterministic():
    from hippo.run import run

    nomem = run(_cfg(**{"memory.mode": "off", "run.name": "t_nomem"}))
    dual1 = run(_cfg(**{"memory.mode": "both", "surprise.source": "traj_divergence", "run.name": "t_d1"}))
    dual2 = run(_cfg(**{"memory.mode": "both", "surprise.source": "traj_divergence", "run.name": "t_d2"}))
    assert dual1["sr_pass1"] > nomem["sr_pass1"]      # memory helps
    assert dual1["sr_pass1"] == dual2["sr_pass1"]      # reproducible
    assert dual1["writes"] < 60                        # surprise gating writes less than store-all
