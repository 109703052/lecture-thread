# 課程查詢 MCP server

LectureThread 提供一個本機、唯讀的 [MCP](https://modelcontextprotocol.io/)（Model Context Protocol：讓 AI 助理以標準格式呼叫外部工具的協定）server。AI 助理可以用它查詢已登錄課程的逐字稿、講義段落、來源時間與投影片出現紀錄，再根據這些證據回答問題。設計取捨見 [MCP 設計](mcp-design.md) 與 [ADR 0004](architecture/adr/0004-read-only-course-mcp.md)。

## 能做什麼、不能做什麼

| 提供 | 不提供 |
|---|---|
| 4 個唯讀工具：列課程、在單一資料層搜尋、讀取來源上下文、列投影片出現紀錄 | 修改逐字稿、講義、核對決定或發布；Resources、Prompts |
| 來源 ID（`source_id`，原始 `transcript.json` 的零起算索引）、時間、資料層與 `revision` | 圖片、音訊或影片內容；server 沒有看圖或聽音的能力 |
| 字面搜尋：NFKC 正規化與大小寫折疊後做子字串比對 | 語意搜尋、自動擴詞、embeddings、向量資料庫 |
| 本機 stdio（標準輸入／輸出）連線 | 遠端 HTTP、帳號、ASR／OCR／VLM 或文字模型推論、長時間任務、shell 或任意檔案讀取 |

只讀 registry（課程登錄檔）明確列出的課程，不掃描 `output/` 或 `output/jobs/`。工具參數只接受課程 ID、來源 ID、頁碼與查詢字串，不接受路徑或網址。

**使用雲端 AI 時請注意：** server 在本機執行，但工具回傳的課程片段會交給你使用的 AI host，若 host 使用雲端模型，這些片段就會送到該服務。只登錄你願意送出的課程。

## 三種內容來源要分清楚

| 資料層 | 檔案 | 意義 |
|---|---|---|
| `raw_transcript` | `transcript.json` | 原始逐字稿。`raw_transcript_origin` 說明它是語音辨識（`asr`）、預寫腳本（`scripted`，例如公開示範）或未聲明（`unknown`） |
| `corrected_transcript` | `transcript.corrected.json` | 校訂後的顯示用逐字稿；段數與每段時間必須和原始逐字稿完全一致，否則標為 `invalid` |
| `editorial_notes` | `editorial_chapters.json` | 由 AI 助理直接撰寫、經來源與 hash 驗證的講義段落。段落的 `source_ids` 是引用來源，不代表講義等於原話 |

- 缺少某層時明確回報 `missing`、`unsupported` 或 `invalid`，不會改用其他層代替。舊示範只有 `authored_notes.json`，沒有 `source_ids` 契約，所以 `editorial_notes` 是 `unsupported`。
- 人工修訂（`transcript.manual-edits.json`）與閱讀稿第一版不合併。人工修訂有內容時，回應附 `manual_edits_not_applied` 警告，表示 `corrected_transcript` 不是使用者最新定稿。
- AI host 根據這些證據寫出的回答屬於模型生成內容。請要求它引用 `source_id` 與時間，並把來源內容和自己的推論分開。

## 安裝

已驗證環境：Windows 11 x64、PowerShell、專案內 uv 0.13.3 管理的 Python 3.12.15、官方 Python MCP SDK `mcp==2.3.0`（`mcp-types==2.3.0`）。SDK 2.3.0 支援 initialize 握手協定 `2024-11-05`～`2025-11-25`，以及 `2026-07-28` 的無狀態協定；實測 Claude Code 2.1.303 與 SDK 自己的 `ClientSession` 都協商到 `2025-11-25`。

`requirements-mcp.txt` 固定 SDK 及全部間接依賴，並以 `requirements.lock.txt` 為 constraint；不含 GPU、ASR、OCR 或模型套件。`requirements-dev.txt` 已經包含它，因此依 [開發與測試](development.md) 建立環境後即可使用。只想安裝 MCP 所需套件時，在專案根目錄執行：

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD 'tools/uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD 'tools/python'
$env:UV_PYTHON_BIN_DIR = Join-Path $PWD 'tools/python-bin'
$env:UV_TOOL_DIR = Join-Path $PWD 'tools/uv-tools'
.\tools\uv\uv.exe pip install --python .venv/Scripts/python.exe -r requirements-mcp.txt
```

公開示範課程的資料由 `examples/demo/create_demo.py` 產生到 `output/demo/`，第一次使用前先執行一次：

```powershell
.\.venv\Scripts\python.exe examples/demo/create_demo.py
```

## 課程登錄

公開範例 [`mcp.courses.example.json`](../mcp.courses.example.json) 只登錄原創示範：

```json
{
  "schema": 1,
  "courses": [
    {"manifest": "courses/demo.json", "raw_transcript_origin": "scripted"}
  ]
}
```

- `manifest`：既有的[課程設定](courses.md)檔。相對路徑以 registry 檔所在的資料夾為基準，不受 client 工作目錄影響。課程 ID 取自 manifest，重複 ID 會讓 server 拒絕啟動。
- `raw_transcript_origin`：`asr`、`scripted` 或 `unknown`（預設）。如實填寫，回應會據此標示原始逐字稿的性質。
- 私人課程請寫在專案根目錄的 `mcp.courses.local.json`。它被 `.gitignore` 精確忽略，不會提交。例如加入本機的原創循環佇列成果：

```json
{
  "schema": 1,
  "courses": [
    {"manifest": "courses/demo.json", "raw_transcript_origin": "scripted"},
    {"manifest": "output/jobs/e2e-circular-queue/course.reader.json", "raw_transcript_origin": "asr"}
  ]
}
```

registry 或任何 manifest 有錯時，server 會在 stderr 印出原因並以代碼 2 結束，不會只載入部分課程。server 只讀課程資料夾中的固定檔案：`transcript.json`、`transcript.corrected.json`、`editorial_chapters.json`、`slide_evidence.json`、`transcript.manual-edits.json`、`authored_notes.json`。每次讀取都檢查解析後的實際路徑（含 symlink 與 Windows junction）仍在課程資料夾內，否則回 `INVALID_COURSE_DATA`。

啟動時會固定核准的課程目錄、web root 與既有課程目錄的檔案系統身分。讀取前後都會核對；即使整個課程目錄或上層 web root 被換成 junction，也不會把新位置當成核准範圍。正常更新目錄內的 JSON 檔案不受影響；若有意替換整個課程目錄，請確認 registry 與 manifest 指向預期位置，再重新啟動 server。還原原本目錄後可繼續查詢。

## 啟動與驗證（Windows PowerShell）

server 透過 stdio 和 AI host 溝通，通常由 host 自動啟動。請一律用**絕對路徑**指定 Python、server 與 registry，例如專案在 `C:\path\to\lecture-thread` 時：

```powershell
C:\path\to\lecture-thread\.venv\Scripts\python.exe C:\path\to\lecture-thread\lecture_mcp_server.py --registry C:\path\to\lecture-thread\mcp.courses.example.json
```

直接在終端機執行時，server 會等待 JSON-RPC 訊息，看起來像沒有反應；這是正常的。關閉 stdin（client 斷線）時 server 會自行結束，這點有自動測試；手動執行時可按 Ctrl+C 中止（未納入自動測試）。`--registry` 若給相對路徑，以專案資料夾為基準。

用官方 SDK 的真實 client 驗證四個工具（不需要 AI host，也不寫任何檔案）：

```powershell
.\.venv\Scripts\python.exe examples/mcp/record_demo.py --registry mcp.courses.example.json --check
```

要重新產生公開展示紀錄 [mcp-demo-record.md](mcp-demo-record.md)，把 `--check` 換成 `--out docs/mcp-demo-record.md`。協定與查詢測試：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_course_query.py tests/test_mcp_protocol.py -p no:cacheprovider -rs
```

## 連接 AI host（以 Claude Code 為例）

以下設定已實測可用（見 [AI host 展示紀錄](mcp-ai-host-demo.md)）。專案不會自動修改你的全域或專案 MCP 設定；請依需要自行加入。

建立一個 JSON 檔，例如 `lecturethread.mcp.json`（放在你自己的資料夾，路徑換成實際位置）：

```json
{
  "mcpServers": {
    "lecturethread": {
      "type": "stdio",
      "command": "C:\\path\\to\\lecture-thread\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\path\\to\\lecture-thread\\lecture_mcp_server.py",
        "--registry",
        "C:\\path\\to\\lecture-thread\\mcp.courses.example.json"
      ]
    }
  }
}
```

只在一次執行中載入、不改任何設定：

```powershell
claude -p "列出已登錄課程，搜尋 queue，並附 source_id 與時間說明它的規則" --mcp-config .\lecturethread.mcp.json --strict-mcp-config --allowedTools "mcp__lecturethread__list_courses mcp__lecturethread__search_course mcp__lecturethread__get_source_context mcp__lecturethread__get_slide_occurrences"
```

要長期使用，可把同一段 `mcpServers` 內容自行加入 Claude Code 的 MCP 設定（例如專案根目錄的 `.mcp.json`）；這種常駐設定方式本專案尚未實測。其他支援 stdio 的 host 也使用相同的 command 與 args，同樣未逐一驗證。

## 四個工具

所有工具都標示 `readOnlyHint=true`；實際的唯讀限制由程式保證。成功回應的頂層欄位是 `schema_version`、`course_id`（適用時）、`revision`、`notice`、`data`、`warnings`，同時以 MCP 結構化結果（`structuredContent`）與相同內容的 JSON 文字回傳。完整的實際回應見 [mcp-demo-record.md](mcp-demo-record.md)。

| 工具 | 參數 | 主要回傳 |
|---|---|---|
| `list_courses` | `offset=0`、`limit=20`（1–50） | 每門課的 `id`、標題、說明、`raw_transcript_origin`、`revision`、各資料層狀態、警告；`next_offset`。不回傳內文或路徑 |
| `search_course` | `course_id`、`query`（去頭尾空白後 1–200 字）、`layer="corrected_transcript"`、`limit=5`（1–20）、`expected_revision?`、`cursor?` | 命中項目（逐字稿：`source_id`、`start`、`end`、原文 `text`；講義：章節與段落、`source_ids`、`source_time`、`editorial_time`）、`total_matches`、`has_more`、`next_cursor` |
| `get_source_context` | `course_id`、`source_ids`（1–10 個不重複非負整數）、`before=1`、`after=1`（各 0–2）、`expected_revision?` | 每個來源的 `raw_text`、`corrected_text`（該層不可用時為 null）、時間、前後句、所有時間重疊的投影片出現紀錄、引用它的講義段落 |
| `get_slide_occurrences` | `course_id`、`page_id?`、`offset=0`、`limit=20`（1–50）、`expected_revision?` | 依時間排序的每次出現：`occurrence_id`、`page_id`（沒有 PDF 頁碼時為 null）、`title`、`start`、`end`、`visual_change`、`visual_change_meaning`、`timing_precision`、`overlapping_source_ids`；`next_offset` |

規則：

- **回頁與註記變化不合併**：同一頁每次出現都是獨立紀錄，不依 `page_id` 去重。
- **revision**：由契約版本、manifest 與上述固定檔案的內容 hash 計算（缺檔也納入），不使用修改時間。每次請求會讀兩次並比對，內容不一致就重試，連續變動回 `COURSE_BUSY`。後續請求帶 `expected_revision`，課程已變更時回 `STALE_REVISION`，避免在不同版本之間沿用 `source_id`。
- **大小上限**：每個工具結果 `CallToolResult` 最多 64 KiB（UTF-8 JSON），包含 `content` 文字、`structuredContent`、JSON 跳脫與 SDK 結果欄位；不包含外層 JSON-RPC 的 request ID 或 framing。搜尋結果的長文字只給 600 字的 excerpt 並標 `text_truncated=true`；上下文中的單句最多 4000 字。結果頁放不下時縮短該頁並附 `page_shortened_for_size` 警告，再用 `next_cursor`／`next_offset` 繼續。`get_source_context` 不會丟掉要求的 ID，放不下時回 `RESULT_TOO_LARGE`。送出前再以 SDK 實際序列化結果檢查一次；業務錯誤本身若超限，也會改成精簡的 `RESULT_TOO_LARGE`。SDK 自行產生的協定／參數驗證錯誤不屬於此工具結果限制。
- **cursor** 綁定課程、資料層、正規化後的查詢與 revision；換了查詢條件就回 `INVALID_ARGUMENT`，課程變更則回 `STALE_REVISION`。
- **空結果**是正常成功（`isError=false`、`results=[]`），不是錯誤。

### 錯誤

業務錯誤以 MCP 工具錯誤回傳（`isError=true`），內容是：

```json
{
 "schema_version": 1,
 "error": {
  "code": "LAYER_UNAVAILABLE",
  "message": "editorial_notes is unsupported: Only legacy authored_notes.json exists; it has no source_ids contract",
  "details": {"layer": "editorial_notes", "status": "unsupported"}
 }
}
```

| code | 情況 |
|---|---|
| `COURSE_NOT_ALLOWED` | 課程 ID 不在 registry |
| `LAYER_UNAVAILABLE` | 指定的資料層缺少或不支援 |
| `INVALID_COURSE_DATA` | 資料層驗證失敗（例如講義的 raw hash 已失效、校訂稿段數或時間不符）、課程資料夾不存在、檔案解析到課程資料夾外，或 manifest 在 server 啟動後被修改 |
| `INVALID_ARGUMENT` | 參數超出範圍或 cursor 不符 |
| `SOURCE_NOT_FOUND` | `source_id` 不存在於目前 revision（`details.missing_source_ids` 列出全部） |
| `STALE_REVISION` | `expected_revision` 已過期（`details.current_revision` 是目前版本） |
| `COURSE_BUSY` | 讀取期間檔案持續變動 |
| `RESULT_TOO_LARGE` | 回應超過 64 KiB |
| `INTERNAL_ERROR` | 未預期的錯誤；細節只寫在 server 的 stderr |

參數型別或 schema 錯誤（例如 `source_ids` 傳 `true`）由 SDK 驗證，也以 `isError=true` 回傳。所有錯誤都不含本機絕對路徑、環境變數或 traceback。

## 停止與排查

- **正常停止**：關閉 AI host 或結束該次對話即可。host 關閉 stdin 後 server 會自行結束，不留背景程序；測試也確認 client 關閉後沒有殘留的 server 程序。
- **host 顯示連線失敗**：先在 PowerShell 用上方的絕對路徑命令手動啟動，看 stderr。registry 錯誤會印出 `cannot load course registry: ...` 並結束。
- **stdout 必須只有協定訊息**：server 的日誌一律寫到 stderr。若自行修改程式，不要在 server 中使用 `print()` 輸出到 stdout，否則 host 會解析失敗。
- **課程顯示 `status: error`**：`list_courses` 會列出原因，例如公開示範尚未執行 `create_demo.py`、課程資料夾不存在。
- **一直出現 `STALE_REVISION`**：課程檔案已經改變；重新呼叫 `list_courses` 或 `search_course` 取得新的 revision。
- **修改了 manifest 或 registry**：重新啟動 server（重新開啟 host 的連線）。

## 已知限制

- 搜尋是字面比對。示範課程內文寫的是「Queue」，用「佇列」搜尋不會命中；AI host 需要自行嘗試不同字詞。
- `page_id` 只有經原稿配對與人工核對的課程才有；公開示範沒有，回傳 null，不會從圖片檔名推測。
- hard link 無法從路徑分辨，路徑邊界檢查只涵蓋 symlink 與 junction。本機若無建立 symlink 的權限，對應測試會明確跳過；junction 案例照常執行。
- 第一版不合併人工修訂與閱讀稿，也不提供 reader 深連結；需要時另開既有閱讀器核對時間。
