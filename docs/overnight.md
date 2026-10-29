# 睡前處理一堂課

本頁的背景生成流程使用本機文字模型。若講義已改由 Codex 直接撰寫，請使用下方「Codex 直接撰寫與發布」，不要以舊的 `resume` 覆寫新版。

## 新課程預設作業流程

依 [資工筆記規格](../profiles/computer-science/note-spec.md) 的「新課程影片到發布的標準流程」執行：建立來源及前課脈絡 → 原始轉錄與投影片時間軸 → 對照原圖校訂逐字稿、針對疑點回聽 → AI 修順獨立閱讀稿 → 撰寫講義與清理待核對清單 → 忠實性、教學品質及資料驗收 → 依授權發布。

閱讀稿可去口頭禪與無意義重複，但必須保留老師原話的校訂版本、來源時間與實質內容。後續人工／線上修訂須連動檢查閱讀稿、講義與清單；閱讀區不插入模型建議或核對小字。本頁舊背景管線不等於已自動完成這些編輯與驗收工作；「閱讀稿／查看原話」切換及版本失效處理須以實際程式驗收為準。

在專案根目錄的 PowerShell 使用 `lecture.cmd`。這是本機背景程序，不需保持 Codex 對話持續執行。電腦需保持開機且不進入睡眠；不會修改 Windows 電源、驅動、全域 PATH、執行原則或註冊服務。

完整處理環境已就緒後，第一次先執行 `.\lecture.cmd prepare`，將預設視覺與文字模型下載至專案 `models/`（已有的模型會重用）。文字模型 [`qwen2.5:7b`](https://ollama.com/library/qwen2.5:7b) 約 4.7 GB；這一步需要網路，結束會停止專案 Ollama。

## 開始、查看與續跑

### 有原始投影片：正式視覺入口

已有影片任務（包含 `media.json` 與 `media/lecture.mp4`）時，使用以下命令建立獨立核對資料：

```powershell
.\lecture.cmd visual --job "output/jobs/任務ID" --references "原稿索引/references.json" --out "output/jobs/任務ID/visual-review"

# 同一資料夾可續跑；加上此旗標，才對變化前後的原尺寸裁切圖做 CPU OCR
.\lecture.cmd visual --job "output/jobs/任務ID" --references "原稿索引/references.json" --out "output/jobs/任務ID/visual-review" --ocr-regions
```

`references.json` 是陣列，每筆包含 `deck_id`、`source`、`source_sha256`、`render_pdf`、`render_sha256`、`slide_count`；檔案路徑使用絕對路徑。PPTX 須先有核對過的 PDF 呈現及原稿 hash。本命令不自動轉檔，亦不修改原稿。

流程為原稿文字基準 → 一次影片解碼同時產生每秒低解析度換頁探針與五秒配對畫面 → 五秒頁面配對 → 補抓原尺寸邊界與影片尾端畫面 → 局部差異清單（以同一次解碼產生的無損 960 寬比較畫面兩兩比較，避免 JPEG 與原尺寸畫面縮放方式不同造成假差異）。原稿頁面特徵預設快取在 `data/cache/deck-features/`，換原稿、呈現 PDF 或程式版本會自動重建；續跑時已完成的配對、邊界畫面與裁切圖都直接沿用。`--ocr-regions` 會將差異座標換算回原尺寸，保留變化前後裁切圖並辨識；不把 OCR 當成已確認的手寫文字，不以空辨識結果刪除差異。模糊／無法配對的頁面仍須人工核對，必要時另做全圖辨識。

輸出包括 `page-baselines.json`、`alignment.json`、`differences.json`、選用的 `region-ocr.json` 與 `status.json`。完成狀態是 `review_required`，不是講義已發布。相同輸入可續跑；影片、原稿索引或視覺程式版本改變時須指定新輸出目錄。命令透過 `run.py` 執行並取得專案處理鎖，不啟動 Ollama。

此入口不會刪除既有 occurrence、改寫正式證據或自動執行舊文字模型。核對後再進入 Codex 校訂、撰寫與 `editorial_publish.py`。下方 `start/resume` 仍是舊整夜路線，尚未自動切換成原稿輔助流程。

抽圖快取會檢查張數、連續序號及每張圖片 hash。若收到 `Frame cache` 完整性錯誤，請選擇新的 `--out` 重新建立核對資料，保留舊資料供比較；不要自行重編圖片序號或編造 hash。舊版沒有圖片完整性清單的快取也須重建。`Comparison frame` 錯誤代表差異比較畫面缺漏、被修改或來自舊版輸出，同樣請改用新的 `--out`。裁切紀錄缺少 checksum 或損壞則會自動重新裁切，避免誤用其他圖片的 OCR。

### 無原稿：舊整夜路線

透過 `run.py` 執行的 `quick_ocr` 現在使用 `course/ocr-cache/`，完全相同的解碼像素只辨識一次，回頁時間照常保留。快取包含 OCR 程式、模型、設定與套件版本；錯誤結果不快取。相似但不同的畫面仍分別辨識，避免吞掉小符號。已有 `slides_raw.json` 不會因加入快取而自動重跑。

```powershell
# 本機影片（路徑有空白時保留引號）
.\lecture.cmd start "C:\Courses\lecture01.mp4" --title "作業系統第一堂" --background

# YouTube；一次只下載指定影片，不展開播放清單
.\lecture.cmd start "https://www.youtube.com/watch?v=影片ID" --title "課程名稱" --background

# 開始時會印出任務 ID；不指定 ID 時自動產生，不會覆寫舊課程
.\lecture.cmd status
.\lecture.cmd status 任務ID

# 同一任務失敗後接續；已完成的階段經 hash 核對後略過
.\lecture.cmd resume 任務ID --background

# 隔天開啟本機閱讀服務，Ctrl+C 結束服務
.\lecture.cmd serve 任務ID --port 8769
```

服務啟動後：講義為 <http://127.0.0.1:8769/index.html>，待核對清單為 <http://127.0.0.1:8769/review.html>。更換 port 時使用相同的新 port。服務一次讀取一個任務；原本課程及 demo 的服務不受影響。

省略 `--background` 會在目前終端執行並印出階段；Ctrl+C 會嘗試終止該階段的子程序並關閉專案 Ollama。背景執行的日誌在 `output/jobs/任務ID/worker.log`；關閉終端後工作仍可繼續，但登出、關機或睡眠會中斷／暫停。重新開機後需明確 `resume`，沒有自動開機服務。

## 先決條件與資源

- 完整處理環境：專案 `.venv`、鎖版依賴、上游 checkout、FFmpeg／ffprobe、Whisper large-v3、可攜 Ollama 與已下載的 `minicpm-v:8b`。環境建立見 [開發文件](development.md)。公開 demo 的最小環境不足以執行模型管線。
- 目前轉錄使用 CUDA 與中文模式，英文術語由資工詞彙表輔助。非中文課程尚未提供語言選項。
- 預設用 `minicpm-v:8b` 看圖、`qwen2.5:7b` 撰寫文字，不需要雲端 API key。兩者依序執行，前一個模型卸載後才進行下一階段。`--model` 可選已安裝、支援結構化 JSON 的文字模型，`--vlm-model` 選視覺模型；品質與資源需求需另外驗證。`start` 不自動 pull 模型，請先 `prepare`。
- 影片會轉為瀏覽器可播放的 H.264／AAC 副本，不修改來源。長片可能在此階段花較多 CPU 時間。
- 預設每 2 秒保留 PNG 樣本；只合併相鄰且解碼像素完全相同的畫面。回頁保留新的出現區間，新增註記保持獨立。相同畫面可共用 VLM 分析，講稿仍按每次出現獨立整理。
- 壓縮雜訊、游標移動、攝影機／講師畫面可能導致很多區間，增加 OCR、VLM、講義生成與磁碟用量。先用短片估測耗時；目前未設自動刪除樣本。`--interval 5` 可減少樣本，但也更容易漏取短暫切頁。
- 語音與視覺／文字推論依序執行；管線以跨程序鎖防止兩個本管線任務同時使用 GPU。此鎖不控制外部應用或手動啟動的模型。

## 實際執行順序

1. 檢查環境、來源身分、Ollama 連線與兩種模型版本，下載／轉碼至獨立任務目錄。
2. Whisper 轉錄至私有暫存，驗證成功後才保存正式原始逐字稿。
3. 抽圖、OCR、按像素相同與否共用分析、資工 VLM、grounding。
4. 建立每次畫面出現的證據與逐字稿主要歸屬，不用低 keyword overlap 刪內容。
5. 本機文字模型按每次出現、最多約 2,000 字／60 秒的來源批次撰寫講義。來源 ID 由結構化輸出限制且必須完整覆蓋，時間由程式填入；格式、覆蓋錯誤或格式範例抄寫會重試。大幅改寫原句、更動數字或抄用鄰句的校字建議不採用：保留原句，受影響的講義段落也改為明示的待核對原句，未確認的推論不當成正式解釋；其餘段落可繼續生成。
6. 保存 AI 校正版、逐句校正依據、疑點，建置共用閱讀器。
7. 核對原稿 hash、每個畫面筆記、逐字稿歸屬與時間範圍，輸出待核對清單。
8. 成功、失敗或可攔截的中斷後均嘗試停止專案 Ollama；關閉失敗會標記任務失敗，不能顯示全部完成。

## 進度與產物

所有資料在 `output/jobs/任務ID/`，被 Git 忽略，不會改寫根目錄 `course.local.json` 或既有課程。

| 檔案 | 用途 |
|---|---|
| `job.json` | 原始來源、模型、抽樣與重試設定；建立後不可修改來混用成果 |
| `status.json` | 任務／階段狀態、嘗試次數、時間、心跳、錯誤、產物 hash、Ollama 清理結果 |
| `events.jsonl`、`logs/*.log` | 階段開始／完成／失敗事件與各階段的完整輸出 |
| `course/author_progress.json` | 講義已完成批次／總批次 |
| `course/_author/v*/**.json` | 分版本的講義批次 checkpoint，續跑時重用；失敗回應另存供診斷 |
| `course.local.json`、`index.html` | 該任務的閱讀設定與閱讀頁 |
| `review.html`、`待核對清單.md`、`review.json` | 可閱讀及可機器處理的疑點清單 |
| `完整課程講義.md` | 純文字講義，可獨立備份 |
| `course/transcript.json` | 原始逐字稿，生成後不覆寫 |
| `course/transcript.corrected.json`、`transcript.corrections.json` | AI 校正版與修訂依據，未逐句聽音覆核 |
| `course/coverage_report.json` | 結構／來源覆蓋報告，不是內容正確率評分 |

## 失敗時的行為與限制

預設每個失敗階段最多自動再試 2 次（`--retries 0..5`）；模型生成另有每批格式／連線重試，會帶入驗證錯誤再請模型修正。持續失敗就停止，保留完成產物與錯誤，使用相同 ID `resume`。未完成的轉錄／抽圖會整段重跑；若轉錄已保存完整結果及 receipt，只差最後更新進度，會驗證後採用，不重跑 ASR。VLM 按頁保存，講義按批保存。

Windows 偶爾會因進度讀取或掃描暫時鎖住檔案；VLM 的中途 checkpoint 及最後 JSON 匯出都經專案轉接器做有限次原子替換重試，不修改上游原始碼。無法替換時仍會明確失敗，保留前次完整 checkpoint。

已完成產物被人工修改、來源影片、任務設定或模型權重版本改變時，拒絕靜默重建，以免蓋掉修訂。不同影片／模型／抽樣策略應建立新 ID；需要修復被外部改動的任務時先備份並核對，不要刪除原始逐字稿或人工修訂。

硬性終止程序、斷電／關機無法保證執行 finally。`status` 會在看不到 PID 且心跳逾時時標示可能中斷（受限執行環境也可能看不到主機 PID）；`resume` 會重新取得 OS 鎖，按 PID、建立時間及專案命令核對並結束殘留的本任務子程序，再驗證產物、接續工作。無法確認身分時停止並保留錯誤，不會盲目終止其他程序。殘留的專案 Ollama 可在專案根目錄用 `.venv/Scripts/python.exe ollama_service.py stop` 停止；不會停止其他位置的 Ollama。

清單涵蓋模型提出的疑點、沒有獨立講稿的轉場與沒有 OCR 文字的畫面，**不是完整錯誤偵測器**。來源 ID 覆蓋只能證明原句被分配到講義，無法證明模型解釋正確或沒有省略細節。仍需抽查數字、公式、術語與程式碼；短於抽樣間隔的畫面不保證擷取。

Related: [課程格式](courses.md)、[講義規格](../profiles/computer-science/note-spec.md)、[ADR 0002](architecture/adr/0002-resumable-local-lecture-pipeline.md)。

## Codex 直接撰寫與發布

逐字稿、OCR、視覺分析與畫面時間仍可沿用；講義正文由 Codex 讀取這些來源後直接編寫，保存為課程目錄的 `editorial_chapters.json`。同系列課程先閱讀前課講義及待核對事項，再接續下一堂。這個檔案必須包含全課總覽、連續章節、段落文字、來源 ID 及明示的疑點，不能用重新命名本機模型舊稿代替撰寫。

```powershell
# 這兩個命令只做資料驗證與發布，不會啟動任何模型
.\.venv\Scripts\python.exe editorial_publish.py --course output/jobs/任務ID/course.local.json
.\.venv\Scripts\python.exe editorial_publish.py --course output/jobs/任務ID/course.local.json --check
```

發布前驗證原始逐字稿 hash、全部片段依序恰好歸屬一次、章節時間連續及所有來源圖片存在。舊閱讀頁、講義與清單會先備份；原稿、人工修訂和既有視覺證據不覆寫。閱讀頁優先顯示分章講義，另保留每次投影片出現（含回頁與註記）的來源對照。`authoring_provenance.json` 記錄作者、證據摘要、備份及校正版沿用範圍。

已有 `editorial_chapters.json` 的課程，舊 Worker 的前置檢查與作者階段會拒絕再次呼叫本機文字模型。修改正文後應重新執行發布命令。來源覆蓋通過不等同內容完全正確；未聽音確認的疑點仍須保留。

## 本機驗證範圍（2026-10-21，歷史紀錄）

以下是舊整夜路線當時的驗收紀錄，測試數量不是目前結果；目前的測試命令與驗收見 [開發與測試](development.md) 及 [公開準備狀態](open-source-readiness.md)。

- 24 秒真實課程片段完成全部階段，確認背景程序在啟動命令結束後繼續工作；OCR 故障後續跑略過已完成轉錄及抽圖。另用 8 秒片段驗證原稿 receipt 與完整流程，再續跑一次確認完成產物重用。
- 64 項 Python 測試、35 項閱讀器 Node 測試通過。涵蓋失敗／原子替換／原稿保護／校字防護／來源覆蓋／孤兒子程序與 PID 重用保護；相同畫面回訪與一個像素的註記差異有 FFmpeg 整合測試。
- 本機 HTTP 驗證講義、待核對 HTML、12 個圖片請求及媒體 206 byte range 共 15 項通過。完成後實際連線確認專案 Ollama 的 11435 port 已關閉。
- 本輪沒有完整長課耗時測量、YouTube 新下載的端到端驗收或新一輪真實瀏覽器操作驗收；既有閱讀器互動回歸通過。短片的結構成功不能當作長課品質、速度或數字正確率保證。
