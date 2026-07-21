"""Targeted probe: run previously-failed tasks through the confidence gate manually.
For each: solo (no memory) -> assess confidence -> if not confident, retry with retrieved
memory. Shows whether the gate rescues genuine failures without perturbing confident ones.
"""
import json
import importlib.resources as ir

from hippo.config import load_config
from hippo.wa.data import set_site_env
from hippo.wa.run import _fix_webarena_grader
from hippo.llm import LLMClient
from hippo.wa.brain import WaBrain
from hippo.memory import Memory
from hippo.wa.rollout import run_episode, compact_trace

raw = {x["task_id"]: x for x in json.loads(ir.files("webarena").joinpath("test.raw.json").read_text())}
cfg = load_config(["--wa.base_url", "http://10.44.12.29", "--wa.site", "shopping_admin",
                   "--wa.confidence_gate", "on", "--memory.retrieve_k_reasoning", "1",
                   "--wa.max_steps", "30", "--wa.step_timeout", "90", "--wa.reset_timeout", "120",
                   "--llm.model", "gpt-5.6-sol", "--llm.embed_model", "local/BAAI/bge-small-en-v1.5"])
set_site_env(cfg)
_fix_webarena_grader()
llm = LLMClient(model="gpt-5.6-sol", embed_model="local/BAAI/bge-small-en-v1.5",
                temperature=0.7, max_tokens=8000, cache=False)
brain = WaBrain(llm)
BANKS = {"shopping_admin": "runs/wa_shopping_admin_20260719_182647_20260719_182649/memory.json",
         "gitlab": "runs/wa_gitlab_20260719_161841_20260719_161843/memory.json"}
mems = {}
for s, p in BANKS.items():
    m = Memory(llm.embed, cfg); m.load(p); mems[s] = m

TESTS = [("shopping_admin", 212), ("shopping_admin", 288), ("gitlab", 136), ("gitlab", 309)]
for site, T in TESTS:
    scope = f"site:{site}"
    solo = run_episode(T, "", cfg, llm); solo["trace"] = compact_trace(solo["steps"])
    conf = brain.assess_confidence(raw[T]["intent"], solo["trace"], solo["stop_answer"])
    print(f"\n=== {site} t{T}: {raw[T]['intent'][:50]} | gold {list(raw[T]['eval']['reference_answers'].values())}", flush=True)
    print(f"  solo: ans={solo['stop_answer'][:45]!r} reward={solo['reward']} confident={conf}", flush=True)
    if not conf:
        pairs = mems[site].reasoning.topk_scored(raw[T]["intent"][:2000], 1, 0.0, scope=scope)
        mt = mems[site].render({"reasoning": [it for it, _ in pairs]})
        retry = run_episode(T, mt, cfg, llm)
        tag = "RESCUED" if retry["reward"] > solo["reward"] else ("tie" if retry["reward"] == solo["reward"] else "WORSE")
        print(f"  -> consulted {[it.title for it, _ in pairs]}", flush=True)
        print(f"  retry-with-mem: ans={retry['stop_answer'][:45]!r} reward={retry['reward']}  [{tag}]", flush=True)
    else:
        print("  -> confident, kept solo (no perturbation)", flush=True)
print("\nPROBE DONE", flush=True)
