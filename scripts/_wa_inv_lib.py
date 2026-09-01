import json, os, collections, sys
sys.path.insert(0,'src')
ROOT='/Users/yutongs/Projects/hipo-agent'
os.chdir(ROOT)
from hippo.config import load_config
from hippo.wa.data import load_tasks

RUNS = {
 'admin1':'runs/wa_fleet_shopping_admin_readonly_20260807_225320_20260807_225403',
 'admin2':'runs/wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530',
 'shop1':'runs/wa_fleet_shopping_readonly_20260803_192709_20260803_192720',
 'shop2':'runs/wa_fleet_shopping_readonly_20260805_182840_20260805_182907',
 'shop3':'runs/wa_fleet_shopping_readonly_20260806_223937_20260806_224018',
}
SITE = {'admin1':'shopping_admin','admin2':'shopping_admin','shop1':'shopping','shop2':'shopping','shop3':'shopping'}

def tasks(site):
    cfg = load_config(['--wa.site', site, '--wa.task_filter','readonly','--wa.base_url','http://x'])
    return {t['task_id']: t for t in load_tasks(cfg)}

def load_run(run):
    """returns dict: per-arm per-task (nc, n) computed from wa_episode_end only,
    plus retrieval, judges, writes."""
    p = RUNS[run]+'/events.jsonl'
    ep = collections.defaultdict(lambda: collections.defaultdict(dict))  # arm -> tid -> rollout -> reward
    judges = collections.defaultdict(lambda: collections.defaultdict(dict))
    ans = collections.defaultdict(lambda: collections.defaultdict(dict))
    retr = {}
    writes = []   # (order_index, kind, task, title)
    errs = collections.defaultdict(lambda: collections.Counter())
    order = []
    i=0
    for ln in open(p):
        try: d=json.loads(ln)
        except: continue
        k=d.get('kind'); i+=1
        if k=='wa_episode_end':
            ep[d['tag']][d['task_id']][d['rollout']] = int(bool(d.get('reward')))
            ans[d['tag']][d['task_id']][d['rollout']] = d.get('stop_answer','')
        elif k=='wa_judge':
            judges[d['tag']][d['task_id']][d['rollout']] = (d.get('outcome'), d.get('reason',''))
        elif k=='wa_retrieve':
            retr[d['task_id']] = (d.get('titles') or [], d.get('scores') or [])
        elif k in ('wa_write_l1','wa_write_l2'):
            writes.append((i, k, d.get('task'), d['item']['title'], d.get('nc'), d.get('n')))
        elif k=='wa_episode_error':
            errs[d['tag']][d['task_id']]+=1
        elif k=='wa_task':
            order.append((d['tag'], d['task_id']))
    return dict(ep=ep, judges=judges, ans=ans, retr=retr, writes=writes, errs=errs, order=order)

def sr(dd):
    return (sum(dd.values()), len(dd))

def channel(t):
    et = t['eval_types']; ref = t.get('reference') or {}
    if 'string_match' in et:
        if 'fuzzy_match' in ref:
            fm = ref['fuzzy_match']
            if (isinstance(fm,str) and fm.strip()=='N/A') or (isinstance(fm,list) and [x.strip() for x in fm]==['N/A']):
                return 'na'
        if len(et)>1:
            return 'mixed'
        if 'exact_match' in ref or 'must_include' in ref:
            return 'string'
        if 'fuzzy_match' in ref:
            return 'fuzzy'
        return 'string'
    return 'urlprog'
