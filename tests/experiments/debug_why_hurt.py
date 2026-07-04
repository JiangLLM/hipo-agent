"""Debug WHY memory hurts: align nomem vs a variant per-step, bucket reused/misled,
and on misled steps show the injected facts + whether any names the gold control.

Run: python3 tests/experiments/debug_why_hurt.py [--limit N] [--variant L1new|L2gold|L2nogold]
Self-contained (src untouched). Trust only the structured output after '=== WHY ==='.
"""
import json, os, re, math, time, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("EXP_MODEL", "gpt-4o-mini")

def _key():
    for l in open(os.path.join(HERE, "..", "..", ".env")):
        if l.startswith("OPENAI_API_KEY="):
            return l.split("=", 1)[1].strip()
    raise RuntimeError("no OPENAI_API_KEY")
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

def parse_control(g):
    m = re.match(r"\s*\[([^\]]*)\]\s*(.*?)\s*->\s*(\S+)", g or "")
    return (m.group(1).strip(), m.group(2).strip(), m.group(3).strip()) if m else ("", "", "")

def dangerous(prompt, gold):
    terms = set()
    for sp in re.findall(r"\b[A-Z][A-Za-z0-9'&]*(?:\s+[A-Z][A-Za-z0-9'&]*)+", prompt):
        terms.add(sp.lower())
    for mth in "january february march april may june july august september october november december".split():
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

def extract_l1_new(goal, obs, thought, action, is_correct, gold_repr):
    role, label, _ = parse_control(gold_repr)
    verdict = "CORRECT" if is_correct else "WRONG"
    sysp = ("You label ONE web-navigation step into a reusable DECISION RULE. The CORRECT control is "
        "ALREADY GIVEN (parsed from gold). Do NOT decide correctness; only describe how to recognize it "
        "and the trap.\nGiven: sub-goal, page candidates, agent REASONING and chosen ACTION, verdict, and "
        "CORRECT_CONTROL={role,label}.\n"
        'Return JSON {"genuine":bool,"reason":str,"intent":str,"cue":str,"trap":str}.\n'
        "- genuine: WRONG->false. CORRECT->true only if reasoning names the real discriminative cue.\n"
        "- intent: GENERIC user sub-goal, 3-6 word verb phrase; GENERALIZE specifics. BAD: a control name; "
        "button/filter/link/element; 'page-state'.\n"
        "- cue: how to recognize CORRECT_CONTROL by visible text/role, <=15 words.\n"
        "- trap: ONLY the visible label of the WRONG control picked, <=5 words, MUST differ from label; else ''.\n"
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
    return {"statement": stmt, "key": key, "gold_label": label.lower()}

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

def gold_label_of(repr_str):
    _, lab, _ = parse_control(repr_str)
    return lab.lower()

def main():
    limit = 20
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    tasks = json.load(open(os.path.join(HERE, "data", "eval_tasks_49.json")))[:limit]
    steps = []
    for ti, t in enumerate(tasks):
        hist = ""
        for si, st in enumerate(t["steps"]):
            if st["solvable"]:
                steps.append(dict(ti=ti, si=si, goal=t["goal"], site=t["site"], obs=st["obs"], hist=hist,
                                  pos=st["pos_ids"], tgt=st["target_act"], repr=st["act_repr"]))
            hist += f"Observation: `{st['target_obs']}`\nAction: `{st['target_act']}` ({st['act_repr']})\n"
    print(f"debug: {len(tasks)} tasks, {len(steps)} solvable steps, variant=L1new", flush=True)
    q = embed([f"{s['goal']}\n{s['obs'][:400]}" for s in steps])
    qmap = {(s["ti"], s["si"]): q[i] for i, s in enumerate(steps)}
    bytask = defaultdict(list)
    for s in steps:
        bytask[s["ti"]].append(s)

    # Pass 1: nomem predictions (per step)
    def nm_pred(s):
        _, act = predict(s["goal"], s["hist"], s["obs"], "", 0.0)
        return (s["ti"], s["si"]), eaf(act, s["pos"]), act
    with ThreadPoolExecutor(16) as ex:
        nm = list(ex.map(nm_pred, steps))
    nm_ok = {k: v for k, v, _ in nm}
    nm_act = {k: a for k, _, a in nm}

    # Pass 2: L1new stream (memory grows), record per-step withmem pred + injected facts
    mem = []
    wm_ok = {}; wm_act = {}; injected = {}
    facts_all = []
    for ti in range(len(tasks)):
        ts = bytask[ti]
        if not ts:
            continue
        site = ts[0]["site"]; snap = [f for f in mem if f["site"] == site]
        def mtext_and_facts(s):
            if not snap:
                return "", []
            top = sorted(snap, key=lambda f: -cos(qmap[(s["ti"], s["si"])], f["e"]))[:4]
            return "\n".join("[fact] " + f["stmt"] for f in top), top
        def wm_pred(s):
            mt, top = mtext_and_facts(s)
            _, act = predict(s["goal"], s["hist"], s["obs"], mt, 0.0)
            return s, act, top
        with ThreadPoolExecutor(16) as ex:
            preds = list(ex.map(wm_pred, ts))
        for s, act, top in preds:
            k = (s["ti"], s["si"])
            wm_ok[k] = eaf(act, s["pos"]); wm_act[k] = act
            injected[k] = [(f["stmt"], f.get("gold_label", "")) for f in top]
        # learn (greedy nomem-independent: use the withmem greedy? use nomem greedy for faithfulness)
        def learn(s):
            th, act = predict(s["goal"], s["hist"], s["obs"], mtext_and_facts(s)[0], 0.0)
            return extract_l1_new(s["goal"], s["obs"], th, act, bool(eaf(act, s["pos"])), s["repr"])
        with ThreadPoolExecutor(16) as ex:
            newf = [x for x in ex.map(learn, ts) if x]
        facts_all += newf
        if newf:
            E = embed([x["statement"] for x in newf])
            for j, x in enumerate(newf):
                hit = next((f for f in mem if f["site"] == site and f.get("key") == x["key"]), None)
                if hit:
                    hit["stmt"] = x["statement"]; hit["e"] = E[j]
                else:
                    mem.append({"site": site, "key": x["key"], "stmt": x["statement"], "e": E[j], "gold_label": x["gold_label"]})

    # bucket
    buckets = Counter()
    misled_examples = []
    inj_relevant_on_misled = 0
    for s in steps:
        k = (s["ti"], s["si"])
        a = nm_ok.get(k, 0); b = wm_ok.get(k, 0)
        gl = gold_label_of(s["repr"])
        inj = injected.get(k, [])
        rel = any(gl and gl in stmt.lower() for stmt, _ in inj)  # a fact naming the gold control was injected
        if a == 1 and b == 0:
            buckets["MISLED 本对->被带偏"] += 1
            if len(misled_examples) < 8:
                misled_examples.append((s, gl, inj, nm_act[k], wm_act[k], rel))
        elif a == 0 and b == 1:
            buckets["REUSED 本错->被修对"] += 1
        elif a == 1 and b == 1:
            buckets["both right"] += 1
        elif rel:
            buckets["both wrong + 注入了相关fact(没用上)"] += 1
        else:
            buckets["both wrong + 无相关注入"] += 1

    # injection relevance overall
    n_steps_with_inj = sum(1 for s in steps if injected.get((s["ti"], s["si"])))
    n_rel_hit = 0; n_inj_total = 0; n_rel_total = 0
    for s in steps:
        k = (s["ti"], s["si"]); gl = gold_label_of(s["repr"]); inj = injected.get(k, [])
        n_inj_total += len(inj)
        hits = sum(1 for stmt, _ in inj if gl and gl in stmt.lower())
        n_rel_total += hits
        if hits:
            n_rel_hit += 1

    print("\n=== WHY (nomem vs L1new, aligned per solvable step) ===")
    tot = sum(buckets.values())
    for kk, vv in buckets.most_common():
        print(f"  {vv:4d}  {100*vv//max(tot,1):3d}%   {kk}")
    mis = buckets["MISLED 本对->被带偏"]; reu = buckets["REUSED 本错->被修对"]
    print(f"\n  净(reused - misled) = {reu} - {mis} = {reu - mis}")
    print(f"  记忆最终条数: {len(mem)}  (写入 {len(facts_all)} 次)")
    print(f"\n=== 注入相关性 (top-4 检索是否命中当前步的 gold 控件) ===")
    print(f"  有注入的步: {n_steps_with_inj}/{len(steps)}")
    print(f"  注入的 fact 总数: {n_inj_total}, 其中命中 gold 控件: {n_rel_total} ({100*n_rel_total//max(n_inj_total,1)}%)")
    print(f"  至少注入到1条相关fact的步: {n_rel_hit}/{len(steps)} ({100*n_rel_hit//max(len(steps),1)}%)")
    print(f"\n=== 被带偏的步样例 (本来对, 注入记忆后错) ===")
    for s, gl, inj, na, wa, rel in misled_examples:
        print(f"\n[{s['site']}] gold_control='{gl}'  nomem选->{na}  withmem选->{wa}  {'(注入含相关fact但仍带偏)' if rel else '(注入全是无关fact=噪声挤占)'}")
        for stmt, gll in inj[:4]:
            mark = "  <<命中gold" if (gl and gl in stmt.lower()) else ""
            print(f"     inj: {stmt[:110]}{mark}")
    print(f"\n=== 抽取的 fact 样例 (前8条) ===")
    for f in facts_all[:8]:
        print(f"  - {f['statement'][:120]}")
    print("=== END (trust only the structured output above) ===")

if __name__ == "__main__":
    main()
