"""Load Mind2Web split shards and attach ranker scores (scores_all_data.pkl)."""
from __future__ import annotations

import glob
import json
import os
import pickle


def load_split(data_dir: str, split: str) -> list[dict]:
    folder = os.path.join(data_dir, split)
    files = sorted(glob.glob(os.path.join(folder, "*.json")),
                   key=lambda x: int(x.split("_")[-1].split(".")[0]))
    samples: list[dict] = []
    for f in files:
        samples.extend(json.load(open(f)))
    return samples


def add_scores(samples: list[dict], score_path: str) -> list[dict]:
    """Attach DeBERTa-ranker score + rank to every candidate (like AWM)."""
    with open(score_path, "rb") as f:
        cand = pickle.load(f)
    scores, ranks = cand["scores"], cand["ranks"]
    for sample in samples:
        for s in sample["actions"]:
            sid = f"{sample['annotation_id']}_{s['action_uid']}"
            for cands in (s["pos_candidates"], s["neg_candidates"]):
                for c in cands:
                    cid = c["backend_node_id"]
                    c["score"] = scores.get(sid, {}).get(cid, -1e9)
                    c["rank"] = ranks.get(sid, {}).get(cid, 10**9)
    return samples
