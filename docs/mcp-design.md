# LectureThread MCP 第一版設計

狀態：第一版已依本規格實作並在本機驗收（2026-10-30）；安裝、設定與工具介面以 [MCP server 操作文件](mcp.md) 為準。本文保留原設計，並在文末列出最終實作的差異。相關取捨見 [ADR 0004](architecture/adr/0004-read-only-course-mcp.md)。

## 目標與範圍

讓 AI 助理查詢已登錄的課程，取得可追溯到逐字稿與畫面出現區間的資料，再回答使用者問題。既有閱讀器和課程處理流程保持原樣。

第一版提供四個唯讀 Tools，使用官方 Python MCP SDK 與本機 stdio。沒有 ASR、OCR、文字模型推論、網路服務、資料修改、發布或任意 shell 工具。搜尋採確定性文字比對，暫不加入 embeddings、向量資料庫或自動摘要。Resources、Prompts、圖片傳送與任務啟動留待後續。

官方依據：[server concepts](https://modelcontextprotocol.io/docs/learn/server-concepts)、[Python SDK](https://github.com/modelcontextprotocol/python-sdk)。實作時選擇與展示 client 相容的 SDK 穩定版本並固定依賴，記錄實測版本，不直接追隨 main 或假設最新協定已被 client 支援。

## 分層與檔案配置（建議新增）

- `lecture_mcp_server.py`：SDK 註冊、參數驗證、錯誤與回傳格式轉接；所有日誌走 stderr，stdout 只供協定使用。
- `course_query.py`：純查詢邏輯、來源驗證、快照、搜尋與 occurrence 查詢；可不透過 MCP 測試。
- `mcp.courses.example.json`：僅列 `courses/demo.json` 的可公開登錄範例。
- 本機設定 `mcp.courses.local.json`：實作時新增精確 ignore 規則；登錄使用者允許查詢的課程，不能自動掃描所有 output/jobs。
- `requirements-mcp.txt`：固定 SDK 與必要相依；不得引入 GPU、OCR 或 ASR。先驗證與現有 constraints 相容，再決定 CI 安裝方式。
- `tests/test_course_query.py`、`tests/test_mcp_protocol.py`：邏輯測試與真實 stdio client/server 測試。
- `docs/mcp.md`：實作後的安裝、client 設定、限制與展示步驟。

server 直接使用專案 `.venv` 啟動，不依賴 vendor 的工作目錄，不用 `run.py` 啟動這個無模型服務。相對設定路徑相對 registry 所在目錄解析；程式本身不可依賴 client 的 cwd。

## 課程登錄與檔案邊界

建議設定格式：`{"schema":1,"courses":[{"manifest":"courses/demo.json"}]}`。課程 ID 取自 manifest，不額外維護另一份映射；重複 ID 啟動失敗。登錄設定由本機使用者編輯，工具參數只接受 course_id、來源 ID、頁碼與查詢字串，不接受路徑或網址。

沿用 `load_course` 解析 manifest，但要另外對實際讀取的固定資料檔做 resolved path containment 檢查（含 symlink／junction）。只讀課程目錄內允許的檔案；不回傳絕對路徑、環境變數或 traceback。第一版不讀圖片 bytes、影片或任意 image 路徑。

核准範圍固定為啟動時解析的課程目錄與 web root，並保存既有課程目錄的檔案系統身分。每次快照讀取前後都重新核對，拒絕目錄或上層路徑被 junction 替換；不能以替換後重新 resolve 的位置建立新邊界。有意更換整個目錄時須重新啟動 server。

預設只登錄原創 demo。接雲端 AI 時，工具回傳內容可能送到該服務；本機 server 不等於資料完全留在本機。教材文字是資料，不能當成執行指令。

## 資料層與快照

- `raw_transcript`：`transcript.json`，source_id 是原始陣列的零起算索引；原創 demo 必須標明是預寫腳本，不是假裝 ASR。
- `corrected_transcript`：`transcript.corrected.json`；驗證段數與時間和 raw 一致。缺檔就回報該層不可用，禁止偷偷退回 raw。
- `editorial_notes`：有效的 `editorial_chapters.json`，沿用 `validate_editorial` 與 raw hash 驗證；paragraph 的 source_ids 是引用來源，不表示整理內容等於原話。舊 demo 的 `authored_notes.json` 無同一契約，第一版不偽造 source_ids，回報此層不支援。
- `slide_evidence.json`：保留每次 occurrence，不依相同頁碼去重。頁碼缺少時回傳 null；不能由圖片檔名猜測 PDF 頁碼。
- 人工修訂與閱讀稿第一版不合併進上述資料。存在 `transcript.manual-edits.json` 時回傳明確 warning：`manual_edits_not_applied`，避免把 corrected 稱為使用者最新定稿。

每個課程查詢回傳 `revision`：由 manifest 與相關固定資料檔的 bytes hash（缺檔亦納入）、契約版本產生。每次請求建立一致快照；讀取前後 hash 不一致則限次重試，仍變動回 `COURSE_BUSY`。跨工具請求可帶 `expected_revision`，不一致回 `STALE_REVISION`，不得在不同版本間重用 source_id。不得只用 mtime 判斷內容未變。

## 四個工具契約

以下是設計上的函式參數，不是已實作的呼叫指令。所有工具標示唯讀；真正的唯讀限制由程式實作，不依賴註記。

| 工具 | 參數 | 結果 |
|---|---|---|
| `list_courses` | `offset=0, limit=20`（最大 50） | id、title、各資料層 availability、資料來源性質、manual edits warning；不回傳內文或私人路徑 |
| `search_course` | `course_id, query, layer="corrected_transcript", limit=5`（1–20）、`expected_revision?, cursor?` | revision、命中片段、source_ids、時間、匹配方式、結果截斷狀態 |
| `get_source_context` | `course_id, source_ids, before=1, after=1, expected_revision?` | 每個來源的 raw／corrected 文字、時間、與它有時間重疊的 occurrence metadata；缺少 corrected 時明確為 null |
| `get_slide_occurrences` | `course_id, page_id?, offset=0, limit=20, expected_revision?` | occurrence_id、page_id、start/end、變化類型、時間精度；保留重訪與註記變更，並回傳 next_offset |

`get_source_context` 的 ID 數量 1–10、不接受 bool、負值與不存在 ID；before/after 各 0–2。`get_slide_occurrences` limit 最大 50，沒有 page_id 時可列出所有出現紀錄，指定的頁碼找不到時回空陣列。

搜尋 query 去頭尾空白後長度 1–200 字；NFKC + casefold 後做字面子字串搜尋，不接受 regex、不自動擴詞。回傳原文而非正規化文字，依時間與來源 ID 穩定排序。中文可直接搜「佇列」；AI 可用多次不同字詞查詢，但 server 不宣稱語意搜尋。notes 以段落為單位搜尋，來源時間由引用的 transcript 取得，另外保留段落的 editorial time。

每次回應設定 64 KiB UTF-8 上限。長文字提供有長度限制的 excerpt 與 `truncated=true`；結果頁截斷時提供 continuation，continuation 必須綁定 revision 與查詢條件。不靜默丟棄 requested source IDs：context 無法完整容納時回 `RESULT_TOO_LARGE`，要求減少 ID／上下文。空搜尋結果是正常成功，並非系統錯誤。

大小計算對象為完整 `CallToolResult` 的 UTF-8 JSON：包含文字與 structured content 兩份內容、跳脫字元及 SDK 結果欄位，不包含外層 JSON-RPC framing。查詢層依此預算縮短分頁；adapter 再驗證 SDK 實際序列化大小，超限的成功結果或業務錯誤都改回精簡錯誤。測試以真正 stdio client 驗證長中文分頁無遺漏、context 超限與縮小請求後成功，並比對查詢層估算與 SDK 序列化大小。

## 回應與錯誤

使用 MCP SDK 支援的結構化結果，並提供一致的 JSON 文字表示以便 client 展示；不可只回自然語言答案。頂層包含 `schema_version=1`、`course_id`（適用時）、`revision`、`data`、`warnings`。內容項目清楚區分 layer、source_ids、原始來源時間與整理內容。

錯誤至少包含：`COURSE_NOT_ALLOWED`、`LAYER_UNAVAILABLE`、`INVALID_ARGUMENT`、`SOURCE_NOT_FOUND`、`INVALID_COURSE_DATA`、`STALE_REVISION`、`COURSE_BUSY`、`RESULT_TOO_LARGE`。業務錯誤使用 SDK 對應的工具錯誤回應，不把錯誤當成搜尋零結果；schema／協定錯誤交由 SDK。錯誤不包含內部絕對路徑或課程全文。

第一版回傳 source_ids、occurrence_ids 與時間即可，不宣稱 AI 已看過圖片或聽過音訊。不生成現有 reader 尚不支援的 `?t=` 深連結，也不自動啟動 HTTP reader。展示時另手動開既有閱讀器核對時間。

## 測試與完成標準

1. 以 tracked demo 產生器和小型 synthetic JSON fixture 驗證，不依賴私人課程、vendor、GPU 或模型。demo 無 notes/page_id 也是必要案例。
2. 測試搜尋中英文、空結果、上限、錯誤資料層、ID 邊界、raw/corrected 對應、失效 notes hash、人工修訂 warning。
3. 回頁與新增註記須是不同 occurrence；來源跨兩個畫面時全部回傳，不只挑第一張。
4. 課程未登錄、路徑逃逸（含 Windows junction／symlink 適用案例）、檔案中途變動、舊 revision 與回應截斷都要驗證。
5. 所有查詢前後比較課程檔案 hash，確定沒有寫檔、lock 檔或自動建置副作用。不要直接調用會建立鎖檔的修訂方法。
6. 用官方 SDK 的真實 client 啟動 stdio server，依選定 SDK 完成連線／工具列舉／四個工具呼叫／錯誤回應／關閉程序；stdout 不含日誌。只測 Python 函式不算 MCP 驗收。
7. Windows CI 加入以上無模型驗證，保留原有 Python／Node 測試與 demo 建置。
8. 另外以選定的 AI host 實際連接，記錄 host、SDK 版本與一次呼叫鏈。CI client 通過和 AI host 展示成功分開報告。

## 實作順序與作業展示

先完成 registry、快照與純查詢；再接 SDK／stdio；最後加入 CI 和一個 AI host 的連接說明。安裝／啟動命令與 host 設定範例在選定版本並測過後才寫成可直接使用的指令。暫不改使用者全域設定或自動登錄私人課程。

第一條展示用無模型原創 stack/queue demo：列課程 → 搜尋 queue 原句 → 取得上下文與全部重訪畫面，讓 AI 引用 source_id 與時間回答。第二條可選用本機 circular-queue 成果：搜講義中的滿條件 → 讀原始／校訂來源 → 核對回頁紀錄。沒有該成果時不可複製 reference-run hash 偽造可用資料。

作業證據保存工具清單、實際請求／回傳、附來源的 AI 回答、測試與 CI 連結。原創公開 fixture 可供重現；私人課程與生成媒體不提交。完整影片處理、圖片工具、人工修訂寫入與遠端 HTTP 是後續範圍，另行設計。

## 最終實作與原設計的差異（2026-10-30）

實作檔案即上方建議的配置，另加 `examples/mcp/record_demo.py`（以真實 SDK client 執行展示並產生紀錄，也供 CI 煙霧測試）。以下是設計未寫明、實作時決定的部分：

- **SDK**：`mcp==2.3.0`。它支援 initialize 握手 `2024-11-05`～`2025-11-25` 與 `2026-07-28` 無狀態協定；Claude Code 2.1.303 及 SDK `ClientSession` 實測協商到 `2025-11-25`，SDK 高階 `Client` 的自動模式也有測試。`requirements-mcp.txt` 固定 SDK 及全部間接依賴，`requirements-dev.txt` 引入它。
- **registry 欄位**：每筆另有選填的 `raw_transcript_origin`（`asr`／`scripted`／`unknown`，預設 `unknown`）。manifest 沒有機器可讀的逐字稿性質欄位，從 description 文字猜測又不可靠，所以由登錄者明確聲明。registry 出現未知欄位時拒絕啟動。
- **人工修訂 warning**：`transcript.manual-edits.json` 有修訂內容或無法解析時才回 `manual_edits_not_applied`（附 `pending_edits`）；空的修訂清單沒有待套用內容，不提示。
- **回應格式**：頂層多一個 `notice`，提醒課程文字是資料、不是指令。工具直接回傳 `CallToolResult`（結構化內容加相同的 JSON 文字），因此 tools/list 不宣告 output schema；成功與錯誤的結構不同，宣告單一 schema 會讓錯誤結果不符合它。
- **錯誤**：另增 `INTERNAL_ERROR`，只用於未預期的程式錯誤，細節只寫 stderr。參數型別錯誤（例如布林值當 ID）先由 SDK 的 pydantic strict 驗證以 `isError=true` 回傳，純查詢層也再驗證一次。
- **revision 的檔案集合**：manifest 加上 `transcript.json`、`transcript.corrected.json`、`editorial_chapters.json`、`slide_evidence.json`、`transcript.manual-edits.json`、`authored_notes.json`。每次請求讀兩次並比對 bytes，最多 3 輪。manifest 在 server 啟動後被改動時回 `INVALID_COURSE_DATA`，要求重新啟動，不在執行中切換到另一份課程設定。
- **大小**：搜尋 excerpt 600 字、上下文每句 4000 字、單檔讀取上限 64 MiB。分頁結果超過 64 KiB 時縮短該頁並回 `page_shortened_for_size` warning 與 continuation。
- **其餘欄位**：`get_source_context` 另回傳引用該來源的講義段落（`cited_by_notes`）；`get_slide_occurrences` 另回傳每次出現時間重疊的 `overlapping_source_ids`，但不回傳圖片檔名、`deck_text_layer` 或 OCR 線索。
- **路徑邊界**：固定檔名逐一 resolve（含 symlink／junction），解析結果必須仍是課程資料夾內的同名一般檔案。hard link 無法從路徑辨識，列為已知限制。
- **尚未驗證**：GitHub Actions 尚未實際執行新的 CI 步驟（變更未推送）。
