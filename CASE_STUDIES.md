# 记忆救活的题：五个经典例子

每个例子都是从 run 目录的 `events.jsonl` 和 `memory.json` 原样拉的。nc/n = 8 条并行 rollout 里真做对几条。

---

## 例 1 · GitLab：一条经验救活四道题（t742 → t743/744/745/746）

run `wa_fleet_gitlab_all_20260815_172053`

**题目**：t742 是 "Create a new private project 'planner' and add Abishek, Vinta as members"。建项目不难，坑在加成员：新建项目的 README 页上有一条醒目的链接 "Invite team members and collaborators"，点进去是 GitLab 官方文档站，不是这个项目的成员管理页。没有记忆的 8 条 rollout 全部点了这条链接，看到文档就以为任务完成了，0/8。带记忆臂当时库里也没有相关经验，1/8。

**L1 收集到什么**：3 条真失败的 rollout 各写了一条反思，标题分别是 "Use the project Members page and verify every invite"、"Use and verify the project Members page"、"Use and verify the project Members interface"。三条说的是同一件事：那条 README 链接是文档，真正的入口在左侧栏 Project information / Manage → Members → Invite members；选人时按完整显示名和用户名核对；发完邀请回成员列表确认每个人都在。

**L2 总结成什么**（多数错少数对档，nc=1/8——有一条 rollout 做对了，L2 的任务是解释它为什么对）：

> **Use the project Members interface** — Creating a GitLab project and adding one or more users as project members; not for sharing documentation or merely describing collaboration.
> Create a blank project, confirm the exact name/slug and requested visibility, then use the project sidebar's "Project information" or "Manage" → "Members" → "Invite members"; the README's "Invite team members and collaborators" is a documentation link, not the membership control. Select every requested autocomplete account by matching its full display name and username, submit the invite with the requested role or the default when none is specified, and verify every account is visibly listed on the Members page.

**后面怎么用**：t743 "Create a new public project 'web_arena' and add Abishek, Vinta as members"，同一个模板换了项目名和可见性。检索时 description 里 "creating a GitLab project and adding users as members" 和任务意图对上，LLM 门控选中它注入。无记忆臂 0/8，判官原话："It clicked the README's 'Invite team members and collaborators' link, which opened external GitLab documentation rather than the project's member-management page, and then stopped." 带记忆臂 8/8："navigated to Project Members, selected the matching Abishek S (@abisubramanya27) and Vinta Chen (@vinta) accounts, submitted the invitation, and verified both appeared as direct members." t744（AutoAGI + primer）、t745、t746 同一条经验，同样 0/8 → 8/8。四道题、32 条无记忆 rollout 掉的是同一个坑，经验里 "is a documentation link, not the membership control" 那半句就是全部价值。

---

## 例 2 · Shopping：两臂全错，L2 照样提炼出对的口径（t141 → t143）

run `wa_fleet_shopping_all_20260811_191401`，另两次独立 run（08-05、08-06 只读集）同样复现

**题目**：t141 "How much I spent on food-related shopping during March 2023"，参考答案 47.41。两臂 0/8，没有一条做对。错法有两种：一是只看 My Account 首页那个不全的 Recent Orders 面板；二是算对了商品小计但没把运费摊进去——判分口径要求混合订单的 Shipping & Handling 按件分摊到符合条件的商品上。

**L1 收集到什么**：6 条，标题如 "Audit mixed orders and allocate shipping"、"Use full order details and include attributable costs"、"Audit every dated order and include attributable shipping"。判官看得到参考答案，它的失败诊断里写着"该把运费按件摊进去"，写手看不到答案但能看到这句诊断，所以 6 条 L1 都学到了这一点。

**L2 总结成什么**（全错档，nc=0/8——没有成功者可学，L2 的任务是找共同死因）：

> **Audit complete orders and allocate related shipping** — Use for category-spend questions based on purchase history, especially when orders mix qualifying and unrelated merchandise; do not rely on the limited "Recent Orders" panel or interpret a category as consumables only.
> Open "My Account" → "My Orders," review all pages for the requested period, and select "View Order" on every qualifying row. In "Items Ordered," enumerate every visibly category-related product—including accessories, decorations, and supplies—using full names and displayed subtotals, then add each item's attributable share of "Shipping & Handling" based on the visible per-item or per-unit pattern and reconcile the result with the order totals.

**后面怎么用**：t143 "How much I spent on home decoration shopping during 1/29/2023"，参考答案 265.69。无记忆臂 0/8，8 条全部找对了那件 260.69 的家居装饰品，但全部只报了商品小计，判官原话："It omitted the item's $5 share of the $10 shipping charge across the two ordered items; adding that yields the required $265.69." 带记忆臂 8/8："allocated $5.00 of the $10.00 shipping across the two single-quantity items to derive $265.69." 这道题体现的是：来源题自己没做对也没关系，只要失败诊断里有可学的东西，全错档的 L2 就能把口径传给下一道同模板题。

---

## 例 3 · Shopping：多数对少数错，写成一句告诫（t126 → t226/t228）

run `wa_fleet_shopping_all_20260811_191401`

**题目**：t126 "What is the price range of Canon photo printer in the One Stop Market?"，答案 2.56–649.99。无记忆 8/8，带记忆 7/8——只有一条错，错在把搜索结果里的线材、墨盒这类配件也算进了区间。

**L1 收集到什么**：1 条（只有一条真失败）："Verify the complete range, then answer immediately"——用 Advanced Search 按 Product Name 收窄，把 look-alike 的配件耗材排掉，两端核实完就直接答。

**L2 总结成什么**（多数对少数错档，nc=7/8——多数人是对的，L2 只把少数派的错写成告诫，且不许收窄答案形态）：

> **Verify the complete product range, then answer** — Use when a shopping task asks for a price range or other extrema across products; do not use a broad catalog scan when a single product detail page already answers the question.
> Open "Advanced Search," constrain "Product Name" with the brand or identifying product term, use the largest "Show" option, and inspect every results page or sort by price; exclude accessories, parts, supplies, and products that merely mention the brand. Read the full names and prices directly, opening product details if the grid abbreviates them, account for every qualifying or tied row, and once both visible endpoints are verified, stop navigating and explicitly provide the requested range—do not omit the final answer.

**后面怎么用**：t226 "What is the price range for products from Amazon basic?"，答案 5.49–375.19。无记忆臂 0/8：把关键词搜索当成了品牌筛选，7,332 条结果里连衣服家具都有，排序后报了全站极值 $0.01 和 $28,942.99。带记忆臂 8/8：按 Product Name 搜，38 条结果升序读到 5.49，降序读到 375.19，还主动排掉了一个只是附带 Amazon Basics 线材的 $508.37 音箱套装。t228（sephora，18.18–94.99）同一条经验，1/8 → 8/8，无记忆臂把 $10.99 的指甲蜡当成了 Sephora 商品。经验里 "exclude accessories, parts, supplies, and products that merely mention the brand" 是起作用的那句。

---

## 例 4 · Shopping Admin：半对半错，两头都写（t62 → t63）

run `wa_fleet_shopping_admin_readonly_20260808_130520`

**题目**：t62 "Which customer has completed the most number of orders in the entire history?"，答案 Jane Smith。无记忆 6/8，带记忆 4/8。站内有两条路：Reports > Customers > Order Count 报表，好走但没有订单状态筛选，"completed" 这个条件根本没法加；Sales > Orders 把 Status 筛成 Complete 再按客户名手工聚合，麻烦但是对的。

**L1 收集到什么**：4 条，正好分成两派——两条说走 Order Count 报表按年聚合，两条指出这个报表没有状态筛选，得去 Sales > Orders 筛状态。

**L2 总结成什么**（半对半错档，nc=4/8——信息量最大的一档，成功方做对了什么、失败方踩了什么坑都写）：

> **Use the status-filtered grid and aggregate every occurrence** — Applies to historical customer rankings, especially when the question restricts orders by status; the Reports > Customers > Order Count report is suitable only when all statuses qualify or its scope is independently verified.
> For status-specific counts, use Sales > Orders, open Filters, apply the required Status, and ensure every matching record is visible across all pages or an export; do not trust Order Count as a look-alike because it has no status filter. Group every exact full customer name consistently across the complete result—including repeated rows and intervals—compare final totals, include every tie, distinguish near-identical names, and open View if a grid value is abbreviated before answering only from visibly confirmed data.

**后面怎么用**：t63 "Which customer(s) has completed the second most number of orders in the entire history?"，答案是三个并列的 Adam Garcia、Michael Nguyen、Sarah Miller。无记忆臂 2/8，判官原话："used the Customer Order Count report without filtering orders to the 'Complete' status, then treated year-grouped rows as an overall completed-order ranking and selected Grace Nguyen." 带记忆臂 8/8："used the Complete status filter, confirmed all 153 matching records were displayed on one page, and aggregated the Bill-to Name values. It identified the second-highest count as 8, tied by Adam Garcia, Michael Nguyen, and Sarah Miller." "include every tie" 那半句也用上了——这题答案是三人并列，少报一个就错。

---

## 例 5 · SWE-bench Verified：SQL 模板漏空格（django-10880 → django-12039）

run `swe_big_django_20260712_190710`。先说口径：这是 7 月的配置，模型 claude-haiku-4-5，nomem 每题 1 次尝试、withmem 5 次，尝试次数不对等，同配置独立重复 4 次后净效应归零。所以这个例子只看机制，不看效应量。

**题目**：django-10880，Count 带 Case 条件加 distinct=True 时生成的 SQL 是 `COUNT(DISTINCTCASE ...)`，DISTINCT 后面少一个空格。withmem 5 次尝试里 4 次解决。

**L1 收集到什么**："Locate SQL template issues via grep for template strings"——查 SQL 生成的问题不要满仓库翻，直接 grep aggregates.py 和 expressions.py 里的 `template = ` 字符串，看 `%(distinct)s%(expressions)s` 这类占位符拼接有没有空格。

**L2 总结成什么**（多数对少数错档，nc=4/5）：

> **SQL template spacing in Aggregate.as_sql() with DISTINCT** — WHEN: An Aggregate function uses distinct=True AND the expression argument is a complex expression like Case that starts with a keyword. WHEN NOT: Simple field aggregations without distinct.
> The Aggregate.as_sql() method sets extra_context['distinct'] to 'DISTINCT' (no trailing space). The template '%(function)s(%(distinct)s%(expressions)s)' concatenates this directly with expressions, causing 'COUNT(DISTINCTCASE ...)' instead of 'COUNT(DISTINCT CASE ...)'. Fix by adding a trailing space.

**后面怎么用**：django-12039 "Use proper whitespace in CREATE INDEX statements"——`Index(fields=['-name'], name='idx')` 生成的 CREATE INDEX 语句空格错乱。病灶在另一个文件（ddl_references.py），但同一类病：SQL 模板字符串拼接时的空格。无记忆臂 1 次尝试超预算没提交；带记忆臂注入了上面的 L2 和那条 grep 模板串的 L1，5 次里 4 次解决，判官原话："modifying the `Columns.__str__` and `IndexColumns.__str__` methods in ddl_references.py… ensures that empty col_suffixes don't produce trailing spaces, while non-empty suffixes are properly spaced."

---

## Mind2Web

没有。那轮在另一台电脑上跑的，这台机器没有 run 目录，拿不出逐题记录。
