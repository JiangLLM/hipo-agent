"""Offline memory consolidation — the CLS "sleep" pass.

The slice experiment showed the bank has an operating window: 243 items helped
(+4.3 on held-out tasks), 277+ hurt, and the damage is layer-agnostic. This script
is the motivated fix: cluster near-duplicate items by embedding similarity and let
an LLM merge each cluster into ONE sharper item, shrinking the bank without
discarding coverage.

    .venv/bin/python scripts/consolidate_bank.py <bank.json> <out.json> \
        [--threshold 0.7] [--model anthropic/claude-haiku-4-5]
"""
from __future__ import annotations

import argparse
import json
import re
import sys

import numpy as np


MERGE_SYS = (
    "You maintain a memory bank of repository lessons for a coding agent. Below are "
    "several EXISTING items that cover overlapping ground. Consolidate them into ONE "
    "item that keeps every distinct, actionable insight and drops repetition and filler.\n"
    'Respond JSON {"title": str, "description": str (WHEN this applies), '
    '"content": str (1-3 sentences, concrete)}.\n'
    "Keep file paths and command names; never invent new claims."
)


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    blob = m.group(0)
    for candidate in (blob, re.sub(r'\\(?![\\/"bfnrtu])', r"\\\\", blob)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return {}


def cluster(vectors: np.ndarray, threshold: float) -> list[list[int]]:
    """Greedy leader clustering: an item joins the first cluster whose leader it
    resembles; otherwise it founds a new one. Order-dependent but cheap and stable."""
    leaders: list[int] = []
    groups: list[list[int]] = []
    for i in range(len(vectors)):
        for gi, leader in enumerate(leaders):
            if float(vectors[i] @ vectors[leader]) >= threshold:
                groups[gi].append(i)
                break
        else:
            leaders.append(i)
            groups.append([i])
    return groups


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bank")
    ap.add_argument("out")
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--model", default="anthropic/claude-haiku-4-5")
    args = ap.parse_args()

    from dotenv import load_dotenv

    load_dotenv("/Users/yutongs/Projects/hipo-agent/.env")
    from fastembed import TextEmbedding

    from hippo.llm import LLMClient

    items = json.load(open(args.bank))["reasoning"]
    emb = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    texts = [f"{it['title']}. {it['description']}" for it in items]
    V = np.array(list(emb.embed(texts)))
    V /= np.linalg.norm(V, axis=1, keepdims=True)

    llm = LLMClient(model=args.model, embed_model="local/BAAI/bge-small-en-v1.5",
                    max_tokens=2000, budget_usd=5)
    groups = cluster(V, args.threshold)
    merged, n_merged = [], 0
    for g in groups:
        if len(g) == 1:
            merged.append(items[g[0]])
            continue
        blob = "\n\n".join(f"[{k}] {items[i]['title']}\nwhen: {items[i]['description']}\n"
                           f"{items[i]['content']}" for k, i in enumerate(g))
        out = _json(llm.chat([{"role": "system", "content": MERGE_SYS},
                              {"role": "user", "content": blob}],
                             temperature=0.0, drop_params=True))
        if out.get("title") and out.get("content"):
            base = dict(items[g[0]])            # inherit scope/id/timestamps from the first
            base.update(title=out["title"], description=out.get("description", ""),
                        content=out["content"], embedding=None)
            merged.append(base)
            n_merged += len(g)
        else:                                    # merge failed -> keep originals (no data loss)
            merged.extend(items[i] for i in g)
    json.dump({"reasoning": merged, "fact": []}, open(args.out, "w"))
    print(f"{len(items)} -> {len(merged)} items "
          f"({sum(1 for g in groups if len(g) > 1)} clusters, {n_merged} items merged), "
          f"llm cost ${llm.spent_usd:.2f}")


if __name__ == "__main__":
    sys.exit(main())
