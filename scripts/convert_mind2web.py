"""Convert a Mind2Web shard (raw JSON) -> hippo JSONL (one step = one task).

Standard Mind2Web "multichoice" formulation: at each step the agent sees the task
goal, the actions taken so far, and a candidate element list (the gold element +
sampled distractors); it must pick the right element id. Metric = Element Accuracy.

Candidate text is recovered from cleaned_html (Mind2Web stores visible text in
<text backend_node_id="...">CONTENT</text> nodes), which is essential — without it
the elements are indistinguishable and the agent can only guess.

Usage:
  python scripts/convert_mind2web.py data/m2w_train_10.json data/mind2web.jsonl \
      --n_cands 20 --seed 0
"""
from __future__ import annotations

import argparse
import json
import random
import re
from html.parser import HTMLParser


class _TextMap(HTMLParser):
    """Subtree text per node, keyed by backend_node_id."""

    def __init__(self):
        super().__init__()
        self.stack: list[str] = []
        self.text: dict[str, list[str]] = {}

    def handle_starttag(self, tag, attrs):
        bid = dict(attrs).get("backend_node_id")
        if bid is not None:
            self.stack.append(bid)
            self.text.setdefault(bid, [])

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        s = data.strip()
        if not s:
            return
        for bid in self.stack:
            self.text[bid].append(s)


def build_text_map(cleaned_html: str) -> dict[str, str]:
    p = _TextMap()
    try:
        p.feed(cleaned_html)
    except Exception:
        pass
    return {bid: re.sub(r"\s+", " ", " ".join(parts))[:80] for bid, parts in p.text.items()}


def render_candidate(c: dict, text_map: dict[str, str]) -> str:
    tag = c.get("tag", "?")
    try:
        attrs = json.loads(c.get("attributes", "{}"))
    except Exception:
        attrs = {}
    bid = str(c.get("backend_node_id", attrs.get("backend_node_id", "")))
    txt = text_map.get(bid, "")
    keep = []
    for k in ("id", "type", "role", "name", "placeholder", "title", "alt",
              "aria_label", "aria-label", "value"):
        v = attrs.get(k)
        if v:
            keep.append(f'{k}="{str(v)[:30]}"')
        if len(keep) >= 3:
            break
    body = f"<{tag} {' '.join(keep)}>".replace("  ", " ").replace(" >", ">")
    return f'{body} text="{txt}"' if txt else body


def convert(in_path: str, out_path: str, n_cands: int, seed: int) -> int:
    data = json.load(open(in_path))
    rng = random.Random(seed)
    n = 0
    with open(out_path, "w") as out:
        for ex in data:
            website = ex.get("website", "site")
            goal = ex.get("confirmed_task", "")
            reprs = ex.get("action_reprs", [])
            for i, act in enumerate(ex.get("actions", [])):
                pos = act.get("pos_candidates") or []
                if not pos:
                    continue
                text_map = build_text_map(act.get("cleaned_html", ""))
                negs = act.get("neg_candidates") or []
                sample = rng.sample(negs, min(n_cands - 1, len(negs)))
                cands = sample + [pos[0]]
                rng.shuffle(cands)
                gold_id = None
                lines = []
                for j, c in enumerate(cands):
                    cid = f"c{j}"
                    if c is pos[0]:
                        gold_id = cid
                    lines.append(f"{cid}: {render_candidate(c, text_map)}")
                op = act.get("operation", {})
                history = "\n".join(f"  {r}" for r in reprs[:i]) or "  (none)"
                prompt = (
                    f"GOAL: {goal}\n"
                    f"ACTIONS SO FAR:\n{history}\n"
                    f"Choose the single element id to act on next. "
                    f"Operation will be {op.get('op','CLICK')}.\n"
                    f"CANDIDATES:\n" + "\n".join(lines) +
                    "\nAnswer with only the element id (e.g. c3)."
                )
                rec = {
                    "id": f"{ex.get('annotation_id','x')[:8]}_{i}",
                    "prompt": prompt,
                    "scope": f"site:{website}",
                    "task_type": "step",
                    "gold": gold_id,
                    "meta": {"op": op.get("op", "CLICK"), "value": op.get("value", ""),
                             "n_cands": len(cands), "website": website},
                }
                out.write(json.dumps(rec) + "\n")
                n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("in_path")
    ap.add_argument("out_path")
    ap.add_argument("--n_cands", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    total = convert(a.in_path, a.out_path, a.n_cands, a.seed)
    print(f"wrote {total} step-tasks -> {a.out_path}")
