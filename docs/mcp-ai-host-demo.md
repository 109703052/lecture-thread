# MCP 展示紀錄：AI host 實際連接

> 以 Claude Code CLI 的 headless 模式（`claude -p`）作為 AI host，透過暫時的 `--mcp-config` 檔案與 `--strict-mcp-config` 載入 LectureThread MCP server；未修改任何全域或專案 MCP 設定，並以 `--tools ""` 關閉內建工具、`--no-session-persistence` 不保存對話。資料為原創公開示範課程。以下工具呼叫與回答取自該次 `stream-json` 輸出；回應只列摘要，完整回應格式見 [SDK client 展示紀錄](mcp-demo-record.md)。

- 日期：2026-10-30
- AI host：Claude Code 2.1.303（headless，stdio）；MCP 連線狀態：connected
- host 取得的工具：`mcp__lecturethread__get_slide_occurrences`, `mcp__lecturethread__get_source_context`, `mcp__lecturethread__list_courses`, `mcp__lecturethread__search_course`
- server：`lecture_mcp_server.py`（mcp 2.3.0）；registry：`mcp.courses.example.json`
- 結果：success，7 個 turn

## 使用者提問

> 請只使用 lecturethread MCP 工具回答：在已登錄的堆疊與佇列示範課程中，queue 的出入規則是什麼？它和 stack 有什麼差別？課程後段回到 stack 示意圖時補充了什麼？請依序 list_courses → search_course → get_source_context → get_slide_occurrences，回答時每個論點附 source_id 與時間（秒），並明確分成「來源內容」與「補充推論」兩段；注意逐字稿性質。

## 工具呼叫鏈

| # | 工具 | 參數 | 回應摘要 |
|---|---|---|---|
| 1 | `list_courses` | `{}` | courses: lecturethread-demo（scripted，ok） |
| 2 | `search_course` | `{"course_id": "lecturethread-demo", "query": "queue", "expected_revision": "r1-d4d03e189b1eebc206661ada23dd33e6", "limit": 10}` | total_matches=2；source_ids=[2, 3] |
| 3 | `search_course` | `{"course_id": "lecturethread-demo", "query": "佇列", "expected_revision": "r1-d4d03e189b1eebc206661ada23dd33e6", "limit": 10}` | total_matches=0；source_ids=[] |
| 4 | `search_course` | `{"course_id": "lecturethread-demo", "query": "stack", "expected_revision": "r1-d4d03e189b1eebc206661ada23dd33e6", "limit": 10}` | total_matches=4；source_ids=[0, 1, 3, 4] |
| 5 | `get_source_context` | `{"course_id": "lecturethread-demo", "source_ids": [2, 3, 4], "expected_revision": "r1-d4d03e189b1eebc206661ada23dd33e6", "before": 1, "after": 1}` | source 2（12–18 秒）→ occurrences [2]；source 3（18–24 秒）→ occurrences [2]；source 4（24–30 秒）→ occurrences [3] |
| 6 | `get_slide_occurrences` | `{"course_id": "lecturethread-demo", "expected_revision": "r1-d4d03e189b1eebc206661ada23dd33e6"}` | occurrence 1（0–12 秒，page_id=None）；occurrence 2（12–24 秒，page_id=None）；occurrence 3（24–36 秒，page_id=None）；warnings=['page_id_unavailable'] |

## AI host 的回答（原文）

我依序呼叫了 list_courses → search_course → get_source_context → get_slide_occurrences。課程是 `lecturethread-demo`（堆疊與佇列｜公開示範課程），revision 為 `r1-d4d03e189b1eebc206661ada23dd33e6`。

**逐字稿性質：** 這門課的原始逐字稿標註為 `scripted`，也就是事先寫好的教學腳本，不是語音辨識結果。我查到的段落中，`raw_text` 和 `corrected_text` 一字不差。下面的引用代表腳本內容，不代表實際口說。

## 一、來源內容

**1. Queue 的出入規則**
- Queue 用排隊來比喻。enqueue 把新元素加到尾端，dequeue 從前端移除。〔source_id 2，12–18 秒〕
- 兩種操作用的是不同端點，所以最早到的 A 最先離開，形成先進先出（FIFO）的順序。〔source_id 2，12–18 秒〕

**2. 和 stack 的差別**
- Stack 的 push 和 pop 都在同一端（頂端）進行，這個限制產生後進先出（LIFO）的順序。最後放入的 C 會最先取出。〔source_id 0，0–6 秒〕
- 依序 push(A)、push(B)、push(C)，再 pop 三次，會得到 C、B、A。〔source_id 1，6–12 秒〕
- 同樣輸入 A、B、C 再全部移除：stack 輸出 C、B、A，queue 輸出 A、B、C。用相同輸入比較，可以單獨看出資料結構對順序的影響。〔source_id 3，18–24 秒〕
- 每次操作的成本仍取決於實作方式，例如陣列、環狀緩衝區或鏈結串列。〔source_id 3，18–24 秒〕
- 重點在操作的先後關係，和元素在記憶體中是否連續存放無關。空的 stack 不能再 pop，要由介面定義錯誤或空值行為。〔source_id 1，6–12 秒〕

**3. 後段回到 stack 示意圖時補充了什麼**
- 回到 stack 示意圖時，新增了「只移動頂端指標」的註記。主題和第一頁相同，但這次補上了實作觀點。〔source_id 4，24–30 秒〕
- LIFO 是元素進出的規則，常數時間是特定實作下的操作成本，兩者不同。〔source_id 5，30–36 秒〕
- 如果用容量固定且還沒滿的陣列，push 可以直接寫入頂端並更新索引。但可擴充陣列在容量不足時可能要搬移資料，所以不能說每次 push 在最壞情況下都是常數時間。〔source_id 5，30–36 秒〕

**投影片出現區間（get_slide_occurrences）**
- occurrence 1：0–12 秒，涵蓋 source 0、1
- occurrence 2：12–24 秒，涵蓋 source 2、3
- occurrence 3：24–36 秒，涵蓋 source 4、5

三筆紀錄的 `page_id`、`title`、`visual_change` 都是 null，工具也回報了 `page_id_unavailable` 警告。

## 二、補充推論（不是來源原文）

- **「回頁」只有逐字稿這一個依據。** occurrence 3（24–36 秒）是後段的 stack 示意圖，這點來自 source 4 的文字。投影片資料沒有頁碼、標題或畫面變化欄位，工具也看不到圖像，所以無法從畫面確認它和 occurrence 1 是同一張圖。
- **Queue 該用哪種實作。** 來源提到環狀緩衝區（source 3），推測它適合 queue：兩端都有指標，可以避免 dequeue 時搬移元素。這是我的推論，課程沒有明說。
- **「只移動頂端指標」的含意。** 我理解為 pop 不必清除或搬動資料，只要調整頂端索引。這和 source 5 的固定容量陣列例子一致，但「pop 不清除資料」這一點來源沒有說。
- **檢索限制。** 用中文「佇列」搜尋沒有結果，課程內文一律用英文「queue」。搜尋是字面比對，不是語意搜尋，所以不排除還有其他用詞不同的相關段落。不過整門課只有 6 段（source 0–5），我已經看過全部內容。

## 核對

- 回答中的 source_id 與秒數已逐項對照上方工具回應及 `examples/demo/transcript.json`：source 0–5 依序為 0–6、6–12、12–18、18–24、24–30、30–36 秒，與回答一致。
- 回答標明原始逐字稿是 `scripted` 預寫腳本，並指出 page_id 為 null、工具看不到圖像，所以「回頁」只以逐字稿為依據；這與 server 的實際限制相符。
- 「補充推論」段落是模型的推論，不是課程來源。
- 這是一次實際執行的結果；模型回答每次可能不同，不作為自動化測試的基準。
