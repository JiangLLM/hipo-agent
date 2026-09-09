"""Build per-task multi-step episodes (the experience unit) from Mind2Web samples.

Each episode = one task with an ordered list of steps. Per step we precompute the
observation (pruned DOM of gold + top-(k-1) ranked negatives), the gold action
string, and the gold element ids — exactly the MindAct/AWM offline setup. The agent
predicts each step with teacher-forced gold history; the whole episode is what our
memory distills from.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ._dom import get_target_act, get_target_obs, get_top_k_obs


@dataclass
class M2WStep:
    obs: str                      # current observation (top-k candidate DOM)
    target_act: str               # gold action string, e.g. "CLICK [123]"
    target_obs: str               # gold-only DOM (for teacher-forced history)
    act_repr: str                 # human-readable, e.g. "[link] NFL -> CLICK"
    pos_ids: list[str]            # gold element backend_node_id(s)
    solvable: bool                # gold present & within top-k candidates


@dataclass
class Episode:
    task_id: str
    task: str                     # confirmed_task (the goal)
    website: str
    domain: str
    subdomain: str
    steps: list[M2WStep] = field(default_factory=list)

    @property
    def scope(self) -> str:
        return f"site:{self.website}"


def build_episodes(samples: list[dict], top_k_elements: int = 5) -> list[Episode]:
    episodes: list[Episode] = []
    for sample in samples:
        ep = Episode(
            task_id=sample["annotation_id"],
            task=sample["confirmed_task"],
            website=sample.get("website", "site"),
            domain=sample.get("domain", ""),
            subdomain=sample.get("subdomain", ""),
        )
        for s, act_repr in zip(sample["actions"], sample.get("action_reprs", [])):
            pos = s.get("pos_candidates") or []
            pos_ids = [c["backend_node_id"] for c in pos][:1]
            in_topk = any(c.get("rank", 10**9) < top_k_elements for c in pos)
            if pos_ids:
                obs, _ = get_top_k_obs(s, top_k_elements)
                target_obs = get_target_obs(_fromstring(s["cleaned_html"]), pos_ids)
                target_act = get_target_act(s, pos_ids[0])
            else:
                obs, target_obs = "", ""
                op = s.get("operation", {})
                target_act = f"{op.get('op','CLICK')} []"
            ep.steps.append(M2WStep(
                obs=obs, target_act=target_act, target_obs=target_obs,
                act_repr=act_repr, pos_ids=pos_ids,
                solvable=bool(pos_ids) and in_topk,
            ))
        episodes.append(ep)
    return episodes


def _fromstring(html: str):
    from lxml import etree

    return etree.fromstring(html)
