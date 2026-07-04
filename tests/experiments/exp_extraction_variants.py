"""Self-contained A/B: new-L1 vs L2-gold vs L2-no-gold (vs nomem), stream from scratch.

Run:  python3 tests/experiments/exp_extraction_variants.py [--limit N]
Needs OPENAI_API_KEY in .env. All extraction variants are INLINED here (src untouched).

Variant definitions (honest):
  * L1_NEW      : gold-anchored; correct control fixed from gold; emit intent/cue/trap;
                  de-literalize task specifics in code. (single greedy attempt is enough)
  * L2_GOLD     : cross-sample contrastive distillation; the GOLD action IS shown to the
                  extractor as ground truth. (needs N>1 to create divergence)
  * L2_NOGOLD   : same contrastive distillation but the GOLD action is NOT shown to the
                  extractor (ReasoningBank-style: learn from self-experience). NOTE: which
                  attempts count as "correct" (for the divergence gate) still comes from
                  pos_ids in BOTH — that is the experimental scoring, not the memory content.
Scoring mirrors src/hippo/m2w/run.py (element_acc / step_success), retrieval = per-step
top-4 by embedding cosine (like src/hippo/memory/store.py). Memory grows from scratch,
task-level update with upsert dedup, paired against the same nomem baseline.
"""
import json, os, re, math, time, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("EXP_MODEL", "gpt-4o-mini")

def _key():
    for l in open(os.path.join(HERE, "..", "..", ".env")):
        if l.startswith("OPENAI_API_KEY="):
            return l.split("=", 1)[1].strip()
    raise RuntimeError("no OPENAI_API_KEY in .env")
_K = _key()

def _post(url, payload, tries=8):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                headers={"Authorization": "Bearer " + _K, "content-type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        except Exception as e:  # noqa: BLE001
            last = e; time.sleep(min(3 * (i + 1), 20))
    raise last

def chat(m, temp=0.0):
    return _post("https://api.openai.com/v1/chat/completions",
        {"model": MODEL, "temperature": temp, "messages": m, "stop": ["Task:", "Observation:"]})["choices"][0]["message"]["content"]

def embed(t):
    if not t:
        return []
    out = []
    for i in range(0, len(t), 300):
        out += [e["embedding"] for e in _post("https://api.openai.com/v1/embeddings",
            {"model": "text-embedding-3-small", "input": t[i:i + 300]})["data"]]
    return out

def js(t):
    m = re.search(r"\{.*\}", t, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001
        return {}

def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) + 1e-9)

# --- de-literalization ---
def parse_control(g):
    m = re.match(r"\s*\[([^\]]*)\]\s*(.*?)\s*->\s*(\S+)", g or "")
    return (m.group(1).strip(), m.group(2).strip(), m.group(3).strip()) if m else ("", "", "")

def dangerous(prompt, gold):
    terms = set()
    for sp in re.findall(r"\b[A-Z][A-Za-z0-9'&]*(?:\s+[A-Z][A-Za-z0-9'&]*)+", prompt):
        terms.add(sp.lower())
    for mth in ("january february march april may june july august september october november december").split():
        if re.search(r"\b" + mth + r"\b", prompt, re.I):
            terms.add(mth)
    for t in re.findall(r"\b\w*\d[\w:]*\b", prompt.lower()):
        terms.add(t)
    for m in re.finditer(r"(?:TYPE|SELECT):\s*([^-\n]+)", gold, re.I):
        v = m.group(1).strip().lower()
        if v:
            terms.add(v)
    return {t for t in terms if len(t) >= 3}

def delist(text, terms):
    for t in sorted(terms, key=len, reverse=True):
        if t:
            text = re.sub(r"\b" + re.escape(t) + r"\b", "", text, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip(" ,.;:-\u2013")

# --- EXTRACTION VARIANTS ---
def extract_l1_new(goal, obs, thought, action, is_correct, gold_repr):
    role, label, _ = parse_control(gold_repr)
    verdict = "CORRECT" if is_correct else "WRONG"
    sysp = ("You label ONE web-navigation step into a reusable DECISION RULE. The CORRECT control is "
        "ALREADY GIVEN (parsed from gold). Do NOT decide correctness; only describe how to recognize it "
        "and the trap.\nGiven: sub-goal, page candidates, agent REASONING and chosen ACTION, verdict, and "
        "CORRECT_CONTROL={role,label}.\n"
        'Return JSON {"genuine":bool,"reason":str,"intent":str,"cue":str,"trap":str}.\n'
        "- genuine: WRONG->false. CORRECT->true only if reasoning names the real discriminative cue.\n"
        "- intent: GENERIC user sub-goal, 3-6 word verb phrase; GENERALIZE specifics ('find events in a "
        "city' NOT 'in New York City'). BAD: a control name; button/filter/link/element; 'page-state'.\n"
        "- cue: how to recognize CORRECT_CONTROL by visible text/role, <=15 words; same generalization.\n"
        "- trap: ONLY the visible label of the WRONG control picked, <=5 words, MUST differ from "
        "CORRECT_CONTROL.label; else ''.\n"
        "- HARD: CORRECT_CONTROL.label is ground truth; NEVER name a different control as correct. "
        "intent and cue non-empty. NEVER copy product/place/date/number/color/size into intent or cue.")
    usr = (f"SUB-GOAL: {goal}\nPAGE candidates: {obs[:600]}\nAGENT reasoning: {thought}\n"
           f"AGENT chose: {action}\nCORRECT_CONTROL: role={role} label={label!r}\nVerdict: {verdict}")
    out = js(chat([{"role": "system", "content": sysp}, {"role": "user", "content": usr}], 0.0))
    genuine = bool(out.get("genuine", False)) if is_correct else False
    if (is_correct and genuine) or not label:
        return None
    lit = dangerous(goal, gold_repr)
    intent = delist(str(out.get("intent", "")).strip(), lit)
    cue = delist(str(out.get("cue", "")).strip(), lit)
    trap = str(out.get("trap", "")).strip()
    if (not trap) or trap.lower() == label.lower() or re.match(r"(CLICK|TYPE|SELECT|HOVER)\b", trap, re.I):
        trap = ""
    if not intent:
        return None
    stmt = f"When {intent}: use '{label}' ({role})" + (f", not '{trap}'" if trap else "") + (f". {cue}" if cue else "")
    key = re.sub(r"[^a-z0-9]+", "-", f"{role}:{label}:{intent}".lower()).strip("-")[:80]
    return [{"statement": stmt, "key": key}]

def extract_l2(goal, obs, attempts, gold_repr, use_gold):
    n = len(attempts); nc = sum(1 for a in attempts if a["correct"])
    if not (0 < nc < n):
        return []
    majority = "correct" if nc * 2 >= n else "wrong"
    direction = ("MOST attempts FAILED and a few succeeded -> summarize HOW to do this step CORRECTLY."
                 if majority == "wrong" else
                 "MOST attempts SUCCEEDED and a few failed -> summarize the trap the failing attempt(s) fell into.")
    gold_line = (f"GROUND TRUTH (gold) correct action: {gold_repr}\n" if use_gold else
                 "You are NOT given the gold answer. Infer the reliable pattern ONLY from which "
                 "self-judged attempts succeeded vs failed.\n")
    sysp = ("You are an expert in web navigation. For ONE step, an agent made N parallel attempts (some "
        "correct, some wrong). " + ("Use the gold action as ground truth. " if use_gold else "") +
        "Contrast why some succeeded and others failed.\n" + direction + "\n"
        "Each item: title / description(WHEN to use) / content(1-3 sentences, how to pick the right control).\n"
        "Rules: describe controls by general function + visible text, NEVER numeric id; NEVER copy any "
        "value from the goal (products, places, dates, numbers). At most 3 items.\n"
        'Return JSON {"facts":[{"title":str,"description":str,"content":str,"key":str}]}')
    lines = [f"GOAL: {goal}", f"PAGE candidates: {obs[:600]}", gold_line, f"{n} attempts, {nc} correct:"]
    for i, a in enumerate(attempts):
        lines.append(f"  attempt{i+1} [{'ok' if a['correct'] else 'wrong'}]: {a['thought'][:160]} -> chose {a['chosen']}")
    out = js(chat([{"role": "system", "content": sysp}, {"role": "user", "content": "\n".join(lines)}], 0.0))
    lit = dangerous(goal, gold_repr if use_gold else goal)
    items = []
    for f in out.get("facts", []):
        if not isinstance(f, dict):
            continue
        title = (f.get("title") or "").strip(); content = (f.get("content") or "").strip()
        body = content or title
        if not body:
            continue
        stmt = delist(f"{title}: {body}" if title else body, lit)
        if stmt:
            items.append({"statement": stmt, "key": f.get("key")})
    return items

# --- agent + scoring ---
_SYS = ("You are an agent navigating the web. Given the task, the trajectory so far, and the current page "
    "elements, first reason briefly about which element advances the task and why, then output the next "
    "action. Action space:\n1. CLICK [id]\n2. TYPE [id] [value]\n3. SELECT [id] [value]\n"
    "Respond in EXACTLY this format:\nThought: <one concise sentence on why this element>\nAction: `CLICK [123]`")

def predict(goal, hist, obs, mem, temp=0.0):
    msgs = [{"role": "system", "content": _SYS}]
    if mem:
        msgs.append({"role": "user", "content": "Lessons from past tasks:\n" + mem})
    msgs.append({"role": "user", "content": f"Task: {goal}\nTrajectory:\n{hist}Observation: `{obs}`"})
    resp = chat(msgs, temp)
    tm = re.search(r"Thought:\s*(.+?)(?:\n|Action:)", resp, re.S)
    am = re.search(r"Action:\s*`([^`]+)`", resp) or re.search(r"`([^`]+)`", resp)
    return (tm.group(1).strip() if tm else ""), (am.group(1) if am else (resp.splitlines()[-1] if resp.strip() else "")).strip()

def eaf(act, pos):
    m = re.search(r"\[(\d+)\]", act)
    return 1 if (m and m.group(1) in pos) else 0

def load_eval(limit=None):
    tasks = json.load(open(os.path.join(HERE, "data", "eval_tasks_49.json")))
    return tasks[:limit] if limit else tasks

def mean(x):
    return sum(x) / len(x) if x else 0.0

def run(cond, tasks, n_traj):
    steps = []
    for ti, t in enumerate(tasks):
        hist = ""
        for si, st in enumerate(t["steps"]):
            if st["solvable"]:
                steps.append(dict(ti=ti, si=si, goal=t["goal"], site=t["site"], obs=st["obs"], hist=hist,
                                  pos=st["pos_ids"], tgt=st["target_act"], repr=st["act_repr"]))
            hist += f"Observation: `{st['target_obs']}`\nAction: `{st['target_act']}` ({st['act_repr']})\n"
    q = embed([f"{s['goal']}\n{s['obs'][:400]}" for s in steps]); qmap = {(s["ti"], s["si"]): q[i] for i, s in enumerate(steps)}
    bytask = defaultdict(list)
    for s in steps:
        bytask[s["ti"]].append(s)
    mem = []; ea = defaultdict(list); ss = defaultdict(list); nwrite = 0; empty = 0
    for ti in range(len(tasks)):
        ts = bytask[ti]
        if not ts:
            continue
        site = ts[0]["site"]; snap = [f for f in mem if f["site"] == site]
        def mtext(s):
            if not snap:
                return ""
            return "\n".join("[fact] " + f["stmt"] for f in sorted(snap, key=lambda f: -cos(qmap[(s["ti"], s["si"])], f["e"]))[:4])
        nr = 1 if cond in ("nomem", "L1new") else n_traj
        def roll(s):
            outs = []
            for r in range(nr):
                th, act = predict(s["goal"], s["hist"], s["obs"], mtext(s), 0.0 if r == 0 else 0.7 + 0.01 * r)
                outs.append({"r": r, "thought": th, "chosen": act, "correct": bool(eaf(act, s["pos"]))})
            return s, outs
        with ThreadPoolExecutor(16) as ex:
            packed = list(ex.map(roll, ts))
        for s, outs in packed:
            g = next((o for o in outs if o["r"] == 0), outs[0])
            if g["chosen"].strip() == "":
                empty += 1
            ea[ti].append(1 if g["correct"] else 0)
            ss[ti].append(1 if g["chosen"].strip() == s["tgt"].strip() else 0)
        def learn(pk):
            s, outs = pk
            g = next((o for o in outs if o["r"] == 0), outs[0])
            if cond == "L1new":
                return extract_l1_new(s["goal"], s["obs"], g["thought"], g["chosen"], g["correct"], s["repr"]) or []
            if cond == "L2gold":
                return extract_l2(s["goal"], s["obs"], outs, s["repr"], use_gold=True)
            if cond == "L2nogold":
                return extract_l2(s["goal"], s["obs"], outs, s["repr"], use_gold=False)
            return []
        if cond != "nomem":
            with ThreadPoolExecutor(16) as ex:
                newp = list(ex.map(learn, packed))
            flat = [x for sub in newp for x in sub]
            nwrite += len(flat)
            if flat:
                E = embed([x["statement"] for x in flat])
                for j, x in enumerate(flat):
                    key = x.get("key")
                    hit = next((f for f in mem if f["site"] == site and key is not None and f.get("key") == key), None)
                    if hit:
                        hit["stmt"] = x["statement"]; hit["e"] = E[j]
                    else:
                        mem.append({"site": site, "key": key, "stmt": x["statement"], "e": E[j]})
    n = len(tasks); h = n // 2
    def half(d, lo, hi):
        return mean([v for ti in range(lo, hi) for v in d[ti]])
    return {"element_acc": mean([v for ti in ea for v in ea[ti]]), "step_success": mean([v for ti in ss for v in ss[ti]]),
            "mem": len(mem), "writes": nwrite, "empty": empty,
            "gap1": half(ea, 0, h) if cond != "nomem" else 0.0, "gap2": half(ea, h, n) if cond != "nomem" else 0.0,
            "_ea": ea}

def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    n_traj = 3
    tasks = load_eval(limit)
    nsolv = sum(1 for t in tasks for s in t["steps"] if s["solvable"])
    print(f"eval: {len(tasks)} tasks, {nsolv} solvable steps, N={n_traj}, model={MODEL}", flush=True)
    R = {}
    for c in ("nomem", "L1new", "L2gold", "L2nogold"):
        R[c] = run(c, tasks, n_traj)
        r = R[c]
        print(f"[done] {c:9} element_acc={r['element_acc']:.3f} step={r['step_success']:.3f} "
              f"mem={r['mem']} writes={r['writes']} empty={r['empty']}", flush=True)
    base = R["nomem"]
    nm_ea = base["_ea"]; n = len(tasks); h = n // 2
    def half(d, lo, hi):
        return mean([v for ti in range(lo, hi) for v in d[ti]])
    print("\n=== EXTRACTION VARIANTS RESULT ===")
    print(f"{'cond':9} {'element_acc':>11} {'Δelem':>7} {'step_succ':>10} {'mem':>5} {'writes':>7} {'empty':>6}")
    for c in ("nomem", "L1new", "L2gold", "L2nogold"):
        r = R[c]
        print(f"{c:9} {r['element_acc']:>11.3f} {r['element_acc']-base['element_acc']:>+7.3f} "
              f"{r['step_success']:>10.3f} {r['mem']:>5} {r['writes']:>7} {r['empty']:>6}")
    print("\n=== self-evolution gap (element_acc vs nomem, by task order) ===")
    for c in ("L1new", "L2gold", "L2nogold"):
        ea = R[c]["_ea"]
        g1 = half(ea, 0, h) - half(nm_ea, 0, h); g2 = half(ea, h, n) - half(nm_ea, h, n)
        print(f"{c:9} 1st={g1:+.3f} 2nd={g2:+.3f} {'widen' if g2 > g1 else 'flat/への'}")
    print("=== END (trust only the numeric table above) ===")

if __name__ == "__main__":
    main()
