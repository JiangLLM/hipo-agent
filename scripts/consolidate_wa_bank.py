"""Offline consolidation of a WebArena L2 bank — the fix for the four write-side defects.

WA_FINDINGS.md diagnosed why memory's net effect is ~0: the extracted L2 lessons (a) are
near-duplicates written over and over (7 "read the reviews" lessons), (b) are half dead
weight (23/42 never retrieved) which dilutes cosine, (c) let CONTRADICTORY rules coexist
(subtotal vs grand-total -> t331 coin-flips to the wrong one), and (d) record click-by-click
procedure instead of a judgement principle (t336 burns the 30-step budget).

This script rebuilds the bank offline in three stages:

  1. CLUSTER+MERGE  greedy leader clustering on the full item text; each cluster is rewritten
                    by an LLM into ONE item.
  2. PRINCIPLE-IFY  the same rewrite forces every surviving item into (trigger, rule) form:
                    `description` must be a condition checkable FROM THE TASK TEXT ALONE, and
                    `content` must state what to JUDGE, not which buttons to click. An item
                    that cannot be given a checkable trigger is DROPPED (better absent than
                    coin-flipped). Note retrieval embeds only "title. description", so the
                    trigger has to live in description to affect recall at all.
  3. CONFLICT SWEEP for every surviving pair above --conflict-threshold, an LLM decides
                    whether they conflict and resolves it: collapse into ONE branched rule
                    when the branch is checkable from the task text, otherwise keep the
                    single better rule and drop the loser. Contradictions are never left
                    side by side, because that is exactly what makes retrieval a coin flip.

Output is a memory.json the runner can load as a frozen bank (embeddings are cleared, so
MemoryStore.load re-embeds them), plus a markdown report of every decision for eyeballing.

    .venv-wa/bin/python scripts/consolidate_wa_bank.py \
        runs/wa_shopping_.../memory.json runs/shopping_bank_clean.json \
        --report runs/shopping_consolidation.md

Then validate with a symmetric A/B against the same site:
    ARMS=nomem,frozenmem MEM=runs/shopping_bank_clean.json bash scripts/run_wa_sym.sh shopping
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sys

import numpy as np

REWRITE_SYS = """You maintain a lesson bank for an autonomous web-navigation agent working on \
a shopping/admin/forum website. You are given one or more EXISTING lessons that cover \
overlapping ground. Rewrite them into ONE lesson, or drop them.

Two hard requirements, because the bank they came from failed for exactly these reasons:

1. TRIGGER, not vibes. `description` must state a condition an agent can check by reading the \
TASK QUESTION ALONE, before it has looked at any page — e.g. "the task asks how much was spent \
over a date range" is checkable; "when the order history is paginated" is NOT (that needs the \
page). Phrase it as "Use when <checkable condition>." plus, if useful, "Do not use when \
<checkable exception>." If no such condition exists for this lesson, drop it.

2. PRINCIPLE, not procedure. `content` must say what to DECIDE or VERIFY, in a way that stays \
true if the page layout or the step budget changes. Do NOT transcribe click paths ("go to My \
Account, then My Orders, then use the Show control, then open each order"): those overfit one \
successful run and, when the step budget is tighter, they burn the whole episode and produce no \
answer. State the judgement (which quantity counts, what disqualifies a candidate, what to \
preserve verbatim) and at most a short hint about where the evidence lives.

3. SHORT. `description` is at most 2 sentences; `content` is at most 3 sentences and 70 words. \
A lesson that grows into a manual is not a lesson: it gets retrieved for everything, bloats the \
prompt and buries the one decision that mattered. If the inputs really contain several unrelated \
decisions, keep the most load-bearing one and drop the rest rather than concatenating them.

Delete repetition, filler and narration. Prefer one crisp sentence over three vague ones. Never \
invent a rule the inputs do not support.

Respond with JSON only:
{"drop": false, "title": str, "description": str, "content": str}
or, if the lesson has no task-checkable trigger or no transferable principle:
{"drop": true, "why": str}"""

CONFLICT_SYS = """You maintain a lesson bank for an autonomous web-navigation agent. Two lessons \
below may give CONFLICTING instructions. Conflicting lessons that sit side by side are worse than \
one lesson, because retrieval picks whichever wording happens to score higher and the agent then \
follows the wrong rule.

Decide:
- "none"     — they do not actually conflict (different situations, compatible advice).
- "branch"   — they conflict, but WHICH one applies is decidable from the TASK QUESTION ALONE. \
Return ONE merged lesson whose content states the branch explicitly ("if the question says X do \
A, otherwise do B") and whose description covers both cases.
- "keep_a" / "keep_b" — they conflict and the branch is NOT decidable from the task question. \
Keep the single rule that is right in the general/default case and discard the other. Say which \
in "why".

For "branch", the merged lesson must stay short: description at most 2 sentences, content at most \
3 sentences and 70 words, stating the branch as a decision rather than a click path.

Respond with JSON only:
{"verdict": "none"|"branch"|"keep_a"|"keep_b", "why": str,
 "title": str, "description": str, "content": str}   // the three text fields only for "branch"
"""


def _json(text: str) -> dict:
    """Pull the first JSON object out of a model reply, tolerating stray backslashes."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    blob = m.group(0)
    for candidate in (blob, re.sub(r'\\(?![\\/"bfnrtu])', r"\\\\", blob)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return {}


def _text(it: dict) -> str:
    return f"{it.get('title','')}. {it.get('description','')} {it.get('content','')}".strip()


def _embed(llm, texts: list[str]) -> np.ndarray:
    V = np.asarray(llm.embed(texts), dtype=float)
    return V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)


def cluster(V: np.ndarray, threshold: float, max_size: int) -> list[list[int]]:
    """Greedy leader clustering: an item joins the first cluster whose leader it resembles,
    else it founds one. Order-dependent but cheap, stable and easy to audit.

    max_size matters more than it looks: these lessons all come from one site, so on this
    embedding the median pair already sits at ~0.74 and an uncapped cluster happily swallows
    twenty items, which the LLM then rewrites into a manual instead of a lesson."""
    leaders: list[int] = []
    groups: list[list[int]] = []
    for i in range(len(V)):
        for gi, leader in enumerate(leaders):
            if len(groups[gi]) < max_size and float(V[i] @ V[leader]) >= threshold:
                groups[gi].append(i)
                break
        else:
            leaders.append(i)
            groups.append([i])
    return groups


def _render(items: list[dict], idx: list[int]) -> str:
    return "\n\n".join(
        f"[{k}] {items[i].get('title','')}\nwhen: {items[i].get('description','')}\n"
        f"{items[i].get('content','')}"
        for k, i in enumerate(idx)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bank", help="input memory.json from a withmem run")
    ap.add_argument("out", help="output bank for frozenmem")
    ap.add_argument("--layer", default="L2", help="which layer to consolidate ('' = all)")
    # 0.88 ~ the 97th percentile of pairwise cosine on a single-site L2 bank (median is ~0.74,
    # so anything near 0.75 merges everything into a handful of manuals).
    ap.add_argument("--merge-threshold", type=float, default=0.88)
    ap.add_argument("--max-cluster", type=int, default=5)
    ap.add_argument("--conflict-threshold", type=float, default=0.80)
    ap.add_argument("--model", default="gpt-5.6-sol")
    ap.add_argument("--report", default="", help="write a markdown decision log here")
    args = ap.parse_args()

    sys.path.insert(0, "src")
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    except Exception:
        pass
    from hippo.llm import LLMClient

    raw = json.load(open(args.bank)).get("reasoning", [])
    items = [it for it in raw if not args.layer or it.get("layer") == args.layer]
    print(f"bank: {len(raw)} reasoning items -> {len(items)} with layer={args.layer or 'any'}")
    if not items:
        return 1

    llm = LLMClient(model=args.model, embed_model="local/BAAI/bge-small-en-v1.5",
                    max_tokens=8000, budget_usd=float(os.environ.get("BUDGET", "1000")))
    log: list[str] = [f"# Consolidation of `{args.bank}`\n",
                      f"input: {len(items)} L2 items · merge>={args.merge_threshold} "
                      f"(max cluster {args.max_cluster}) · conflict>={args.conflict_threshold} "
                      f"· model={args.model}\n"]

    # ---- stage 1+2: cluster, then merge/principle-ify each cluster (singletons too) --------
    V = _embed(llm, [_text(it) for it in items])
    groups = cluster(V, args.merge_threshold, args.max_cluster)
    print(f"stage1: {len(groups)} clusters "
          f"({sum(1 for g in groups if len(g) > 1)} multi-item)")
    log.append(f"\n## Stage 1+2 — merge & principle-ify ({len(groups)} clusters)\n")

    kept: list[dict] = []
    n_dropped = 0
    for g in groups:
        titles = [items[i].get("title", "") for i in g]
        out = _json(llm.chat([{"role": "system", "content": REWRITE_SYS},
                              {"role": "user", "content": _render(items, g)}],
                             temperature=0.0))
        if out.get("drop") is True:
            n_dropped += len(g)
            log.append(f"\n- **DROP** {titles} — {out.get('why','(no reason)')}")
            continue
        if not out.get("title") or not out.get("content"):
            # never silently lose coverage on a parse failure: keep the cluster leader as-is
            kept.append(dict(items[g[0]]))
            log.append(f"\n- **PARSE-FAIL, kept original** «{titles[0]}» (cluster {titles})")
            continue
        base = dict(items[g[0]])
        base.update(title=out["title"], description=out.get("description", ""),
                    content=out["content"], embedding=None,
                    source_traj_ids=sorted({s for i in g
                                            for s in (items[i].get("source_traj_ids") or [])}))
        kept.append(base)
        verb = "MERGE" if len(g) > 1 else "REWRITE"
        log.append(f"\n- **{verb}** {titles}\n  -> «{base['title']}»\n"
                   f"  - when: {base['description']}\n  - rule: {base['content']}")
    print(f"stage1+2: {len(items)} -> {len(kept)} kept ({n_dropped} dropped)")

    # ---- stage 3: conflict sweep over surviving pairs --------------------------------------
    log.append(f"\n## Stage 3 — conflict sweep ({len(kept)} items)\n")
    V2 = _embed(llm, [_text(it) for it in kept])
    pairs = [(float(V2[a] @ V2[b]), a, b) for a, b in itertools.combinations(range(len(kept)), 2)]
    pairs = sorted((p for p in pairs if p[0] >= args.conflict_threshold), reverse=True)
    print(f"stage3: {len(pairs)} candidate pairs above {args.conflict_threshold}")
    dead: set[int] = set()
    n_branch = n_drop3 = 0
    for cos, a, b in pairs:
        if a in dead or b in dead:
            continue
        A, B = kept[a], kept[b]
        blob = (f"[A] {A['title']}\nwhen: {A['description']}\n{A['content']}\n\n"
                f"[B] {B['title']}\nwhen: {B['description']}\n{B['content']}")
        out = _json(llm.chat([{"role": "system", "content": CONFLICT_SYS},
                              {"role": "user", "content": blob}], temperature=0.0))
        v = out.get("verdict")
        if v == "branch" and out.get("title") and out.get("content"):
            kept[a] = {**A, "title": out["title"], "description": out.get("description", ""),
                       "content": out["content"], "embedding": None,
                       "source_traj_ids": sorted({*(A.get("source_traj_ids") or []),
                                                  *(B.get("source_traj_ids") or [])})}
            dead.add(b)
            n_branch += 1
            log.append(f"\n- **BRANCH** (cos={cos:.3f}) «{A['title']}» + «{B['title']}»\n"
                       f"  - why: {out.get('why','')}\n  -> «{kept[a]['title']}»\n"
                       f"  - when: {kept[a]['description']}\n  - rule: {kept[a]['content']}")
        elif v in ("keep_a", "keep_b"):
            loser = b if v == "keep_a" else a
            dead.add(loser)
            n_drop3 += 1
            log.append(f"\n- **{v.upper()}** (cos={cos:.3f}) «{A['title']}» vs «{B['title']}»"
                       f" — dropped «{kept[loser]['title']}»\n  - why: {out.get('why','')}")
        # "none" / unparseable -> leave both alone

    final = [it for i, it in enumerate(kept) if i not in dead]
    print(f"stage3: {n_branch} branched, {n_drop3} contradictions resolved by dropping "
          f"-> {len(final)} final items")

    for it in final:                       # frozen bank: let the store re-embed on load
        it["embedding"] = None
        it["layer"] = args.layer or it.get("layer", "")
    json.dump({"reasoning": final, "fact": []}, open(args.out, "w"))

    log.append(f"\n## Result\n\n{len(items)} -> {len(final)} items "
               f"({n_dropped} dropped as untriggerable, {n_branch} branched, "
               f"{n_drop3} contradictions collapsed) · LLM cost ${llm.spent_usd:.2f}\n")
    log.append("\n## Final bank\n")
    for it in final:
        log.append(f"\n### «{it['title']}»\n- when: {it['description']}\n- rule: {it['content']}")
    if args.report:
        open(args.report, "w").write("\n".join(log))
        print(f"report -> {args.report}")
    print(f"{len(items)} -> {len(final)} items, cost ${llm.spent_usd:.2f} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
