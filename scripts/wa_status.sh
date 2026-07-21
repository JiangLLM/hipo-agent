#!/bin/bash
# One-glance progress of all recent WebArena site runs. Run it anytime:
#   bash scripts/wa_status.sh
cd "$(dirname "$0")/.."
.venv-wa/bin/python - <<'PY'
import json,glob,time,os,subprocess
rows=[]
for d in sorted(glob.glob("runs/wa_*_2*/"), key=os.path.getmtime, reverse=True):
    ev=os.path.join(d,"events.jsonl")
    if not os.path.exists(ev): continue
    # infer site from run name
    name=os.path.basename(d.rstrip("/"))
    site=name.split("_20")[0].replace("wa_","")
    nm=[];wm=[];l1=l2=0;last_t=0;cur=""
    for l in open(ev):
        try: dd=json.loads(l)
        except: continue
        last_t=max(last_t,dd.get("t",0));k=dd.get("kind")
        if k=="wa_task":
            (nm if dd["tag"]=="nomem" else wm).append(dd["reward"])
            if dd["tag"]=="withmem": l1=dd.get("l1_total",l1);l2=dd.get("l2_total",l2)
        if k=="wa_step": cur=f"{dd.get('tag')} t{dd.get('task_id')} step{dd.get('step')}"
    tot={"gitlab":43,"shopping_admin":88,"shopping":88,"reddit":11}.get(site,"?")
    alive=subprocess.call(f"pgrep -f 'wa.site {site}' >/dev/null",shell=True)==0
    idle=int(time.time()-last_t)
    # only show runs touched in last 6h
    if idle>21600: continue
    st="跑" if alive else ("完/停" )
    rows.append((site,tot,nm,wm,l1,l2,cur,idle,st))
if not rows: print("没有近期运行"); raise SystemExit
print(f"{'站点':<16}{'状态':<6}{'nomem':<12}{'withmem':<12}{'L1/L2':<8}{'当前/停顿'}")
for site,tot,nm,wm,l1,l2,cur,idle,st in rows:
    ns=f"{len(nm)}/{tot} SR{sum(nm)}"
    ws=f"{len(wm)}/{tot} SR{sum(wm)}"
    tail=f"{cur}" if st=="跑" else f"idle{idle}s"
    warn=" !!卡?" if (st=="跑" and idle>420) else ""
    print(f"{site:<16}{st:<6}{ns:<12}{ws:<12}{str(l1)+'/'+str(l2):<8}{tail}{warn}")
PY
