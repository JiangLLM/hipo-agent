# WebArena rollout divergence probe

Source: runs/wa_shopping_20260724_105245_20260724_105247/events.jsonl

## Is there any contrast to learn from?

- tasks judged: **88**
- all rollouts failed: **39**
- all rollouts succeeded: **32**
- mixed (the only groups with within-task contrast): **17** (19%)

L2 lessons written, by how much contrast the group actually had:

- mixed: **12**
- all-fail (nc=0): **30**

## Can the divergence be localized from the rollouts we already have?

- mixed tasks with a measurable split point: **16/17**
- measured delta in success rate at the split (median): **0.83**
- split depth in steps (median): **2**, min 0, max 4

## Per-task detail

### task 22 — 2/8 genuine
*List out reviewers, if exist, who mention about under water photo*

Split at step **1**, measured delta **1.00**:

- `click` on `/fujifilm-finepix-z200fd-10mp-digital-camera-with-5x-optical-dual-image-stabiliz` — 2 rollouts, success 1.00
- `<END>` on `<END>` — 6 rollouts, success 0.00

winning branch, rollout thought: *Page 1 shows 10 of 12 reviews, and none mention underwater photos. I need inspect page 2 to complete the full review scan.*
  raw action: `click('2067')`

L2 written for this task: none

### task 24 — 7/8 genuine
*List out reviewers, if exist, who mention about price being unfair*

Split at step **1**, measured delta **1.00**:

- `<END>` on `<END>` — 7 rollouts, success 1.00
- `send_msg_to_user(none)` on `/haflinger-men-s-wool-felt-open-back-slippers-beige-550-peat-us-7.html` — 1 rollouts, success 0.00

losing branch, rollout thought: **
  raw action: `send_msg_to_user("None")`

L2 actually written for this task:
- **Inspect all customer reviews and use the exact empty-result marker** (nc=7/8)

### task 143 — 6/8 genuine
*How much I spent on home decoration shopping during 1/29/2023*

Split at step **2**, measured delta **0.29**:

- `click` on `/sales/order/history/?p=2` — 1 rollouts, success 1.00
- `select_option(50)` on `/sales/order/history/?limit=50` — 7 rollouts, success 0.71

winning branch, rollout thought: *The orders are sorted newest first, and page 1 ends at 2/9/23. The requested date 1/29/23 should be on page 2, so I need inspect that page next.*
  raw action: `click('1592')`

losing branch, rollout thought: *The order list has 37 total entries and currently shows only 10. To cover the complete history and locate every order from 1/29/23, I should display all 50 entries on one page.*
  raw action: `select_option('1609', '50')`

L2 actually written for this task:
- **Use full order details and allocate shipping equally** (nc=6/8)

### task 147 — 1/8 genuine
*What is the size configuration of the picture frame I bought 2022*

Split at step **3**, measured delta **0.20**:

- `click` on `/sales/order/view/order_id/184/` — 5 rollouts, success 0.20
- `click` on `/sales/order/view/order_id/154/` — 3 rollouts, success 0.00

winning branch, rollout thought: *The full 2022 history is visible, but the order list does not show product names. I need inspect completed 2022 order details until I find the picture frame and its labeled size; a low-total single-it*
  raw action: `click('1620')`

losing branch, rollout thought: *The full list shows 25 orders from 2022. I need inspect their “Items Ordered” details until I identify the picture frame, then read its labeled size configuration; I’ll start with the latest 2022 orde*
  raw action: `click('1609')`

L2 actually written for this task:
- **Preserve and exhaust full order history** (nc=1/8)

### task 150 — 7/8 genuine
*What is the price configuration of the fake tree I bought Jan 2023*

Split at step **4**, measured delta **1.00**:

- `send_msg_to_user($260.69)` on `/sales/order/view/order_id/148/` — 7 rollouts, success 1.00
- `click` on `/sales/order/history/` — 1 rollouts, success 0.00

winning branch, rollout thought: **
  raw action: `send_msg_to_user("$260.69")`

losing branch, rollout thought: *The January 29 order contains a fake tree, but its visible configurations are only Color and Size, not a configuration labeled “price.” Since the full history showed another January 2023 order, I must*
  raw action: `click('1587')`

L2 actually written for this task:
- **Match the item row before copying its price** (nc=7/8)

### task 164 — 7/8 genuine
*What are the main criticisms of this product? Please extract the relevant sentences.*

Split at step **1**, measured delta **1.00**:

- `send_msg_to_user(those labial never came to me and i would like them again be)` on `/mineralogie-all-natural-lip-gloss-ruby-rose.html` — 7 rollouts, success 1.00
- `send_msg_to_user(uneven color)` on `/mineralogie-all-natural-lip-gloss-ruby-rose.html` — 1 rollouts, success 0.00

winning branch, rollout thought: **
  raw action: `send_msg_to_user("Those labial never came to me and I would like them again because I paid`

losing branch, rollout thought: **
  raw action: `send_msg_to_user("Uneven color")`

L2 actually written for this task:
- **Read the complete Reviews text** (nc=7/8)

### task 226 — 6/8 genuine
*What is the price range for products from Amazon basic?*

Split at step **0**, measured delta **0.29**:

- `fill(amazon basics)` on `/` — 1 rollouts, success 1.00
- `fill(amazon basic)` on `/` — 7 rollouts, success 0.71

winning branch, rollout thought: *I need find the full set of products matching the Amazon Basics brand, then determine the minimum and maximum prices across all result pages. The header search is the broadest suitable starting point.*
  raw action: `fill('372', 'Amazon Basics')`

losing branch, rollout thought: *I need search the full catalog for products matching the Amazon Basics brand, then inspect all result pages and price extremes. The header search is the appropriate broad search tool.*
  raw action: `fill('372', 'Amazon basic')`

L2 actually written for this task:
- **Validate brand before using sorted price endpoints** (nc=6/8)

### task 301 — 7/8 genuine
*Show the most recent processing order*

Split at step **2**, measured delta **1.00**:

- `select_option(50)` on `/sales/order/history/?limit=50` — 7 rollouts, success 1.00
- `<END>` on `<END>` — 1 rollouts, success 0.00

winning branch, rollout thought: *The order history has 37 orders across four pages and is currently sorted from most recent to oldest. I need inspect the complete history for an exact “Processing” status, so I’ll change the per-page *
  raw action: `select_option('1609', '50')`

L2 written for this task: none

### task 302 — 4/8 genuine
*Show the most recent out of delivery order*

Split at step **3**, measured delta **0.67**:

- `click` on `/sales/order/view/order_id/189/` — 6 rollouts, success 0.67
- `click` on `/sales/order/view/order_id/180/` — 2 rollouts, success 0.00

winning branch, rollout thought: *All 37 orders are visible, and none has “Out for Delivery” as the order-level status. The newest potentially active orders are the three “Pending” orders from 5/2/23, so I need to inspect their detail*
  raw action: `click('1488')`

losing branch, rollout thought: *The complete 37-order list has no order-level “Out for Delivery” status, so this likely appears in shipment/tracking details within completed orders. I should inspect completed orders from newest to o*
  raw action: `click('1521')`

L2 actually written for this task:
- **Treat the complete order-status grid as authoritative** (nc=4/8)

### task 329 — 1/8 genuine
*How much I spend on 4/19/2023 on shopping at One Stop Market?*

Split at step **3**, measured delta **1.00**:

- `click` on `/customer/account/` — 1 rollouts, success 1.00
- `send_msg_to_user($0.00)` on `/sales/order/history/?limit=50` — 6 rollouts, success 0.00
- `click` on `/customer/account/edit/` — 1 rollouts, success 0.00

winning branch, rollout thought: *The complete 37-order list contains no order dated 4/19/2023, so the spending amount may be shown elsewhere in the account dashboard rather than the order-history table. I should inspect the main acco*
  raw action: `click('1899')`

losing branch, rollout thought: *The complete 37-order history is visible, and there are no orders dated 4/19/23, so the amount spent that day was zero.*
  raw action: `send_msg_to_user("$0.00")`

L2 actually written for this task:
- **Verify complete order history before totaling** (nc=1/8)

### task 335 — 7/8 genuine
*Tell me when I last ordered my body butter?*

Split at step **4**, measured delta **0.50**:

- `go_back` on `/sales/order/history/?limit=50` — 6 rollouts, success 1.00
- `click` on `/sales/order/history/` — 2 rollouts, success 0.50

winning branch, rollout thought: *Order #000000170 dated May 17, 2023 does not contain body butter. I need to return to the full order list and inspect the next-newest order.*
  raw action: `go_back()`

losing branch, rollout thought: *Order #000000170 dated May 17, 2023 does not contain body butter. I need to return to the full order list and inspect the next-newest order, continuing downward until I find the first body butter.*
  raw action: `click('1605')`

L2 actually written for this task:
- **Verify the latest matching order** (nc=7/8)

### task 336 — 2/8 genuine
*Tell me when I last ordered my conditioner?*

Split at step **4**, measured delta **1.00**:

- `go_back` on `/sales/order/history/?limit=50` — 2 rollouts, success 1.00
- `click` on `/sales/order/history/` — 6 rollouts, success 0.00

winning branch, rollout thought: *Order #000000170 dated May 17, 2023 does not contain conditioner. I need return to the full order list and inspect the next-newest order.*
  raw action: `go_back()`

losing branch, rollout thought: *Order #000000170 dated May 17, 2023 contains no conditioner, so I must return to the complete order history and inspect the next-newest order, reapplying the Show 50 control if needed.*
  raw action: `click('1605')`

L2 actually written for this task:
- **Complete newest-to-oldest order-detail scan** (nc=2/8)

### task 362 — 6/8 genuine
*Show me the billing address for order number 00178.*

Split at step **2**, measured delta **0.29**:

- `click` on `/sales/order/history/?p=2` — 1 rollouts, success 1.00
- `select_option(50)` on `/sales/order/history/?limit=50` — 7 rollouts, success 0.71

winning branch, rollout thought: *Order 00178 is not among the first 10 orders, and there are 37 total. I need to continue through the order history, starting with page 2.*
  raw action: `click('1592')`

losing branch, rollout thought: *The order history has 37 total orders and can display 50 per page, so showing all orders at once is the safest way to locate order 00178 without missing it.*
  raw action: `select_option('1609', '50')`

L2 actually written for this task:
- **Open the exact order and transcribe the full labeled address** (nc=6/8)

### task 368 — 3/8 genuine
*find discounted items.*

Split at step **0**, measured delta **0.50**:

- `click` on `/?pbaocw=2` — 6 rollouts, success 0.50
- `send_msg_to_user(pre-baked gingerbread house kit value pack, 17 oz., pack of )` on `/` — 1 rollouts, success 0.00
- `send_msg_to_user(i’m sorry, but i couldn’t complete the search.)` on `/` — 1 rollouts, success 0.00

winning branch, rollout thought: *The showcase contains 24 items across two pages, so I must inspect page 2 before identifying all discounted items.*
  raw action: `click('1930')`

losing branch, rollout thought: **
  raw action: `send_msg_to_user("Pre-baked Gingerbread House Kit Value Pack, 17 oz., Pack of 2, Total 34 `

L2 actually written for this task:
- **Verify explicit discounts across the full catalog** (nc=3/5)

### task 796 — 3/8 genuine
*Change the delivery address for my most recent order to 155 5th Street, San Francisco, CA.*

Split at step **1**, measured delta **0.83**:

- `click` on `/sales/order/view/order_id/190/` — 2 rollouts, success 1.00
- `<END>` on `<END>` — 6 rollouts, success 0.17

winning branch, rollout thought: *The most recent order is #000000190 dated 7/24/26 and currently Pending. I’ll open its order details to find the delivery-address editing option.*
  raw action: `click('1499')`

L2 written for this task: none

### task 798 — 4/8 genuine
*Change the delivery address for my most recent order to 77 Massachusetts Ave, Cambridge, MA.*

Split at step **1**, measured delta **0.80**:

- `click` on `/sales/order/view/order_id/190/` — 5 rollouts, success 0.80
- `<END>` on `<END>` — 3 rollouts, success 0.00

winning branch, rollout thought: *The most recent order is #000000190 dated 7/24/26 and is pending. I’ll open its details to find the delivery-address editing option.*
  raw action: `click('1499')`

L2 written for this task: none

## Mixed tasks with no measurable split

- task 166 (7/8): What are the main criticisms of this product? Please extract the relevant sentences.
