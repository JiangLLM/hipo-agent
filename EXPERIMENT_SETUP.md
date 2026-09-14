# EXPERIMENT_SETUP.md — hippo-agent 实验设置全记录

本文档记录 hippo-agent 三个 benchmark 实验实际是怎么跑的，供论文附录与复现使用。所有陈述均来自对仓库代码（HEAD f1bebc1，2026-09-13；代码与配置自 71fb3f8 起未变，run 数据提交 463d80f，2026-08-31）、启动脚本、`config/default.yaml`、`runs/` 下 run 产物（`events.jsonl` 的 `run_start` 配置、`summary.json`、`memory.json`）以及 AWS_FLEET.md、HANDOFF.md、WA_FINDINGS.md 等文档的逐条核对。另：仓库含 `hippo-src/`（09-09 加入的 `src/hippo` 逐字节快照，与 src/ 无差异）与 `RETRIEVAL_INJECTION_ABLATIONS.md`（09-13，检索/注入消融史与原始数据）。凡是只能从文档推出、没有代码或产物佐证的地方都标注"文档陈述"或"推断"。文档与代码不一致处集中放在第 15 节。`.env`、`.env.aws` 只读了变量名，没有读值。

## 1. 总览

三个 bench 的实验规模、模型与判分来源如下表。WebArena 是主实验，SWE-bench Verified 是第二个 bench（后来主效应被撤回），Mind2Web 是最早的原型阶段，本机没有任何 run 目录。

| bench | base model（agent / 判官 / 写手） | 题数 | 臂 | 每题 rollout 数 N | 判分来源 | 主要 run 目录 |
|---|---|---|---|---|---|---|
| WebArena（5 站，自托管 8 台 EC2） | gpt-5.6-sol（三者共用一个 LLMClient，经 OpenAI 兼容网关） | 单站 readonly 集 434 题（shopping 139 / map 109 / shopping_admin 109 / gitlab 67 / reddit 10）；单站 all 集 764 题（187 / 109 / 182 / 180 / 106）；legacy string_match 集 230 题 | nomem、withmem（frozenmem 存在于代码中，但 fleet 时代没有跑过） | 两臂均 8（`--agent.n_traj 8 --wa.eval_rollouts 8`） | 官方 WebArena evaluator（经 BrowserGym 在 `env.step` 内逐步调用）；fuzzy_match / ua_match 的 LLM 判官被重定向到网关模型 `WA_GRADER_MODEL`（默认 gpt-4o） | `runs/wa_fleet_<site>_<filter>_<ts>_<ts>/`；正典 run 见第 13 节 |
| SWE-bench Verified（django / sympy / sphinx 子集） | anthropic/claude-haiku-4-5（agent 与判官/写手同一模型） | django 231（229 有 arm64 镜像）；sympy 75；sphinx 44（30 学 + 14 留出，从 run 配置推断） | nomem、withmem、frozenmem（repo bank / global bank） | 写臂 5，评分臂 1 | 本地 swebench 4.1.0 官方 harness（`scripts/eval_local.py`，Epoch arm64 镜像） | `runs/swe_big_django_20260712_190710/`，`runs/abl_*`，`runs/fc_<repo>_<arm>_s<seed>_*` |
| Mind2Web（test_task） | openai/gpt-4o-mini 或 openai/gpt-4o（脚本默认值不一；文档称 gpt-4o-mini） | test_task 252 题 / 69 站（文档陈述） | nomem、withmem（step_evolve 配对）或 nomem、stream | 脚本默认 3，HANDOFF 命令用 5 | 教师强制下 element_acc / action_f1 / step_success（与 gold 精确匹配） | 本机无任何 run 目录（见第 12 节） |

## 2. 硬件与环境

### 2.1 账号、区域与机群规模

所有 WebArena 机器都在 Zillow sandbox AWS 账号 717279734741（"Zillow Sandbox 2025"，角色 Zillow-Sandbox-Developer），区域 us-west-2。机器只有 10.x 私网地址，没有公网 IP，必须先连 Cisco Secure Client VPN。SSO 凭证几小时就过期，任何 `aws` 命令前先 `aws sts get-caller-identity` 确认。

机群共 8 台 EC2，全部 m6i.xlarge（4 vCPU、16 GB 内存），根盘 1000 GiB gp3、3000 IOPS。原始机 10.44.12.29（实例 i-08d438a258bafaaeb，标签 hippo-webarena，2026-07-18 启动，AZ us-west-2a，子网 subnet-04edf09770b28cade，VPC vpc-0ea22b3f56f64f15a，安全组 sg-0006aabf64d95494e，密钥对 hippo-webarena，本地私钥 `~/.ssh/hippo-webarena-sandbox.pem`，登录用户 ubuntu）。它没有 IAM instance profile，所以 SSM 不可用，只能 SSH。七台克隆机 10.44.12.12、.27、.38、.41、.44、.48、.58 于 2026-07-26 从 AMI ami-05add2ab04b84ab85（名 hippo-webarena-clone-20260726）启动。`scripts/wa_fleet.sh:17` 里 WA_FLEET 默认列表的顺序是 `.29 .12 .27 .38 .41 .44 .48 .58`，这个顺序就是 rollout 编号到机器的绑定顺序。

克隆前查过配额：vCPU 上限 1152（需 32），gp3 上限 50 TiB（需 8 TiB），子网空闲地址 32（需 7）。克隆步骤：

```bash
aws ec2 create-image --instance-id i-08d438a258bafaaeb \
  --name hippo-webarena-clone-20260726 --no-reboot      # 1000 GiB 快照约 20 分钟可用
aws ec2 run-instances --image-id ami-05add2ab04b84ab85 --count 7 \
  --instance-type m6i.xlarge --key-name hippo-webarena \
  --subnet-id subnet-04edf09770b28cade --security-group-ids sg-0006aabf64d95494e
```

成本方面，八台 m6i.xlarge 合计约 1.54 USD/h，八块 1000 GiB gp3 约 640 USD/月（约 21 USD/天），全开时约 58 USD/天（AWS_FLEET.md）。

### 2.2 每台机器上的站点部署

四个站点 tar 包来自 http://metis.lti.cs.cmu.edu/webarena-images：shopping_final_0712.tar、shopping_admin_final_0719.tar、postmill_populated_exposed_withimg.tar、gitlab_populated_final_port8023.tar。载入后镜像合计约 424 GB（GitLab 156、shopping 141、forum 107、shopping admin 19.9），968 GB 盘用去约 651 GB。

每台机器跑四个容器，端口固定：

| 站 | 容器名 | docker run |
|---|---|---|
| shopping | shopping | `docker run -d --name shopping -p 7770:80 shopping_final_0712` |
| shopping_admin | shopping_admin | `docker run -d --name shopping_admin -p 7780:80 shopping_admin_final_0719` |
| reddit | forum | `docker run -d --name forum -p 9999:80 postmill-populated-exposed-withimg` |
| gitlab | gitlab | `docker run -d --name gitlab --shm-size=2g -p 8023:8023 gitlab-populated-final-port8023 /opt/gitlab/embedded/bin/runsvdir-start` |

四个容器都不挂 volume、不 bind mount（`docker inspect` mounts=0），所有站点状态都在容器可写层里。因此"`docker rm -f` 再从镜像 `docker run`"同时是克隆初始化和重置的原语。

### 2.3 克隆 / 启动 / 重置脚本

`scripts/wa_clone_bootstrap.sh` 在机器上以 ubuntu 身份运行，用 `hostname -I` 取本机 IP，按 shopping → shopping_admin → forum → gitlab 顺序逐个起容器，每起一个 sleep 30 s（forum 例外，改为对 localhost:9999 curl 轮询最多 30×1 s）。曾经四个一起起导致八台 15 GB 机器上 gitlab 全部 OOM（Exited 137），所以改成串行。

起容器后要把站点里写死的 base URL 改成本机 IP。Magento 两站：等 `bin/magento config:show web/secure/base_url` 有回应（最多 60×10 s），然后 `magento setup:store-config:set --base-url=http://<IP>:<port>`，再直接 MySQL `UPDATE core_config_data SET value='http://<IP>:<port>/' WHERE path='web/secure/base_url'`（用户 magentouser，库 magentodb），最后 `magento cache:flush`。GitLab 改写 `/etc/gitlab/gitlab.rb` 里的 `external_url 'http://<IP>:8023'` 并前台 `gitlab-ctl reconfigure`。Postmill 从 Host 头推链接，不需要改。

最后一步验证：`curl -L --max-time 40` 抓 `http://<IP>:<port>/`，提取正文里所有 http(s) 主机名，任何主机不在白名单 {本机 IP, www.magentocommerce.com, postmill.xyz, ogp.me, schema.org, www.w3.org, gitlab.com, about.gitlab.com, docs.gitlab.com, forum.gitlab.com} 即失败；重定向终点 URL 不含本机 IP 也失败；HTTP 码 000 也失败。这套严格校验来自第一次克隆的教训：七台克隆全部"成功"，却都把 shopping 重定向到 http://metis.lti.cs.cmu.edu:7770/，原因是旧脚本固定 sleep 45 s、输出丢到 /dev/null、检查只匹配 10.x 地址。

`scripts/wa_fleet.sh` 是笔记本侧的机群工具，三个子命令：

```bash
bash scripts/wa_fleet.sh urls                 # 打印逗号分隔的 8 个 http://10.44.12.x，供 --wa.base_urls
bash scripts/wa_fleet.sh check [site]         # 每台探测 7770/7780/9999/8023（或单站），
                                              # 000=DOWN、重定向终点不含本机 IP=FOREIGN，任一台 NOT READY 则 exit 1
bash scripts/wa_fleet.sh reset [site]         # scp bootstrap 到 /tmp/boot.sh，8 台并行 ssh 执行，
                                              # 日志 /tmp/wa_reset_<ip>.log，任一台失败 exit 1
```

ssh 参数 `-o StrictHostKeyChecking=no -o ConnectTimeout=8 -o BatchMode=yes`，密钥来自 WA_KEY（默认 `$HOME/.ssh/hippo-webarena-sandbox.pem`），机器列表来自 WA_FLEET。

实测重置时长：每臂开始前的全站全机群重置 221.1 s（gitlab_all 0815）、224.6 s 与 244.0 s（reddit_all 0814）、229.0 s（shopping_admin_all 0818）；reddit_all 0814 里 190 次逐题 forum 单站重置最短 42.4 s、中位 47.6 s、最长 53.3 s。

### 2.4 rollout 与机器的绑定

设置了 `wa.base_urls` 时，runner 为每个部署建一个 `max_workers=1` 的 `ProcessPoolExecutor`（spawn 上下文），initializer `_worker_init` 把 `cfg.wa.base_url` 覆盖成 `base_urls[i]`；rollout r 永远提交到 `pools[r]`，绑定是结构性的（按进程），不是共享计数器。`set_site_env()` 在 worker 内用赋值（不是 setdefault）写 WA_SHOPPING=`<base>:7770`、WA_SHOPPING_ADMIN=`<base>:7780/admin`、WA_REDDIT=`<base>:9999`、WA_GITLAB=`<base>:8023`、WA_WIKIPEDIA=`<base>:8888/...`、WA_MAP=`<base>:3000`、WA_HOMEPAGE=`<base>:4399` 及不带前缀的同名变量；`assert_site_env()` 若发现 SHOPPING/SHOPPING_ADMIN/REDDIT/GITLAB 不以本 worker 的 base_url 开头就抛 "deployment mismatch"。早先用 setdefault 时八个 rollout 曾静默共用一台机器。

从 step 日志核过：shopping_admin_all 0818 的 25,898 条 `wa_step` URL 里，rollout 0..7 分别只落在 .29、.12、.27、.38、.41、.44、.48、.58；reddit_all 0814 同样每个 rollout 只有一个 10.44.12.x 主机（另有少量通过页面链接点出去的外部主机，见第 16 节）。所有 fleet 日志中 "rollout isolation ON: 8 deployments [...]" 在 nomem 出现 19 次、withmem 15 次。

`wa.worker_recycle` 默认 10，在逐部署池上变为 `max(1, 10 // n_traj) = 1`，即每台机器的 worker 进程每跑完一个 rollout 就换新。

没有 base_urls 时走单个 n_traj worker 的共享池、一个部署，只允许纯只读任务：`stream_arm` 在 n_traj>1 且任务集含 mutating 且 `len(base_urls) < n_traj` 时抛 ValueError；base_urls 非空但短于 n_traj 也抛。

### 2.5 单机 map 模式

map 不在 8 台机群上，而是另一台独立机器。`scripts/wa_map_deploy.sh` 把官方 WebArena AMI ami-08a862bf98e3bd7aa 从 us-east-2 复制到 us-west-2（名 webarena-map-frontend，1 TB 约 1 小时），启一台 t3a.xlarge、1000 GB gp3、密钥 hippo-webarena、同一子网，user-data 写入 `MAP_BACKEND_IP=18.208.187.221`，Name 标签 webarena-map-frontend。前端是 openstreetmap-website 端口 3000；瓦片服务器（:8080）和 OSRM（:5000）仍指向官方还活着的 18.208.187.221（2026-08-11 探测过）。两次 map run 都用 base_url http://10.44.12.7，base_urls 为空，8 个 worker 进程共用这一台（日志 "parallel rollouts ON: 8 worker processes, ONE deployment"）。第一次（0812）用默认 timeout 10000 且无 stagger，109 题里 22 题所有 episode 全死；第二次（0813）加了 `--wa.timeout 60000 --wa.rollout_stagger 4`。map 机器的实例 ID、AMI 复制后的 ID、启动日期均未记录在任何 .md 中。

### 2.6 runner 所在机器与软件版本

`hippo.wa.run` 本身在研究者的 macOS 笔记本上跑（`caffeinate -i .venv-wa/bin/python ...`，日志里的路径 `/Users/yutongs/Projects/hipo-agent/.venv-wa/lib/python3.11`），通过 VPN 访问 EC2；EC2 上只有站点容器。HANDOFF 称机器是 Apple M4 Max（文档陈述，也是 SWE 选 arm64 镜像的原因）。

| venv | Python | 关键包 |
|---|---|---|
| `.venv-wa`（WebArena） | 3.11.15 | browsergym-core 0.14.3、browsergym-webarena 0.14.3、libwebarena 0.0.4、playwright 1.44.0（Chromium 125.0.6422.26，headless）、gymnasium 1.3.0、litellm 1.92.0、openai 2.46.0、fastembed 0.8.0、tenacity 9.1.4 |
| `.venv`（SWE / 通用） | 3.13.14 | mini-swe-agent 2.4.5、swebench 4.1.0、sb-cli 0.1.4、datasets 5.0.0、litellm 1.90.0、openai 2.44.0、fastembed 0.8.0、docker 7.2.0、numpy 2.5.0 |

`pyproject.toml` 不声明 browsergym/playwright/webarena；WA 浏览器栈只存在于 `.venv-wa`，在 `run_episode` 里懒加载。

## 3. 模型与网关

| 角色 | WebArena | SWE-bench | Mind2Web |
|---|---|---|---|
| agent 模型 | gpt-5.6-sol（脚本默认 MODEL；所有 fleet run 的 run_start 一致） | anthropic/claude-haiku-4-5（`--swe.agent_model`，经 mini-swe-agent 的 litellm） | openai/gpt-4o-mini 或 gpt-4o（脚本默认） |
| 判官 / L1 / L2 / 注入门控 | 与 agent 同一个 LLMClient（`WaBrain(llm)`），即 gpt-5.6-sol | 与 agent 同模型 claude-haiku-4-5（`cfg.llm.model`，`cfg.judge.model` 从未被读） | 与 agent 同模型（`LLMBrain` 的 `judge_llm = judge_llm or llm`） |
| 官方 grader 的 LLM（仅 WA fuzzy_match / ua_match） | `WA_GRADER_MODEL` 环境变量，代码默认 gpt-4o，经同一网关；实际是否覆盖未记录 | 不适用（本地 swebench harness） | 不适用 |
| 嵌入模型 | local/BAAI/bge-small-en-v1.5（fastembed ONNX，本地，384 维） | 同 | config 默认 openai/text-embedding-3-small |
| temperature | agent 0.7（`cfg.llm.temperature`）；judge / L1 / L2 / select_lesson 0.0 | 判官/写手 0.0；agent 未设 temperature（provider 默认） | 学习期 0.7+0.0001·r，测试期 0.0 |
| max_tokens | WA client `wa.max_tokens`=8000（yaml；代码回退 4000）；L1/L2 写手调用覆盖为 16000；grader 调用 `max_completion_tokens=max(64, max_tokens or 256)` | 判官 `swe.judge_max_tokens`=8000 | `llm.max_tokens` 1024 |
| cache | `.cache/chat` 只缓存 temperature==0.0 的调用（key 为 payload sha256），agent 步从不缓存；`.cache/embed` 缓存全部嵌入（本机 53886 条 chat、10456 条 embed） | 同 | 同 |
| 预算 | `--run.budget_usd 1000000`（等于不限） | 按 run 设（180 / 40 / 35 / 20 等），`BudgetExceeded` 硬停 | 8–30 |

网关：`src/hippo/llm.py` 在环境变量 `LLM_API_BASE` 与 `LLM_API_KEY` 同时存在时把所有 chat/embedding 经 litellm 打到一个 OpenAI 兼容网关（HANDOFF 称 ZGAI gateway），模型 id 加 `openai/` 前缀，`drop_params=True`；`run()` 与每个 worker 还全局设 `litellm.drop_params = True`。`LLM_FALLBACK_MODELS` 是逗号分隔的备选模型列表。每次 tenacity 尝试内部先调主模型、失败后立刻依次尝试各备选模型；全部失败才算该次尝试失败，由 tenacity 重试整个循环（最多 8 次尝试，指数退避 2–60 s；`BudgetExceeded` 与 `ContextWindowExceededError` 不重试）。嵌入重试 5 次、1–30 s。单次请求超时来自 `LLM_TIMEOUT`，代码默认 120 s，所有 WA 启动脚本 `export LLM_TIMEOUT=180`。费用用 `litellm.completion_cost` 逐次累加到 `spent_usd`，出错记 0。

关于 temperature 是否真的发出去：WA_FINDINGS.md:132 说网关下 `drop_params` 会剥掉 temperature，所以 0.0 是"假的"。但在 `.venv-wa` 里直接调用 litellm 1.92.0 的 `OpenAIGPT5Config.map_openai_params(model='gpt-5.6-sol', temperature=0.7, drop_params=True)` 返回 `{'max_completion_tokens': 8000, 'temperature': 0.7}`，即客户端确实把 temperature 发给了网关，只是把 `max_tokens` 翻译成 `max_completion_tokens`。网关/模型是否遵守 temperature 无法从仓库验证。gpt-5.6-sol 背后的底层模型、reasoning effort、上下文窗口在仓库里没有任何记录。

关于凭证过期：仓库里没有 LLM 网关 token 刷新逻辑，只有上述重试与 fallback；唯一的过期处理是 AWS SSO 凭证（几小时过期，跑 `aws` 命令前 `aws sts get-caller-identity`）。`.env` 里出现的变量名有 OPENAI_API_KEY、ANTHROPIC_API_KEY、SWEBENCH_API_KEY、LLM_API_BASE、LLM_API_KEY、LLM_FALLBACK_MODELS；`.env.example` 只有 OPENAI_API_KEY 与 HIPPO_MIN_INTERVAL=0 两个生效变量（GEMINI_API_KEY、ANTHROPIC_API_KEY 以注释形式列出）。

SWE 阶段的流量是直连 Anthropic 还是经网关，从产物无法判断；HANDOFF.md:130 说 SWE 约 500 USD 花在 Anthropic key 上，网关是 WebArena 阶段引入的，且 mini-swe-agent 的 model 配置没有收到 api_base（`rollout.py:90`），按原样跑的话 agent 路径是直连。

## 4. WebArena：agent 脚手架

环境用 `gym.make(f"browsergym/webarena.{task_id}", action_mapping=action_set.to_python_code, timeout=wa.timeout, disable_env_checker=True)` 每个 episode 新建，然后 `env.reset()`。视口 1280×720、slow_mo 1000 ms、Playwright 默认超时 10000 ms（`wa.timeout` 默认 10000，map 60000）。所有 812 题注册时只传 `task_id`，因此 `with_na_hint=False`、`with_homepage_hint=False`：agent 看到的 goal 是原始 intent，没有 N/A 提示也没有 homepage 说明。`env.reset` 内部用 WebArena 硬编码的 ACCOUNTS 对任务涉及的每个站 `ui_login`，设地理位置，跳到 `start_url`（以 ` |AND| ` 拆多页）。

观测是纯文本：完整可访问性树 `flatten_axtree_to_str(obs["axtree_object"], extra_properties=obs["extra_element_properties"], filter_visible_only=False)`，从不截断，无截图；首次调用抛异常则回退到不带 extra_properties 的版本。默认 `with_visible=False, with_clickable=False, skip_generic=True, remove_redundant_static_text=True`。元素用 browsergym 的 bid 标识。

动作空间是 `HighLevelActionSet(subsets=["webarena"], multiaction=False, strict=False)`，15 个动作：noop、scroll、keyboard_press、click、fill、hover、tab_focus、new_tab、go_back、go_forward、goto、tab_close、select_option、send_msg_to_user、report_infeasible。给 agent 的描述以 "15 different types of actions are available." 开头、以 "Only a single action can be provided at once." 结尾。

每步一次全新的两消息 chat（system + user），无对话状态、无 tool calling：`llm.chat([{system: build_sys(action_set)}, {user: usr}], temperature=cfg.llm.temperature)`。user 消息精确为：

```
{mem_block}TASK: {goal}

HISTORY:
{_history(steps)}

CURRENT PAGE (accessibility tree):
{_obs_text(obs)}
```

`mem_block` 只在 memory_text 非空时存在，原文是：

```
Optional hints from past tasks on this site — use one ONLY if it clearly fits the current task, and prefer the cheapest sufficient evidence. Do not add steps or chase a procedure a hint describes if you can already answer directly and correctly:
{memory_text}

```

所以 nomem 的 prompt 与"检索为空的 withmem" 字节相同。HISTORY 取最近 15 步，每步 `"{i}. thought: {thought[:200]}\n   action: {action}"`，环境报 `last_action_error` 时追加 `"\n   -> ERROR: {err}"`，第 0 步是 "(none yet)"。system prompt 以 "You are an autonomous web navigation agent. Each turn you see the accessibility tree of the current page and the history of what you already did." 开头，接 `action_set.describe(with_long_description=False, with_examples=True)`，然后是验证/完整性规则、答案格式规则（`send_msg_to_user` 里只放答案值）、"Element ids (bids) MUST be quoted"、留在本服务器的规则，以及输出格式 `Thought: <...>\nAction: <exactly one action call>`。

解析：Thought 用正则 `Thought:(.*?)(\n Action:|end)`；Action 取 `Action:` 之后（或最后一行非空文本）。不匹配 `^[a-zA-Z_]\w*\s*\(` 的输出，剥掉 Thought/Action/Answer/Final Answer 前缀与引号后被强制包成 `send_msg_to_user("<text>")`。`env.step` 不会因坏动作抛异常，browsergym 把异常放进 `obs["last_action_error"]`，脚手架逐步记录并喂回 HISTORY。

主机守卫 `_guard_host`：`goto()` 的目标 netloc 不属于已配置站点来源（SHOPPING/SHOPPING_ADMIN/REDDIT/GITLAB/MAP/WIKIPEDIA/HOMEPAGE 环境变量）时改写回本 episode 配置的站点（回退到当前页来源）；同机其它端口放行；每次改写记 `wa_host_guard` 事件。各 fleet run 的改写次数从 0（7 个 run：gitlab_all 0814、reddit_all 0809/0810×2/0811、shopping_admin readonly 0808 与两次 0809）到 70（map 0813）、49–58（shopping 四个 run）、52（reddit_all 0814）、41（map 0812）。守卫只拦 goto，不拦点链接。

步数上限 `wa.max_steps`=30（yaml；代码回退 20；所有脚本传 `--wa.max_steps 30`）。`agent.max_steps`（15）不被 WA 路径使用。终止条件：browsergym 返回 terminated（WebArena `validate()` 在 score>0 或最后一条 chat 是 assistant 消息即 STOP 时 done；`report_infeasible` 通过 `terminate_on_infeasible=True` 终止；任意 tab 出现未授权 URL 返回 (0, True)），否则到步数上限或步超时。`stop_answer` 是 reset 预置消息之后最后一条 assistant chat。agent 从不收到参考答案，goal 只是 `config['intent']`。

每个进程（父进程与每个 worker）都打 `_patch_browsergym_infra`：browsergym 的 `EXTRACT_OBS_MAX_TRIES` 从 5 降到 2；click/dblclick/fill/clear/check/uncheck/select_option/hover/press/focus/type 里写死的 500 ms Locator 超时提到 3000 ms。`pre_observation_delay` 保持 0.5 s 默认。

## 5. WebArena：学习循环

每题两臂各 8 个 rollout：写臂 withmem 用 `agent.n_traj`，评分臂 nomem/frozenmem 用 `wa.eval_rollouts`，fleet 脚本把两者都设成 NTRAJ=8。任务按 task_id 排序作为流顺序，withmem 严格串行，第 i+1 题能看到第 i 题写入的经验；bank 从空开始（除非 `--wa.memory_in`），结束时存到 `<rundir>/memory.json`。runner 启动时强制 `memory.mode=reasoning_only`、`scope_reasoning=True`，FactStore 从未用过（所有 summary 的 n_fact=0）。

判官 `WaBrain.judge_trajectory` 看到 TASK intent、REFERENCE ANSWER（`eval.reference_answers` 的 json，缺则 "(not provided)"）、OFFICIAL GRADER VERDICT CORRECT/INCORRECT（来自 reward）、AGENT FINAL ANSWER（stop_answer）和 TRACE（`compact_trace`：每步完整 thought/action/error/url 与完整页面树，仅受 obs_budget=200000 字符、最新步优先约束，超出的旧页面替换为 "[omitted — trace too long for the judge]"）。输出 JSON `{outcome, reason}`，三分类 failure / genuine / fluke。硬夹：reward=0 一律 failure；reward=1 默认 genuine，模型说 fluke 才 fluke；空 trace 直接短路不调 LLM。判官从不改分，只提供学习信号。

L1（`reflect_trajectory`）只对 judge outcome=='failure' 且无 error 的 rollout 写，genuine 与 fluke 跳过；每 rollout 最多 1 条（max_items=1），无每题上限（一题最多 n_traj 条 L1）。写手不看参考答案，但收到 SITE、TASK、TRACE 和判官的 reason 字串（"FAILED: <reason>"）；system prompt 禁止从单条轨迹推出一刀切禁令。item 打 scope=`site:<site>`、outcome=failure、layer=L1。

L2 闸门原文（`src/hippo/wa/run.py:490-507`）：

```python
keep = [i for i, v in enumerate(verdicts) if v["outcome"] != "fluke"]
ok_l2 = [verdicts[i]["outcome"] == "genuine" for i in keep]
ncg = sum(ok_l2)
nkeep = len(keep)
if layer2 and nkeep > 1 and ncg < nkeep:
    ... contrast_rollouts(...)
```

即 fluke 从分子分母同时剔除；至少剩 2 个非 fluke rollout 且它们不全是 genuine 成功时触发（全错也触发）。注意：崩溃（error 非空）的 rollout 只从计分分母 n 中剔除，并不从 L2 对比中剔除——判官把它们标成 failure（多为 "empty trace"），它们留在 keep 里按 WRONG 计入 nkeep，并以 "(no usable trajectory)" 行进入 L2 输入。因此即使计分 rollout 全对，只要有崩溃也会触发 L2（gitlab_all 0815 t357 计分 6/6 却按 6/8 写出 "多数对" 告诫，共 7 题；shopping_admin_all 0818 t470 计分 4/4 却按 4/8 写出 "一半" 经验，共 13 题）。`wa_write_l2` 事件里的 nc/n 是 ncg/nkeep（含崩溃 rollout，与 wa_task 的 nc/n 不同），n_fluke = n − nkeep 在有崩溃时为负；`attribute_source_bucket.py` 的来源分档用的正是这组 nc/n。`wa.vote_margin` 被读取（run.py:244）但从未使用。

`contrast_rollouts` 按 nc（保留 rollout 中的 genuine 成功数）与 n（保留数）分四档：

| 条件 | 方向 | learn_from_success | 写出 item 的 outcome 标签 |
|---|---|---|---|
| nc == 0 | "ALL rollouts FAILED" | False | failure |
| nc·2 == n | "Half succeeded, half failed" | True | success |
| nc·2 > n | "Most rollouts SUCCEEDED; a few failed"（谨慎，不得收窄答案） | False | failure |
| 0 < nc, nc·2 < n | "Most rollouts FAILED; a few succeeded"（解释为何，先给便宜默认，条件性验证） | True | success |

L2 每题最多 1 条（max_items=1），layer=L2，scope=`site:<site>`。L2 输入列 SITE、TASK、"<n> rollouts, <nc> succeeded:"，然后每个 rollout `[OK|WRONG] (<judge reason>)` 加它的 L1（title: content）；learn_from_success 时 genuine 成功给完整 TRACE，否则 "(genuine success)" / "(no usable trajectory)"。不传参考答案，但传判官 reason。

写手调用参数 `_WRITE_KW = {drop_params: True, max_tokens: 16000}`，判官与 select_lesson 用 `_JSON_KW = {drop_params: True}` 继承 client 的 8000；四者都 temperature=0.0。

去重键是 `(item.scope, _norm(item.title))`，`_norm = ' '.join(title.lower().split())`；`seen` 集在臂开始时从 bank 播种，L1、L2 共用；重复静默丢弃，存储纯追加，无合并无删除。嵌入文本是 `f"{title}. {description}"`（content 不参与），bge-small 384 维；load 时维度不匹配的 item 会重嵌。

全集 fleet run 最终 withmem bank 规模：shopping 659（560 L1 + 99 L2；outcome 635 failure / 24 success）、gitlab 375（314 + 61）、shopping_admin 533（454 + 79）、reddit 184（142 + 42）、map 371（303 + 68）。

## 6. WebArena：检索与注入

检索 query 是任务 intent。`ReasoningStore.topk` 先按 scope=`site:<site>`、layer=L2（`wa.inject_only_l2` 默认 on）过滤，再做 cosine top-k；`memory.relevance_threshold`=0.0 即关闭。`wa.inject_gate`=llm（yaml 默认、所有 fleet run 一致）：先取 `wa.retrieve_fetch_k`=5 个候选，`WaBrain.select_lesson` 给 LLM 看一份 `[i] title: content` 菜单，让它返回一个 0 基下标或 -1（不注入）；只注入被选中的那一条。`inject_gate` 不是 llm 时才用 `memory.retrieve_k_reasoning`=1 的普通 top-k。两种路径下每题至多注入一条。shopping 全集 run 里 withmem 的 `wa_retrieve` 触发 187 次，134 题注入 1 条、53 题 0 条（门控返回 -1 或池空）。

渲染 `Memory.render()`：每条 `[strategy] {title}: {content} (applies when: {description})`，一行一条，按整条截到 `memory.token_budget*4` 字符（4000×4=16000）。渲染文本包进第 4 节的 "Optional hints..." 前缀，放在 `TASK:` 之前。

## 7. WebArena：评测协议与口径

### 7.1 三种臂与冻结库

nomem：retrieve=False、write=False。frozenmem：retrieve=True、write=False，必须 `--wa.memory_in <memory.json>`，否则 ValueError。withmem：retrieve=True、write=True，可选 `--wa.memory_in` 预载。无论 `wa.arms` 写什么顺序，执行顺序固定 nomem → frozenmem → withmem。frozenmem 的配对协议是 `scripts/run_wa_replicate.sh`（nomem vs frozenmem，`--wa.eval_rollouts $ROLLOUTS` 默认 5，readonly_only 集）；有 summary 的 WA frozenmem run 只找到 `runs/wa_sa_ablation_20260718_205705`，8 机群时代没有跑过 frozenmem。

### 7.2 题集筛选与各站题数

任务来自安装包内置的 `webarena/test.raw.json`（812 题，190 个不同 `intent_template_id`，`require_reset` 全 False），每种模式只保留 `sites == [site]` 的单站题，48 道多站题在任何模式下都被排除。`wa.task_filter` 三个值：

| filter | 定义 | shopping | shopping_admin | gitlab | reddit | map |
|---|---|---|---|---|---|---|
| string_match（legacy） | 单站且 `eval_types == ['string_match']` | 88 | 88 | 43 | 11 | 89 |
| readonly | 单站且冻结清单 `mutating=false` | 139 | 109 | 67 | 10 | 109 |
| all | 全部单站题 | 187 | 182 | 180 | 106 | 109 |

legacy 230 题集（四站）放进了 12 道其实会改状态的题：gitlab 783/789、reddit 723、shopping 792–798、shopping_admin 491/790。空 `task_filter` 回退到旧 `readonly_only`（true → string_match，false → all）。

冻结清单 `config/wa_task_class.json`：n_tasks 812、n_mutating 359、n_readonly 453（含 19 道多站只读）、分类模型 gpt-5.6-sol、36 处启发式/LLM 分歧。`scripts/classify_wa_tasks.py` 的规则是启发式（任何 program_html 检查的 url 不以 'last' 开头；任何 locator 以 'func:' 开头；intent 以 VERBS 正则中的动词开头）或 LLM（gpt-5.6-sol，temperature 0）任一判 mutating 即 mutating，再对 `is_unsaved_form`（所有 program_html 都查 'last…' 且 locator 匹配 .value|.selectedIndex|.checked）豁免。`load_manifest` 要求清单恰好覆盖 812 题，否则 ValueError；清单在所有模式下都加载，因为 mutating 标志同时驱动共享部署守卫。

按参考答案通道分（string=有 exact_match/must_include 键；fuzzy N/A；fuzzy 其它；仅 url_match/program_html）：shopping 54/19/15/99，shopping_admin 62/6/20/94，gitlab 45/3/5/127，reddit 9/2/0/95，map 46/5/38/20。

### 7.3 每题记账与崩溃剔分母

每题：`reward = rollouts[0]['reward']`（官方 0/1，仅第一个 rollout）；`ok = [bool(x['reward']) for x in rollouts]`（全部 N 个 rollout）；`nc = sum(ok)`；`n_err` = error 非空的 rollout 数；`n = len(rollouts) - n_err`。n<=0 记 `wa_task_all_failed`，该题在该臂不产生行；n_err>0 记 `wa_rollouts_dropped {n_err, n_scored}`。error 只在 `run_episode` 抛异常时设置（浏览器 make/reset/step 异常，如 Target crashed、goto 超时），记 `wa_episode_error`；步超时（`_StepTimeout`）中断循环但 error=''，该 rollout 照常计分（通常 0）。超过 `rollout_timeout` 的挂起 rollout 没有结果、从 packed 中消失（n 缩小）；BrokenProcessPool 换新 worker 重试一次，同一部署两次失败则丢弃。`one_task` 内其它异常记 `task_error` 并跳过该题（臂继续）；BudgetExceeded 停 run 并写 `summary.halted`。

这个 `n = len - n_err` 分母是 92e1afb（2026-08-10）引入的。之前的 run（如 shopping_admin_readonly 0807）每题 n=8、崩溃 rollout 记 0：nomem 少了 32 个 `wa_episode_end`，withmem 少 4 个，代码注释说这一项就把配对差值往记忆有利方向推了 3.2 个点。

### 7.4 配对规则

分析脚本按 task_id 配对，只取两臂 `wa_task` 事件都有的题（因 all_failed / task_error / halt 缺失的题掉出配对）；`analyze_ab_mean.py` 额外排除 BAD={783}；`attribute_source_bucket.py` 丢 n==0。每题差值 = withmem nc/n − nomem nc/n，报告的是逐题差值的均值（macro）。

### 7.5 口径的精确定义

| 口径 | 定义 | 验证例（shopping_all 0811，187 题） |
|---|---|---|
| 均值（主口径） | 每题 nc/n 在配对题上的平均（`analyze_ab_mean.py` 称 "the number to trust"）；WA_SHOPPING_ALL 用 pooled sum(nc)/sum(n)，同一 run 上与 macro 三位小数一致 | 836/1495=55.9% → 862/1492=57.8%；macro 0.5591/0.5775 |
| 多数投票 | 题对当且仅当 nc·2 > n（严格多数，4/8 平票算错） | 102/187=54.5% → 105/187=56.1%（>= 变体给 106/108，不匹配文档） |
| 对 1 题即算对 / pass@8 | nc >= 1 | 127/187=67.9% → 131/187=70.1% |
| 8/8 全对 | nc == n（全部计分 rollout 都对，不是字面 nc==8；gitlab_all 用 nc==n 得 0.628/0.667 匹配文档，nc==8 得 0.611/0.639 不匹配） | 82/187=43.9% → 84/187=44.9% |
| 混合口径 | nomem 的均值（或全对率）对 withmem 的 pass@8 | 0.559 vs 0.701；WA_SCORES.md "基线单跑 vs 方法" 整张表是这个口径 |
| rollout[0] pass@1 | `summary.json reward_sr`、`metrics_<arm>.csv reward`、`rewards_<arm>.json`、cum_sr/win10_sr 曲线都只用第一个 rollout；没有任何文档表报这个数 | 0.5722 → 0.6043 |
| 主指标子集 | 只算参考答案含 exact_match 或 must_include 且无 fuzzy_match 键的题；fuzzy 单独报为噪声，N/A 参考题应剔出 headline（`analyze_wa.py`、WA_FINDINGS.md:7,13、WA_DESIGN.md:31） | — |
| 真改善 / 真回退 | withmem nc − nomem nc >= 3（of 8）/ 反向；严格回退 = nomem >= 6/8 且 withmem <= 2/8；大涨/大跌 = 逐题 rate 差 >= +0.5 / <= −0.5；变好/变坏/不动 = 差 >0 / <0 / ==0 | — |
| 能力口径（仅 shopping_admin readonly 0809） | 手工审计：withmem 只在 14 题被判为真实能力缺口算错（去掉 11 个 grader 格式假阴性、9 个 'None' 参考的判官题、4 个过度完整答案）→ 95/109=0.872；nomem 用 pass@8 0 of 8 的 23 题算错 → 86/109=0.789；同 run 原始均值 0.673 vs 0.672 | — |

多数投票、pass@8、8/8、混合四个口径在仓库里没有任何提交的脚本计算，上述定义是通过从 `wa_task` 事件复现文档数字反推的（只有 `_tmp_*.py`、`_verif_bucket.py` 等临时脚本）。WA_FINDINGS 里的 p 值/CI 来自 `_tmp_stats.py`：逐题差值 bootstrap（B=40000，numpy seed 7，双侧 p=2·min(P(mean<=0),P(mean>=0))）和 rollout 级题内置换检验（B=20000）。WA_FINDINGS 的账目表按 `wa_episode_end` 事件算（rate = 有 reward 的 episode_end 数 / episode_end 数），与按 `wa_task` 算的会略有差异（08-03 shopping 一个是 77 题 0.542/0.607，一个是 74 题 0.564/0.628）。

### 7.6 summary.json / metrics 字段

`metrics_<arm>.csv` 列：idx, task_id, template_id, reward（rollout[0]）, judge（rollout[0] 判 genuine 则 1）, nc, n, steps（rollout[0] 步数）。`rewards_<arm>.json` = {task_id: rollout[0] reward}。`summary.json` = {n_tasks, site, arms, <arm>: {n, reward_sr, layer1_writes, layer2_writes}, 可选 halted, learned_memory: {n_reasoning, n_fact}, spent_usd}。

## 8. WebArena：判分补丁

官方 reward 通过 browsergym 获得：`env.step` 每步调 `task.validate()`，它构造假轨迹：最后一条 chat 是 assistant 消息时以其内容为 STOP 答案；最后一条是 `report_infeasible` 产生的 infeasible 消息时以字面 'N/A' 为 STOP 答案（可直接通过 exact_match('N/A')，不经 LLM）；agent 没说话时用占位字串 'whatever'（action_type NONE）。注意脚手架的 `stop_answer` 只读 assistant 消息，`report_infeasible` 结束的 episode 记为 stop_answer=''，因此"N/A 参考题上最终答案为空却判对"的计数里混有这类合法的 N/A 命中。调 `webarena evaluator_router(config_file)(trajectory, config_file, page, client=None)`，返回 (score, done=score>0 或 STOP)；`llm_fuzzy_match` 的 AssertionError 转为 0.0。脚手架取最后一步 reward 的 `int(reward or 0)`，没有独立评测 harness。

上游 `StringEvaluator.clean_answer` 去空白、去一对外层引号、小写；exact_match 是清洗后相等；must_include 是清洗后 ref 为 pred 子串（ref 列表只有一个单字符元素时才按词切）；fuzzy_match 逐参考元素调 `llm_fuzzy_match`；fuzzy_match=='N/A' 先 exact_match('N/A')，再 `ua_match(intent, ref=eval.string_note, pred)`。多个 reference_answers 键和多个 evaluator 之间的分数相乘（EvaluatorComb），没有部分分。上游 `llm_fuzzy_match`/`llm_ua_match` 写死模型 gpt-4-1106-preview、temperature 0、max_tokens 768；fuzzy 输出含 'partially correct' 或 'incorrect' 记 0 否则断言 'correct'；ua 含 'different' 记 0 否则断言 'same'。`URLEvaluator` 规则是 GOLD in PRED：某个参考 base path 是页面 base path 子串，且参考里每个 query 键至少有一个参考值出现在页面 URL query 中；参考按 ' |OR| ' 拆。

`_fix_webarena_grader()`（父进程与每个 worker 都打，因为 reward 在 worker 的 `env.step` 里算）只在 `LLM_API_BASE` 与 `LLM_API_KEY` 都存在时生效，做三件事：

一是 fuzzy grader 转网关：导出 OPENAI_BASE_URL/OPENAI_API_KEY，把 `helper_functions.generate_from_openai_chat_completion` 替换为 litellm 调用 `'openai/' + WA_GRADER_MODEL`（默认 gpt-4o），`max_completion_tokens=max(64, int(max_tokens or 256))`（上游传 768 就是 768），`drop_params=True`，temperature 被丢弃。

二是 N/A 确定性规则：包一层 `llm_ua_match`（同时打在 `helper_functions` 与 `evaluators` 两处），pred 去空白后为空或等于 'whatever' → 0.0；匹配正则（大小写不敏感）

```
^(n/?a|none|no|nothing|not found|no result(s)?|no such .{0,60}|(there (is|are) )?no .{0,60}|does not exist|not (available|achievable|possible)[.!]?)$
```

→ 1.0；其它走原 LLM。只在 fuzzy_match=='N/A' 且 exact_match('N/A') 失败后才到这里。

三是 host 归一化：包 `StringEvaluator.clean_answer`，上游清洗后把 'metis.lti.cs.cmu.edu' 换成 GITLAB（回退 SHOPPING）环境变量的 hostname，把 'www.reddit.com' 换成 REDDIT 的完整 netloc（如 10.44.12.x:9999）。上游对 ref 和 pred 都调 clean_answer，所以归一化是对称的。web.cmoa.org（map t256）刻意不归一化。

版本史要注意：metis 归一化从 b08f899（2026-07-20）就有；N/A 规则与 www.reddit.com 替换首次提交于 4ef2376（2026-08-31），晚于所有全集 run（08-11 至 08-18）。从事件核过这些 run 里 N/A 规则确实没生效：shopping_all 0811 在 N/A 参考题上有 213 个 rollout 判对，其中 176 个最终答案为空；gitlab_all 0815 42 对/40 空；shopping_admin_all 0818 26 对/12 空。每个 run 用的 grader 补丁版本没有记录在产物里（run_start 配置不含 grader 状态）。

## 9. WebArena：超时与看门狗

| 参数 | 值 | 作用层 | 到期行为 |
|---|---|---|---|
| `wa.timeout` | 10000 ms（map 60000） | Playwright 单动作 | 动作报错进 last_action_error |
| `wa.step_timeout` | 90 s | worker 内 SIGALRM 包 `env.step` | 记 'step exceeded 90s'，episode 结束，仍计分 |
| `wa.reset_timeout` | 120 s | 分别包 `gym.make` 与 `env.reset` | 抛异常 → error，rollout 剔出分母 |
| `env.close` | 60 s | worker | — |
| `wa.episode_timeout` | 900 s | worker 内 daemon `threading.Timer` | faulthandler dump 全部栈到 stderr，`os._exit(70)`；父进程收到 BrokenProcessPool 后在新 worker 重试一次 |
| `wa.rollout_timeout` | 1800 s | 父进程，每题全部 N 个 future 共享的墙钟 | FutureTimeout → `_kill_pool` 杀池重建，该 rollout 丢弃，不重试；共享池模式下整批重试一次，第二次失败抛 RuntimeError；所有部署都失败则 'every deployment failed' |
| stall reporter | 每 300 s 检查，>1800 s 无题完成 | 父进程 daemon 线程 | dump 全部线程栈到 stderr 并重置计时（每个停滞区间一次），从不 kill |
| SIGUSR1 | 按需 | 父进程 | `kill -USR1 <pid>` dump 全部线程栈 |
| `LLM_TIMEOUT` | 180 s（脚本导出；代码默认 120） | litellm 请求 | tenacity 重试 8 次 |
| fleet reset 子进程 | 45 min | `reset_site()` 的 subprocess | reset_timeout 事件，required=True 时致命 |
| `wa.rollout_stagger` | 0（map 4） | worker | rollout r 在 `gym.make` 前 sleep r·stagger 秒 |

`_kill_pool` 的做法是向池的 `_result_queue` 为每个待处理 work item 伪造一个 BrokenProcessPool `_ResultItem`，对 `pool._processes` 里每个进程 SIGKILL，join `_executor_manager_thread`（30 s，仍活则告警），最后 `shutdown(wait=False, cancel_futures=True)`。

`reset_per_task`（默认 off，reddit 加 `--wa.reset_per_task on`）：runner 维持一个悲观的 dirty 标志，前一题是 mutating 时在当前 mutating 题前只重置本站容器；第一道 mutating 题跳过，因为臂开始的重置已覆盖。`fleet_reset` 默认 off，fleet 脚本在 FILTER=all 时置 on；`reset_site(required=True)` 在 fleet_reset 为 off 而任务集含 mutating 题时直接抛错，所以 mutating run 不可能带脏状态开跑。`reset_site()` 跑 `bash scripts/wa_fleet.sh reset [container]`（site=None 全站，reddit 映射到容器 'forum'），记 reset_done/reset_failed/reset_timeout/reset_skipped 事件；旧的 `wa.reset_url`/WA_FULL_RESET 端点从未部署过。

`WA_PARALLEL=0` 强制顺序进程内 rollout（调试用）。

## 10. 一次完整 run 的操作流程

以下是 FILTER=all 的 fleet run 从起机群到拿到 summary 的顺序。前提：VPN 已连，`.env` 里有 LLM_API_BASE/LLM_API_KEY，`.venv-wa` 已建。

```bash
# 0. AWS 凭证（SSO 几小时过期）；如机器停着先 start-instances（AWS_FLEET.md 只建议闲时停克隆机）
aws sts get-caller-identity

# 1. 能 ssh 到每台机器
ssh -i ~/.ssh/hippo-webarena-sandbox.pem ubuntu@10.44.12.29

# 2. 机群健康检查（四站 × 8 台，跟随重定向，FOREIGN/DOWN 均失败）
bash scripts/wa_fleet.sh check            # 或 check shopping_admin
bash scripts/wa_fleet.sh urls             # 应打印 8 个 http://10.44.12.x

# 3. 如站点状态脏了先重置（readonly run 可跳过；all run 由 runner 在每臂开始前自动重置）
bash scripts/wa_fleet.sh reset            # 或 reset gitlab；每台日志 /tmp/wa_reset_<ip>.log

# 4. 启动（脚本会拒绝：已有 hippo.wa.run 在跑且未 FORCE=1；机器数 < NTRAJ；check 不过；site=wikipedia）
FILTER=all NTRAJ=8 ARMS=nomem,withmem MODEL=gpt-5.6-sol bash scripts/run_wa_fleet.sh gitlab
#   readonly 集：bash scripts/run_wa_fleet.sh shopping
#   reddit 会自动加 --wa.reset_per_task on
#   map：WA_MAP_HOST=http://10.44.12.7 bash scripts/run_wa_fleet.sh map   （FORCE=1 仅在不共享机器时合理）

# 5. 监控
bash scripts/wa_status.sh
tail -f runs/wa_fleet_gitlab_all_<stamp>.log       # 每题一行 "[arm] i/N t<id> reward= nc=/n cumSR= win10= mem= spent=$"
kill -USR1 <pid>                                    # 疑似卡住时 dump 全部线程栈

# 6. 结束后分析（run 目录带双时间戳）
.venv-wa/bin/python scripts/analyze_ab_mean.py runs/wa_fleet_gitlab_all_<stamp>_<stamp2>
.venv-wa/bin/python scripts/analyze_wa.py runs/wa_fleet_gitlab_all_<stamp>_<stamp2>
python scripts/attribute_source_bucket.py --all-fleet
```

`run_wa_fleet.sh` 实际展开的 python 命令（非 map 站、FILTER=all）：

```bash
LLM_TIMEOUT=180 caffeinate -i .venv-wa/bin/python -m hippo.wa.run \
  --llm.model gpt-5.6-sol --llm.embed_model local/BAAI/bge-small-en-v1.5 \
  --wa.base_url http://10.44.12.29 --wa.site <SITE> --wa.limit 0 \
  --wa.task_filter all --wa.fleet_reset on --wa.arms nomem,withmem \
  --agent.n_traj 8 --wa.eval_rollouts 8 --memory.retrieve_k_reasoning 1 \
  --wa.max_steps 30 --wa.step_timeout 90 --wa.reset_timeout 120 \
  [--wa.reset_per_task on]   # reddit \
  --wa.base_urls http://10.44.12.29,http://10.44.12.12,http://10.44.12.27,http://10.44.12.38,http://10.44.12.41,http://10.44.12.44,http://10.44.12.48,http://10.44.12.58 \
  --run.budget_usd 1000000 --run.name wa_fleet_<SITE>_all_<stamp> 2>&1 | tee runs/wa_fleet_<SITE>_all_<stamp>.log
```

map 版本把 `--wa.base_url http://10.44.12.7 --wa.task_filter readonly --wa.fleet_reset off --wa.timeout 60000 --wa.rollout_stagger 4` 替入，不传 base_urls。脚本环境变量：SITE（位置参数，默认 shopping）、FILTER（readonly|all|string_match，默认 readonly）、NTRAJ 8、ARMS nomem,withmem、MODEL gpt-5.6-sol、RUN_NAME `wa_fleet_${SITE}_${FILTER}_<YYYYmmdd_HHMMSS>`、LLM_TIMEOUT 180、FLEET_RESET（默认 all→on 否则 off）、BUDGET 1000000、WA_MAP_HOST、FORCE。

脚本 echo 的 "== [site] filter=... -> runs/..." 头行在 tee 之前输出，不在 .log 里；.log 里也不打印模型名，模型只在 run_start 事件配置里。

fleet 之前的单机脚本（run_wa_site.sh、run_wa_full.sh、run_wa_replicate.sh、run_wa_rest.sh、run_wa_sym.sh）默认 BASE=http://10.44.12.29、MODEL=gpt-5.6-sol、`--wa.readonly_only true`（legacy 230 题）；最早的 run_wa.sh 则写死 base_url 10.44.12.29、默认 `--wa.limit 40`、`--agent.n_traj 5`、READONLY=true，只跑每站前 40 题。reddit 正典 run 就是 `N=8 BASE=http://10.44.12.29 bash scripts/run_wa_sym.sh reddit`。

## 11. SWE-bench Verified 设置

数据集是 HuggingFace `princeton-nlp/SWE-bench_Verified` test split，`datasets.load_dataset` 后按 instance_id 排序（流顺序按 repo 分组、组内近似时间序）。`swe.repos` 逗号子串匹配 repo 字段（默认 django），`swe.filter` 是 instance_id 正则，`swe.limit` 头部截断（0 不截）。repos=django 得 231 题，其中 django__django-10097 与 django__django-7530 没有 Epoch arm64 镜像被跳过，nomem 实评 229。

agent 在 Epoch AI 重建的逐题 arm64 镜像 `ghcr.io/epoch-research/swe-bench.eval.arm64.<instance_id>:latest`（小写）里跑，代码注释称 Verified 上 arm64 覆盖 420/500。`ensure_image` 在 N 个并行 attempt 前预拉一次：`docker image inspect`，然后最多 3 次 `docker pull -q`（pull_timeout 1800 s，间隔 sleep 30·(i+1) s），'not found' 返回 False 跳题。

agent 框架是 pip 上游 mini-swe-agent 2.4.5，只用它的 DefaultAgent + DockerEnvironment + get_model。配置从内置 `benchmarks/swebench.yaml` 起（system/instance 模板、提交协议 `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt`），hippo 改 step_limit 250→`swe.step_limit` 60、cost_limit 3.0→`swe.attempt_cost_limit` 0.5 USD/attempt、pull_timeout 120→1800。Docker 环境：cwd /testbed、命令超时 60 s、`bash -c`、BASH_ENV=/root/.bashrc、`--rm`、container_timeout 2 h。每个 attempt 自己的新容器，finally 里 `env.cleanup()`，因此同题 N 个 attempt 状态隔离。记忆注入是在 instance_template 前加 Jinja 块 `{% if memory %}<memory>...{{memory}}</memory>{% endif %}`，空记忆渲染为空，nomem prompt 与原生 mini-swe-agent 相同；'attend' 变体强制首回复声明哪些条目适用。agent 模型未设 temperature；mini-swe-agent 对含 anthropic/claude 的模型名自动 `set_cache_control='default_end'`。主实验（big、fc_、abl_、slice_、sym_）用 60 步/$0.5；"官方设定"run（align_default、v2_notes、orc_*）用 250 步/$3.0。

判官 `judge_attempt` 有确定性前门：exit_status != 'Submitted' 或空 patch → success=false 不调 LLM。否则看 problem_statement[:3000]、compact trace（<=30000 字符，test 类命令输出保留 1600+200 尾、其它 400，首 1/3 尾 2/3）、patch[:6000]，返回 `{success, verified, reason, evidence}`；'verified' 要求 trace 字面显示改动后 repro/test 通过；prompt 要求不确定时 success=false。

记忆参数：`memory.mode=reasoning_only`、`scope_reasoning=True`，scope=`repo:<repo>`；检索 query = problem_statement[:2000]，`memory.retrieve_k_reasoning=4`（除 swe_calib 传 2 外所有 SWE run 的 CLI 覆盖；yaml 默认 1）；render 16000 字符上限。L1 只对"意外"attempt（失败或成功但未 verified）写，跳过 verified 成功与 SetupError，每题上限 `l1_max_per_task`=2，每次最多 2 条，输入 trace[:15000]、patch[:3000]。L2 只在 0<nc<n 且 |2·nc − n| >= `vote_margin`=2 时触发（N=5 即 1:4 或 4:1；2:3/3:2 记 `swe_l2_skipped_close_vote`），多数失败→提炼成功做了什么，多数成功→提炼陷阱，最多 2 条，逐 attempt trace[:6000]、patch[:1500]。去重键 (scope, 归一化 title)，追加式。注入门控 `swe.injection_gate` none|llm（llm：fetch 10 候选，`select_relevant` 保留条件匹配的下标，可为 0，解析失败则放行，再截到 k）；`swe.injection_style` plain|attend；`swe.memory_scope=global` 让检索跨 repo 搜全库。

三臂：nomem（retrieve/write 关，每题 1 attempt，题间 `swe.task_workers`=4 线程并行）；withmem（都开，n_traj=5 attempt 在 `min(n_traj, run.concurrency=8)` 线程池里，题间严格串行）；frozenmem（retrieve 开 write 关，`--swe.memory_in`，1 attempt，题间并行）。每题提交的 patch 永远是 attempts[0] 的（model_name_or_path 'hippo-{tag}'）；nc = 判 success&&verified 的 attempt 数；metrics 的 judge_success 是 attempt 0 的判决。臂顺序固定 nomem → frozenmem → withmem；`swe.skip_done` 按 preds json 剔题（续跑 / 构造留出集）。

真值由 `scripts/eval_local.py` 用原装 swebench 4.1.0 harness 算：`make_test_spec(instance, arch='arm64')`，把 Epoch 镜像 tag 成 `spec.instance_image_key` 与 `spec.env_image_key`，调未修改的 `run_instance(..., timeout=1200)`；空 patch 定义为未解决；输出 `gt_{run_id}.json`（instance_id → True/False，None=无镜像/评测出错）写在 preds 旁。final_campaign 传 run_id 'gt_<无时间戳目录名>'，所以文件名形如 `gt_gt_fc_django_nomem_s1.json`。sb-cli 0.1.4 装了但 HANDOFF 说云评测坏了没用。GT 从不进入学习循环。final campaign 的机器纪律：所有 rollout 串行，不与 GT 评测并行，全部跑完后再统一 eval_local。

主要 run：

| run | 配置 | 结果 |
|---|---|---|
| `runs/swe_big_django_20260712_190710` | agent+判官 haiku-4-5，django 231，nomem,withmem，n_traj 5，k 4，60 步/$0.5，预算 $180，07-12 19:07 起约 8.9 h | nomem 229 题 judge_sr 0.5066、agent 花 $48.87；withmem 在 $180.55 时 BudgetExceeded，115 题后停，bank 243 条（185 L1 写、58 L2 写、29 次 close-vote 跳过），527 次判官调用，804 个轨迹文件。GT：nomem 98/229=42.8% 全集；115 学习题上 nomem 49/115=42.6% vs withmem 51/115=44.3%；114 留出题上 nomem 49/114=43.0% |
| `runs/abl_*`（07-13，frozenmem，114 留出，243 条 bank，预算 $35） | abl_plain gate=none；abl_gate gate=llm；abl_attend gate=llm+attend；abl_l1only/l2only/suconly 用过滤 bank（185/58/26） | 57/114=50.0%；55=48.2%；54=47.4%；49=43.0%；46=40.4%；50=43.9% |
| `runs/fc_*`（`scripts/final_campaign.sh`，07-17） | 3 repo（django 114 / sympy 35 / sphinx 14 留出）× 3 臂（nomem、repo bank frozenmem、global bank frozenmem+memory_scope=global）× 3 seed，每 run 预算 $40；repo bank = django 243 / sympy 82（`sym_stream_20260714_044044`，40 题学，N=5，预算 $70、实花 $42.68）/ sphinx 68（`fc_sphinx_learn_20260717_001830`，30 题学，N=5，预算 $45、实花 $34.76）；global bank = `runs/fc_global_bank.json` 三库拼接 393 条 | django nomem s1/s2/s3 48/52/58 of 114；repo 53/52/49；global 45/50/54。sympy nomem 16/18/17 of 35，repo 18/17/15，global 18/20/15。sphinx nomem 5/7/4 of 14，repo 6/6/3，global 5/5/5。28 个 fc_ run 合计 $349.04，每个 django 臂约 1.2 h、$24–25 |
| "四次独立重复" | seed-0 原始 + fc seed 1–3，同一 114 留出题 | nomem {43.0, 42.1, 45.6, 50.9} 均 45.4；repo bank {abl_plain 50.0, 46.5, 45.6, 43.0} 均 46.3；global 3 seed 均 43.6 |
| `runs/align_default_20260713_225859` | 250 步/$3.0，nomem + frozenmem(bank_A_116)，114 留出，花 $71.12 | GT nomem 82/114=71.9%，frozen 83/114=72.8% |
| `runs/swe_tail_20260713_135958` | 从 243 条 bank 继续 withmem 学 116 题，预算 $120，$120.65 停在 110 题，bank 469 | 含快照 bank_A_116(243)/B_180(367)/C_180noL1(277)/B_cons_080(237)/B_cons_085(313)/B_consolidated(69)；slice 46 题：A116 23、B180 19、C180noL1 20、Bcons 21 |
| `runs/swe_calib_20260712_182046` | 25 django 题 nomem，预算 $15，24 评 | judge_sr 0.50；gt_calib_local2.json 11/24；HANDOFF 称判官准确率 87.5%、精度 0.833 |

`run.seed` 传了（`--run.seed 1/2/3`）也记进配置，但 SWE 任何代码路径都不读它；seed 只是标签，重复间差异来自 provider 侧采样（agent 无 temperature），判官调用 temperature 0 且有缓存。所有 SWE harness 代码在单个提交 b08f899（2026-07-20）入库，晚于 SWE run（07-12 至 07-17）。

## 12. Mind2Web 设置

先说结论：本机没有任何 Mind2Web run 目录。`runs/` 286 个条目里没有匹配 m2w|mind2web|stream_L|learned_memory|m2w_ab_mem|m2w_ch_mem|m2w_ps_mem|poscontrol 的；没有任何 `summary.json` 含 `hippo.m2w.run` 必写的 `test_split` 键；没有任何 `events.jsonl` 含 m2w 专有事件 stream_step/step_write_l1/test_episode。仅有的 t_d1/t_d2/t_nomem_*（07-12 两组、07-21、07-26，共 12 个目录）是 `hippo.run` 的 mock run（config.json run.mock true，n=60）。`data/` 目录不存在（gitignored，HANDOFF 说曾有约 11 GB）。所以文档中的每个 Mind2Web 数字（nomem element_acc 0.353；L1 +0.021/+0.054；L2 +0.024/+0.033；L1+L2 −0.009；stream +0.009；bank 104/40/218；+5.4；+9.8；252 题/69 站；60%/84%/88% 可解）都只有文档陈述，无法从本机验证。

代码层面：所有 m2w 代码（`src/hippo/m2w/*`、`brain.py`）与 8 个 `run_m2w*.sh`、`convert_mind2web.py` 在 42b072b（2026-07-03）一次提交，至 HEAD 字节未变。数据布局 `data/mind2web/<split>/*.json` 分片（按文件名尾数排序），ranker 分数来自 `<data_dir>/scores_all_data.pkl`（keys 'scores'/'ranks'，按 `{annotation_id}_{action_uid}` 再 backend_node_id 索引；代码注释称是 AWM 用的 DeBERTa ranker）。默认 test split 是 test_task，learn_split 空则在同一 split 内按站点 holdout（每站 `max(1, int(len·0.5))` 题进学习集，单题站只进测试集；`seed` 参数被接受但不使用）。所有脚本都只用 test_task，从未跑 test_website/test_domain。

观测是 `[gold pos_candidates[0]] + top-(k−1) 负候选`（按 rank 升序）的剪枝 DOM，`m2w.top_k` 默认 5（HANDOFF 命令用 50）；DOM 渲染从 AWM 移植（MindAct 格式，prune_tree max_depth 5、max_children 50、max_sibling 3）。步"可解"当且仅当存在正候选且有正候选 rank < top_k；不可解步三项指标记 0 且不调 LLM。协议是教师强制：每步之后把 gold 动作（不是预测）追加到 history。指标：element_acc = 预测元素 id 在 pos_ids；action_f1 = 操作+值的 token-set F1（不含元素 id）；step_success = `pred_act.strip() == target_act.strip()`；task_success = 全部步 step_success；每 episode 对所有步取均值，run 级对 episode 取无权均值。

三种协议：step_evolve（默认；nomem 在测试集用空记忆跑 → 学习集 step_learn_phase（或加载 memory_in）→ 同一测试集冻结记忆跑 withmem；测试期 temperature 0.0、无写入，两臂在同一留出 episode 上配对）；stream（learn=False 跑 nomem 基线，再 learn=True 跑 'stream' 臂写 metrics_stream.csv；每步 n_traj 个 rollout 并发，rollout 0 贪心且计分，r>0 用 temperature+0.0001·r，L1/L2 在线写）；''（任务级，唯一使用 surprise.* 与 consolidate() 的地方，但 `extract_fact` 函数体被截断只剩 prompt 字串，返回 None，不会写 FactItem）。step_evolve 与 stream 只写 FactItem（`write_fact` upsert），不产生 ReasoningItem。L1 = `judge_step`（每 attempt 每步一次，temperature 0；模型收到 gold 控件 CORRECT_CONTROL，返回 {genuine, reason, intent, cue, trap}；语句模板 "When {intent}: use '{label}' ({role})" + 可选 ", not '{trap}'" + ". {cue}"）；L2 = `extract_step_experiences`（仅 0 < n_correct < n_attempts 时，至多 3 条）。`m2w.record_mode` 传入但函数体不用，aggregate 与 all 行为相同；`m2w.fact_gate` 无代码读取。

脚本默认：run_m2w.sh（gpt-4o-mini，40/40，NTRAJ 3，预算 8，threshold 0.3）；run_m2w_step.sh（gpt-4o，60/60，k_fact 8，预算 30）；run_m2w_ab.sh / run_m2w_channels.sh / run_m2w_perstep_ab.sh / run_m2w_abc.sh / run_m2w_poscontrol.sh 见各文件。HANDOFF 的 stream 命令：

```bash
python -m hippo.m2w.run --brain llm --m2w.protocol stream --m2w.test_split test_task \
  --m2w.top_k 50 --memory.mode fact_only --m2w.layer1 on --m2w.layer2 on \
  --agent.n_traj 5 --m2w.test_limit 20 --run.budget_usd 10 --run.name stream_test
```

哪个脚本/模型产出了 HANDOFF §5 的静态 A/B（49 留出题 / 334 步）不可知；SCORES_VS_COMPETITORS.md 说 gpt-4o-mini，HANDOFF 未写模型。"+9.8 另机 run" 在仓库里没有任何产物、配置或 run 名。`memory.retrieve_k_reasoning` 默认从 42b072b 时的 2 变为 HEAD 的 1，只有 run_m2w_ab.sh 钉住了 2。

## 13. 产物与目录结构

### 13.1 runs/ 命名与 git 状态

run 目录名为 `<run.name>_<YYYYmmdd_HHMMSS>`，而 fleet 脚本的 run.name 本身已含时间戳，所以出现双时间戳，如 `wa_fleet_gitlab_all_20260815_172053_20260815_172110`（前者 shell 启动时刻，后者 RunLogger 建目录时刻）；对应控制台日志是 `runs/<run.name>.log`（单时间戳）。前缀对应：`wa_fleet_<site>_<filter>_` = run_wa_fleet.sh；`wa_sym_<site>_` = run_wa_sym.sh；`wa_<site>_` = run_wa_site.sh；`wa_rep_<site>_` = run_wa_replicate.sh；SWE 的 swe_*、abl_*、slice_*、sym_*、orc_<id>_*、v2_notes_*/v3_fable_*、fc_<repo>_<arm>_s<seed>_*。

本机 `runs/` 有 286 个条目、29 GB；git 跟踪 944 个文件、410 MB，全部在一个提交 463d80f（2026-08-31）入库。`.gitignore` 排除 `runs/**/*.traj.json` 与 `runs/**/trajs/`（SWE 原始轨迹，84 个目录 4716 个文件，注释称 28 GB、单文件超 GitHub 限制），全局排除 `*.log` 但用 `!runs/*.log` 放回（71 个 .log 被跟踪）；还排除 data/、.cache/、logs/、sb-cli-reports/、.env、.env.aws。

### 13.2 WA run 目录

完整 WA run 恰好 7 个文件：events.jsonl、memory.json、metrics_nomem.csv、metrics_withmem.csv、rewards_nomem.json、rewards_withmem.json、summary.json（gitlab_all 0815：events 24.6 MB / 36,248 行，memory.json 3.57 MB）。被中断的 run 缺 summary.json 和 withmem 文件（如 shopping_readonly 0805 只有 events、memory、metrics_nomem、rewards_nomem）。

`events.jsonl` 每行含 t（epoch 秒，3 位小数）、run_id、kind。事件种类与字段：

| kind | 关键字段 |
|---|---|
| run_start | n_tasks，完整解析后配置（run/llm/agent/memory/m2w/swe/wa） |
| reset_done | tag, seconds, site |
| reset_failed | tag, seconds, err（stdout 末 800 字符） |
| reset_timeout | tag |
| reset_skipped | tag, why |
| wa_episode_start | tag, task_id, rollout, goal, mem_injected, mem_chars |
| wa_step | tag, task_id, rollout, step, thought, action, raw, url, reward, action_error, terminated |
| wa_host_guard | goto 改写的 was/now |
| wa_episode_end | reward, n_steps, stop_answer, n_action_errors |
| wa_episode_error | err |
| wa_judge | tag, task_id, rollout, reward, outcome, reason |
| wa_retrieve | n_retrieved, scores, titles, mem_chars |
| wa_write_l1 | task, item.title |
| wa_write_l2 | task, nc, n, n_fluke, item.title |
| wa_rollouts_dropped | n_err, n_scored |
| wa_task_all_failed | n_err |
| wa_task | tag, task_id, template_id, reward, nc, n, n_mem, cum_sr, win10_sr, l1_total, l2_total, ret_titles, errors |
| task_error | 异常信息 |

gitlab_all 0815 的计数：wa_step 26677、wa_judge 2880、wa_episode_start 2878、wa_episode_end 2862、wa_task 360、wa_write_l1 314、wa_retrieve 180、wa_write_l2 61、wa_episode_error 18、wa_rollouts_dropped 14、reset_done 2、wa_host_guard 1、run_start 1。

`memory.json` = `{"reasoning": [...], "fact": []}`，每条 ReasoningItem 字段：title, description, content, scope, certainty, outcome, layer, source_traj_ids, surprise, id（rsn_<8hex>）, created_at, embedding（384 维）。gitlab 正典 bank 157 条 = 130 L1 + 27 L2，全部 scope site:gitlab，outcome failure 152 / success 5，certainty 全 'medium'。

`.log` 以 beartype 警告开头，然后 `[info] run_id=... site=... tasks=... arms=['nomem', 'withmem']`，`[info] [nomem] rollout isolation ON: 8 deployments [...]`，fleet_reset 开时有 `[nomem] resetting all sites from pristine images` 与 `reset of all sites done in 221.1s`；每题一行 `[info] [<arm>] <i>/<N> t<task_id> reward=<0|1> nc=<nc>/<n> cumSR=<x> win10=<x> mem=<bank> spent=$<累计>`；结尾 `[info] DONE {<summary dict>}`。

### 13.3 SWE run 目录

`events.jsonl`（kinds run_start, skip_instance, swe_task, swe_write_l1, swe_write_l2, swe_l2_skipped_close_vote, task_error, retrieve_error）、`metrics_<arm>.csv`（idx, instance_id, repo, judge_success, nc, n, steps, cost）、`preds_<arm>.json`（SWE-bench 提交格式）、`memory.json`（withmem）、`summary.json`、`trajs/<instance_id>.<arm>.a<r>.traj.json`（gitignored）、`gt_*.json`（eval_local 输出）。big run 另有 bank_l1.json(185)/bank_l2.json(58)/bank_success.json(26) 及离线 `scripts/build_notes.py` 生成的 notes_v2.json（96 文件/286 条）、notes_v3_fable.json（101/300）。

### 13.4 正典分数对应的 run 目录

| 文档数字 | run 目录 | 口径 | 复核值 |
|---|---|---|---|
| shopping +10.8（67 配对题） | `runs/wa_fleet_shopping_readonly_20260805_182840_20260805_182907` | 均值 nc/n | 0.5336 → 0.6418；nomem 跑完 139 题（均值 0.5162），withmem 在第 67 题 t272 后因断网中断；无 summary，最后一行 spent=$556.93 |
| gitlab +5.4（67） | `runs/wa_fleet_gitlab_readonly_20260809_115734_20260809_115744` | 均值 | 0.6786 → 0.7329；summary reward_sr 0.6567 → 0.7463；pass@8 0.761→0.821；8/8 0.567→0.597；L1 130 / L2 27；$571.06；4.13 h |
| reddit +5.7（11） | `runs/wa_sym_reddit_20260724_224549_20260724_224551` | 均值 | 0.5682 → 0.6250；reward_sr 0.5455 → 0.6364；单部署 .29，readonly_only，题 [27,28,29,30,31,66,67,68,69,723,726]（t723 按清单为 mutating）；L1 32 / L2 5；$128.21；1.80 h |
| shopping_admin +8.3（109） | `runs/wa_fleet_shopping_admin_readonly_20260809_202133_20260809_202143` | 能力口径 0.789 → 0.872 | 原始均值 0.6735 → 0.6719（−0.2）；reward_sr 0.6239 → 0.633；L1 266 / L2 49；$1439.84；7.41 h；19 wa_episode_error、13 wa_rollouts_dropped |
| shopping 全集 | `runs/wa_fleet_shopping_all_20260811_191401_20260811_191415` | 187 题 | 均值 0.5591 → 0.5775；reward_sr 0.5722 → 0.6043；$1283.70；21.28 h |
| gitlab 全集 | `runs/wa_fleet_gitlab_all_20260815_172053_20260815_172110` | 180 题 | 0.7221 → 0.7484；reward_sr 0.7278 → 0.7167；$1409.44；14.40 h |
| reddit 全集 | `runs/wa_fleet_reddit_all_20260814_002621_20260814_002652` | 106/105 题 | 0.7995 → 0.8071；$693.49；15.54 h；192 reset_done |
| shopping_admin 全集 | `..._20260816_202148_*` 与 `..._20260818_005633_20260818_005647` | 182 题 | 0.6557 → 0.6566（$2919.98，16.84 h）；0.6489 → 0.6508（$2903.29，17.11 h） |
| map | `runs/wa_fleet_map_readonly_20260813_103741_20260813_103743`（0812 那次 `..._20260812_223651_20260812_223653`，87 对） | 109 题，107 配对（summary nomem 108 / withmem 107） | 均值 0.5922 → 0.5952；reward_sr 0.5185 → 0.6075；$540.53；12.76 h。0812：均值 0.6138 → 0.5927（−2.1），nomem 88 / withmem 96 题有分（all_failed 21 / 13 题），$439.96，8.78 h |
| SWE 43.0 → 50.0 | `runs/swe_big_django_20260712_190710/gt_big_nomem_gt.json`（限 114）vs `runs/abl_plain_20260713_040638/gt_abl_plain_gt.json` | 官方 harness 解决率 | 49/114 vs 57/114 |

全集五 run 的 761 配对题合并（PAPER_DIRECTION_REVIEW）：逐题差均值 +1.27 点，正态近似 95% CI [−0.3, +2.8]，120 涨 / 99 跌 / 542 不动；分站 shopping +1.8、gitlab +2.6、admin +0.2（0818）/+0.1（0816）、reddit +0.8、map +0.3（0812 那次 −2.1，87 对）。

fleet run 清单共 22 个：shopping readonly ×3（0803、0805、0806）、shopping all ×1（0811）、shopping_admin readonly ×4（0807、0808、0809×2）、shopping_admin all ×2（0816、0818）、gitlab readonly ×3（0808、0809×2）、gitlab all ×2（0814 中止、0815）、reddit all ×5（0809 与 0810_200251 两次在臂初重置就失败、无任何 wa_task；0810_203514 跑了 34 题、0811 跑了 35 题后中断；0814 完成）、map readonly ×2（0812、0813）。`wa_fleet_gitlab_all_20260814_222525` 12.34 h 只完成 1 道 nomem 题，日志 12.5 MB，原因未记录。各 fleet run 的 `spent_usd` 汇总：49 个有 summary 的 WA run 合计 20311.02 USD，80 个有 spent_usd 的 SWE/其它 run 合计 1066.78 USD（另 12 个 t_* mock run 的 summary 无 spent_usd）。

## 14. 时间线

2026-07-03 首次提交 42b072b "agent memory self-evolution on Mind2Web"，含 DESIGN.md、HANDOFF.md；07-04 README 相关提交。

2026-07-12 SWE 阶段开始：swe_smoke、swe_calib、swe_big_django（19:07 起）；07-13 abl_*、slice_*、swe_tail、align_default；07-14 orc_*、v2_notes、sym_*；07-16 v3_fable；07-17 final campaign fc_*（00:18 sphinx learn 至 18:35）。

2026-07-18 首台 EC2（10.44.12.29）启动，首批 WA run（wa_smoke、wa_shopping_gpt5_6sol N=5）；07-19 四站单 rollout run（launch_<site>.log 的 2026-07-19 基线）；07-20 提交 b08f899 加入 hippo.swe 与 hippo.wa harness；07-24 提交 40d92fc（答案感知判官、答案盲写手、fluke no-op、worker 回收、host guard、预算不设限）及首个对称 8v8 run wa_sym_reddit；07-25 895d871（WA_FINDINGS、consolidation 原型）；07-26 AMI 克隆到 8 台。

2026-08-03 首批 fleet run；08-05/06 shopping fleet；08-07 至 08-09 shopping_admin 与 gitlab fleet；08-09 reddit all；08-10 提交 92e1afb（8 机隔离、冻结清单、AWS_FLEET.md、n_err 分母修正）；08-11 至 08-18 FILTER=all 全集 run（shopping 0811、gitlab 0814/0815、reddit 0814、shopping_admin 0816/0818）与 map 0812/0813；08-13 HIPPO_DESIGN/WA_DESIGN；08-14 N/A 审计与 L2 守卫红队；08-16 BENCH_RESEARCH_2026；08-26 L1_L2_SURPRISE；08-31 提交 4ef2376（写手纪律、确定性 N/A 判分、看门狗、文档）与 463d80f（全部 run 数据）；09-09 论文材料提交；09-13 提交 f1bebc1（RETRIEVAL_INJECTION_ABLATIONS.md）。

`src/hippo/wa/run.py` 的功能考古：b08f899（07-20，399 行）只有 eval_rollouts 与 metis 归一化；40d92fc（07-24，450 行）加 select_lesson 门控、inject_only_l2、max_tasks_per_child、_guard_host、答案盲写手、fluke 处理；92e1afb（08-10，610 行）加 base_urls 逐 rollout 池、_kill_pool、fleet_reset；4ef2376（08-31，792 行 = HEAD）加 _NONE_RX、episode_timeout、rollout_timeout、reset_per_task、stall reporter、rollout_stagger、写手 max_tokens 16000。每个 run 用的确切 commit 没有存在 summary/run_start 里，且不能凭提交时间对应：run_start 配置显示工作树领先于提交（08-09 readonly run 无 rollout_timeout/episode_timeout；shopping_all 0811 只有 rollout_timeout=1800、无 episode_timeout；map 0812 起有 episode_timeout=900；map 0813 起有 rollout_stagger；reddit_all 0814 起有 reset_per_task），而这些键直到 4ef2376（08-31）才入库。第 9 节的看门狗表因此只对 08-14 之后的 run 完整成立。

## 15. 文档与代码不一致处

以下按主题归并，每条以代码/产物行为为准。

协议与 N：WA_FINDINGS.md:11 与 WA_SCORES.md "基线单跑 vs 方法" 说基线是单跑、8 个 rollout 只属于方法；但 `run_wa_fleet.sh:100` 传 `--wa.eval_rollouts 8`，所有 fleet run_start 都是 eval_rollouts=8，nomem 也是 8 rollout（WA_DESIGN.md:7 正确）。HIPPO_DESIGN/WA_DESIGN/L1_L2_SURPRISE 写"8 个并行 rollout"，yaml 默认却是 agent.n_traj 5、eval_rollouts 1，8 只来自脚本的 NTRAJ。PAPER_MAIN_TABLE.md:5 称每格 N=8，SWE 实跑写臂 N=5、评分臂 1。

模型：config/default.yaml llm.model=openai/gpt-4o-mini、judge.model=openai/gpt-4o-mini、swe.agent_model=openai/gpt-5-mini，全部被 CLI 覆盖；`judge.model` 在 WA/SWE/M2W 三条路径都不被读取，判官与 agent 同模型。WA_FINDINGS.md:132 称 temperature 被 drop_params 剥掉，litellm 1.92.0 实测把 temperature 发出去了（网关是否遵守未知）。

重置：`run.py:11` docstring 说"via WA_FULL_RESET"，`reset_site` 自己的 docstring 与 yaml:73-75 说该端点从未部署，真正的重置是 `wa_fleet.sh reset`。`run_wa_fleet.sh:14-16` 头注释说"nothing here resets between tasks"，第 67 行却给 reddit 加 `--wa.reset_per_task on`，reddit_all 0814 有 190 次逐题重置。`wa_fleet.sh:30-32` 注释建议 check 只探即将使用的站，`run_wa_fleet.sh:87` 却不带站名探四站。WA_FINDINGS.md:162 说 GitLab 恢复 5.5 分钟，实测全站并行重置 221–244 s。

判官/写手信息流：`run.py:8` 说学习"label-free"，判官实际收到 reward 与参考答案。`brain.py:11-12` 说写手"never see"参考答案，但 `brain.py:147,252` 把（看过答案的）判官 reason 原文喂进 L1/L2 prompt，WA_FINDINGS.md:212-216 已记为"声明的泄漏"。`run.py:473-474` 注释说 L1 传入参考答案，实际调用不传。L1_L2_SURPRISE.md:8 说蒙对按 surprise 处理，代码里 fluke 是 no-op（L1 跳过、L2 分子分母剔除）。yaml:102 `wa.l1_fluke`、yaml:107 `wa.divergence_signal`、yaml:125 `wa.seed`、`run.seed` 在 src/hippo/wa 中无人读取；`wa.vote_margin` 读了不用。L1_L2_SURPRISE.md:34 描述的向量相似+LLM 去重，代码只有精确 title 去重、追加式存储，LLM 合并只在离线原型 `scripts/consolidate_wa_bank.py`。L1_L2_SURPRISE.md:42 说 fetch_k=10，WA 是 5（10 是 SWE 默认）。

代码回退值与 yaml 不一致（yaml 生效）：max_steps 20 vs 30、wa.max_tokens 4000 vs 8000、inject_gate 'none' vs 'llm'、vote_margin 2 vs 1；yaml 未列 `wa.rollout_stagger`、`wa.reset_timeout` 但代码读取、脚本传递。SWE 侧 yaml 未列 swe.task_workers、memory_scope、memory_in、skip_done、notes_in、filter。

题数与模板：`data.py:6` 与 WA_FINDINGS.md:208 说 241 模板 × 3.4，test.raw.json 是 190 个 intent_template_id、均 4.27。WA_FINDINGS.md:44 说 legacy 集漏进 11 道 mutating，`data.py:63-64` 与重算都是 12（多 shopping_admin t491）。WA_FINDINGS.md:44 说 445 道单站 mutating，清单给 330（764−434）。yaml:113 说 legacy 230，仅从清单出发是 307 道单站只读 string_match 题，230 无法单独复现。WA_SCORES.md:5-9 的题数 146/111/27/69（合 353）与同一组数字在 WA_FINDINGS.md:305-308 的 67/109/11/67 冲突，前者对不上任何 run 目录。WA_SHOPPING_ALL.md:3 说剔除 t572（n=186），总分表数字只在含 t572 的 187 题上复现。WA_FINDINGS.md:168 说 08-03 shopping 74 题、:335/:354 说 77 题（wa_task 配对 vs episode_end 配对）。WA_FINDINGS.md:339 说 66 次 run，runs/ 在该日期段有 75 个含 events 的 WA 目录（21826 条 rollout 数字精确匹配）。

headline 报告：SCORES_REPORT.md:5 把 WebArena 写成 "812 题 64.3% → 71.8%"，实为四站 254 配对题各自差值的无权平均，且 shopping_admin 用能力口径、其它用原始均值，四站来自不同 run；SCORES_REPORT.md:6 写 SWE "500 题 43.0 → 50.0"，实为 114 道 django 留出题，且四次重复后 45.4 vs 46.3 已撤回；SCORES_REPORT.md:7 的 Mind2Web 65.4 → 74.6（+9.2）无任何产物，其它文档说 +9.8/+5.4、绝对分待归档。SCORES_REPORT.md:16 的 shopping_admin 78.9 → 87.2 未注明是审计口径。WA_FINDINGS.md:7,13、WA_DESIGN.md:31 说 N/A 与多元素 fuzzy 题应剔出主指标，但 WA_SHOPPING_ALL、WA_GITLAB_ALL、WA_SCORES、PAPER_DIRECTION_REVIEW 的 headline 表都是全题均值。WA_GITLAB_ALL.md:3 说 08-15 run 带 www.reddit.com 归一化，git 中该改动与 N/A 规则首次出现在 08-31 的 4ef2376。

基础设施文档过期：HANDOFF.md:9-11（07-18）仍写单机 10.44.12.29；HANDOFF.md:132,150 说 runs/ 不进 git（现已进）；HANDOFF.md:19 说 axtree 截 40k（代码不截）；HANDOFF.md:28 说 LLM 超时 120 s（脚本导出 180）；README.md:176 计划 us-east-2 t3a.xlarge（实际 us-west-2 8×m6i.xlarge，t3a.xlarge 只用于 map 前端）；AWS_FLEET.md:129 与 WA_FINDINGS.md:44 说 map 未跑/不可达（后来部署了 map 机器并跑了两次）；HANDOFF.md:12 tar 合计 195G 与 AWS_FLEET.md 镜像 424 GB 是压缩包 vs 载入镜像。README.md:159 django 231 vs HANDOFF.md:93 229（231 载入、229 计分）。README.md:168 "独立重复四次"，fc 只有 3 seed，第四次是 seed-0 原始 run（不同日期、不同机器负载）。`rollout.py:7` "byte-identical to stock mini-swe-agent" 只对 prompt 成立（step_limit、cost_limit、pull_timeout 均改过）。

Mind2Web：`run.py` docstring 的 `--m2w.limit` 不是实际读取的键（代码只读 `learn_limit`/`test_limit`）；`--m2w.split` 仅作为 `--m2w.test_split` 缺省时的回退键被读取（run.py:527）；run_m2w_abc.sh 的 A 臂（"任务级"）与 C 臂实际都是 step_evolve、B 与 C 因 record_mode 未用而相同；run_m2w_channels.sh 的 reasoning_only 臂等价于 nomem；所有 step 脚本传的 `--surprise.source` 在 step_evolve/stream 下不起作用；stream 协议产出 metrics_stream.csv 而非脚本注释说的 metrics_withmem.csv。

## 16. 已知限制与未完成项

可复现性：`wa.seed`/`run.seed` 无代码读取，重复实验之间的差异只来自 LLM 采样；gpt-5.6-sol 的底层模型与 reasoning effort 未知；网关是否遵守 temperature 未知；每个 run 对应的代码 commit 与 grader 补丁版本没有存进产物；每步 prompt token 数未记录（只有 mem_chars 与 raw 回复）；浏览器 locale/时区未设置，取启动 Mac 的 headless Chromium 默认。

判分：N/A 确定性规则与 reddit host 归一化在所有全集 run 中都未生效（不能凭提交日期推断——4ef2376 里的 rollout_timeout/episode_timeout/rollout_stagger/reset_per_task 在 08-11 至 08-14 的 run_start 配置里已经出现，说明工作树代码领先于提交；reddit 归一化未生效的直接证据是 reddit_all 0814 的 t66：16 条 rollout 全部答 http://10.44.12.x:9999/… 而参考为 www.reddit.com，全部判 0），这些 run 中大量 N/A 题靠空答案得分（shopping_all 176/213）；`WA_GRADER_MODEL` 在实际 run 中是否覆盖了 gpt-4o 默认不可知（`.env` 未读、run_start 不记录）；host guard 只拦 goto，点链接仍会离开自托管环境（reddit_all 0814 到达过 www.mediaite.com、www.npr.org、variety.com），跨 run 范围未量化；template 139 的 url_match 胜利部分由 host guard 改写制造（08-06 shopping：withmem 35 次 vs nomem 16 次）。

题集：reddit 正典 11 题是 legacy 集、含 mutating t723、在单部署上跑；fleet 时代 readonly reddit 只有 10 题，没有配对 run；reddit 全集只跑成一次（0814）；map 8 个 rollout 共用一台前端机（无 base_urls），0812 那次 22/109 题全死、只有 87 对；gitlab_all 有两个 run（0814 中止、0815 完成），shopping_admin_all 两个（0816、0818），哪个是正典未定；reddit withmem n=105 vs nomem 106、map 108/107 of 109 的缺题原因未追。

方法：frozenmem 在 8 机群时代没有跑过（仅 07-18/19 单机 ablation）；WA 判官 genuine/fluke 与人类一致性、各站 fluke 比例未提取；在线 consolidation 未接进主循环（只有离线原型）；WA 脚手架没有单元测试（tests/ 下无 wa 测试）；多数投票/pass@8/8/8/混合口径没有提交的脚本；shopping_admin 能力口径的 14 题审计清单只在散文里。

SWE：主效应在四次重复后消失（45.4 vs 46.3，p=0.87）并已撤回；判官校准（87.5%/0.833）与 p 值、"2.9% 与 gold patch 字面重叠"的计算脚本未在 scripts/ 中找到；agent temperature 取 provider 默认且未记录；Anthropic prompt cache 折扣是否体现在 completion_cost 中未验证；是否经网关未知。

Mind2Web：本机没有任何 run 目录或数据，所有数字不可验证；"+9.8 另机 run" 无任何痕迹；test_website/test_domain 从未跑过；HANDOFF 提到的 stream_L1/L2/L1L2 后台 run 参数未记录；学习期 temperature 0.7 调用不缓存，学习过程原则上不可复现；`extract_fact` 截断、`record_mode`/`fact_gate` 无效等代码问题从未修复。

基础设施：安全组规则、克隆机标签、map 机器实例 ID/AMI/是否仍在运行、机器当前是否停机、AWS 账单均不可从仓库得知；`/data/*.sh` 与 cloud-init 脚本不在仓库；WA_FINDINGS.md:339 的 "66 次 run、163 机时" 无法从 runs/ 复算；各 run 的墙钟只能从首末事件时间戳推得。
