# 原創端到端範例：從影片與 PDF 到閱讀頁

這份指南帶你用一套**原創、可重新產生**的資工微課程（循環佇列如何分辨空與滿，約 3 分鐘），實際走過 LectureThread 現有的處理流程：

產生素材 → 建立任務與原稿索引 → 語音辨識（ASR）→ 原稿對齊、換頁與區域 OCR → 人工核對 → 逐字稿校訂 → 閱讀稿與講義撰寫 → 驗證、建置並開啟閱讀頁 → 對照標準答案評估。

它和 [公開示範](quickstart.md) 不同：公開示範只有 36 秒提示音與預寫腳本，不需要模型；本範例有口語旁白、影片，並實際執行 ASR 與 OCR。

> **旁白是合成語音，不是真人授課。** 本範例使用 Windows 內建的 SAPI 語音「Microsoft Hanhan Desktop」（zh-TW）朗讀原創腳本，不模仿任何真實人物。合成語音的辨識表現**不能**推論為真實授課錄音的準確率。

本指南也說清楚哪些步驟是自動的、哪些需要人工核對、哪些由 AI 助理協助撰寫。**目前沒有任意影片一鍵完成的流程**；人工與撰寫步驟各自有輸入格式、驗收方法和可重用的提示範本（[ai-assist-templates.md](../examples/end-to-end/ai-assist-templates.md)）。

## 流程總覽

| # | 步驟 | 入口 | 類型 | 模型推論 | 網路 |
|---|---|---|---|---|---|
| 1 | 產生原創 PDF、旁白、影片 | `examples/end-to-end/scripts/generate_materials.py` | 自動 | 合成語音（本機 SAPI） | 否 |
| 2 | 建立任務、原稿索引，執行 ASR | `examples/end-to-end/scripts/prepare_job.py` | 自動 | Whisper large-v3（CUDA） | 首次下載模型 |
| 3 | 原稿對齊、換頁補抓、局部差異、區域 OCR | `lecture.cmd visual … --ocr-regions` | 自動 | RapidOCR（CPU） | 否 |
| 4 | 核對頁面區間與差異事件 | `review_visual.py` → 人工填 `decisions.json` | **人工** | 否 | 否 |
| 5 | 建立正式畫面證據 | `build_evidence.py` | 自動（讀人工決定） | 否 | 否 |
| 6 | 逐字稿校訂 | 撰寫校訂計畫 → `apply_corrections.py` | **人工／AI 協助** + 自動套用 | 否 | 否 |
| 7 | 閱讀稿 | 撰寫草稿 → `build_reading_layer.py` | **AI 協助撰寫** + 自動驗證 | 否 | 否 |
| 8 | 講義 | 撰寫 `editorial_chapters.json` | **AI 協助撰寫**，人工教學品質檢查 | 否 | 否 |
| 9 | 驗證並建置閱讀頁 | `editorial_publish.py`（`--check` 稽核） | 自動 | 否 | 否 |
| 10 | 開啟並操作閱讀頁 | `serve_reader.py` | 人工驗收 | 否 | 否 |
| 11 | 對照標準答案評估 | `evaluate.py` | 自動（只用於評估） | 否 | 否 |

所有命令都在**專案根目錄**的 PowerShell 執行（例如 `C:\Projects\lecture-thread`）。產物都寫到被 Git 忽略的 `output/`；Git 只保存可散布的文字來源、產生器與說明。

## 1. 支援環境與硬體

- **作業系統**：Windows 10／11 x64、Windows PowerShell 5.1 以上。其他平台未驗收；合成旁白依賴 Windows SAPI。
- **GPU**：ASR 階段固定以 `--device cuda` 執行 faster-whisper large-v3，需要 NVIDIA CUDA GPU；目前流程**沒有 CPU 選項**。參考執行環境：RTX 5070 Ti 16 GB、驅動 610.88、Core Ultra 7 265K、約 32 GB RAM。large-v3 float16 大約需要數 GB 顯示記憶體，較小顯卡未驗證。
- **磁碟**：Whisper 模型約 2.9 GB（專案 `models/huggingface/`）；本範例產物約 40 MB（素材 20 MB、任務 18 MB）。
- 不會修改全域 PATH、驅動、PowerShell 執行原則或系統服務。

## 2. 工具、Python 依賴與模型

| 項目 | 用途 | 取得方式 |
|---|---|---|
| uv 可攜版 `tools/uv/uv.exe` | 建立專案 Python 3.12 與 `.venv` | 見 [開發與測試](development.md#先決條件) |
| `.venv` + `requirements.lock.txt` | 完整鎖版依賴（faster-whisper、ctranslate2、CUDA 使用者態函式庫、RapidOCR、OpenCV、PyMuPDF、OpenCC…） | 見 [開發與測試：選用的完整處理環境](development.md#選用的完整處理環境) |
| 上游 checkout `vendor/lecture-to-notes` | 轉錄腳本與 quick_ocr（RapidOCR 包裝） | 同上；固定於 `upstream-commit.txt` |
| FFmpeg／ffprobe | 合成影片、轉碼、抽圖 | 只加到目前終端的 PATH，見 [開發與測試](development.md#先決條件) |
| Windows 語音「Microsoft Hanhan Desktop」（zh-TW） | 合成旁白 | Windows 設定 → 時間與語言 → 語音 → 新增語音 → 中文（台灣）。多數繁中 Windows 已內建 |
| faster-whisper large-v3 | ASR | 第一次執行 ASR 時自動下載到 `models/huggingface/`（需網路） |
| RapidOCR 模型 | 區域 OCR | 隨 `rapidocr-onnxruntime` 套件安裝 |

本範例**不需要** Ollama、VLM（minicpm-v）或本機文字模型（qwen2.5）；`lecture.cmd visual` 不會啟動 Ollama。

參考執行的版本：Python 3.12.15、faster-whisper 1.2.1、ctranslate2 4.8.3、rapidocr-onnxruntime 1.4.4、onnxruntime 1.31.0、opencv-python 5.0.0.93、PyMuPDF 2.0（MuPDF 1.28.5）、OpenCC（opencc-python-reimplemented 0.1.7）、FFmpeg 8.0.1（gyan.dev）、SAPI 語音 `TTS_MS_ZH-TW_HANHAN_11.0`。

## 3. 哪些步驟需要網路

- **需要網路**：建立 `.venv`（下載 Python 與套件）、clone 上游、第一次 ASR 下載 Whisper 模型、尚未安裝時下載 Windows 中文語音。
- **可離線**：上述都完成後，產生素材、ASR、visual、OCR、核對、撰寫、發布、閱讀與評估都在本機完成，不呼叫雲端 API。

開始前，在同一個 PowerShell 視窗確認：

```powershell
$env:PATH = 'C:\path\to\ffmpeg\bin;' + $env:PATH
ffmpeg -version
.\.venv\Scripts\python.exe .\run.py -c "import faster_whisper, ctranslate2, rapidocr_onnxruntime, pymupdf; print(ctranslate2.get_cuda_device_count())"
Test-Path vendor\lecture-to-notes\scripts\transcribe_video.py
```

成功：FFmpeg 印出版本、CUDA 裝置數至少 1、`Test-Path` 為 `True`。

---

## A. 執行此原創範例

### 步驟 1：產生原創 PDF、旁白與影片（自動，合成語音）

前置輸入（Git 追蹤，可直接編輯）：

- `examples/end-to-end/course/deck.json`：投影片內容（6 頁）與手寫註記定義。
- `examples/end-to-end/course/storyboard.json`：旁白腳本（19 段）與每段開始時的畫面變化。
- `examples/end-to-end/course/content-baseline.json`：講義內容核對基準（不給任何偵測步驟讀取）。

```powershell
.\.venv\Scripts\python.exe examples/end-to-end/scripts/generate_materials.py
```

輸出：`output/e2e-circular-queue/materials/`

| 檔案 | 內容 |
|---|---|
| `deck.pdf` | 原稿 PDF，有文字層；不含現場註記 |
| `deck.json` | 原稿來源的不變副本，給 references.json 引用 |
| `tts/*.wav`、`tts/tts.json` | 每段合成語音與快取紀錄（文字、語音、速度、hash） |
| `narration.wav`、`lecture.mp4` | 完整旁白與 25 fps H.264／AAC 影片 |
| `narration_script.json` | **標準答案**：腳本與合成後的時間，只能用於評估與校訂 |
| `expected_events.json` | **標準答案**：預期畫面狀態與事件（換頁、回頁、逐步出現、註記、擦除、短暫回頁、0.6 秒挑戰），只能用於評估 |
| `materials.json` | 各檔 hash、大小、語音資訊、工具版本、耗時 |

成功判斷：終端印出 `video 183.6 s, 19 narration segments, 16 visual states, 16 expected events`（時間依語音版本略有差異）。完整產生成功後，重跑會驗證 `materials.json`：三份來源、產生器及 PDF／影片／旁白／標準答案的 hash 全部相符才原樣沿用，不重寫任何素材。PDF 也停用隨機檔案 ID，讓相同來源在相同工具版本下可逐位元組重現。來源或產生器更新、產物缺漏或修改、上次中斷未留下完整 receipt 時，請使用新的 `--out`，不要刪改 receipt 來強行續跑。

> 合成語音由 Windows 內建語音產生，生成的音訊與影片只留在本機；本專案不宣稱可再散布這些語音輸出，請在每台電腦重新產生。

### 步驟 2：建立任務與原稿索引，執行 ASR（自動，GPU 推論）

```powershell
.\.venv\Scripts\python.exe examples/end-to-end/scripts/prepare_job.py
```

它使用與 `lecture.cmd start` 相同的任務格式與 `Worker.source`／`Worker.transcribe` 階段（轉成瀏覽器可播放的 H.264 副本；faster-whisper large-v3、CUDA、中文、資工術語提示），**做完 ASR 就停**，不會進入舊路線的 OCR、VLM 與本機文字模型撰寫。任務被標成 `codex-direct`，所以之後不能用 `lecture.cmd resume` 接續舊路線。

輸出：

- `output/e2e-circular-queue/references.json`：原稿索引（`deck_id`、`source`、`source_sha256`、`render_pdf`、`render_sha256`、`slide_count`；絕對路徑）。
- `output/jobs/e2e-circular-queue/`：`job.json`、`status.json`、`media/lecture.mp4`、`media.json`、`logs/transcribe.log`。
- `output/jobs/e2e-circular-queue/course/transcript.json`：**原始 ASR，之後永不覆寫**。

成功判斷：印出 `source: completed`、`transcribe: completed` 與原始 ASR 的 SHA-256。參考執行耗時：轉碼 8 秒、ASR 24 秒，44 段。也可用 `.\lecture.cmd status e2e-circular-queue` 查看。

### 步驟 3：原稿對齊、換頁補抓、差異與區域 OCR（自動，CPU OCR）

```powershell
.\lecture.cmd visual --job "output/jobs/e2e-circular-queue" --references "output/e2e-circular-queue/references.json" --out "output/jobs/e2e-circular-queue/visual-review" --ocr-regions
```

這是既有的正式入口，細節見 [睡前處理一堂課](overnight.md#有原始投影片正式視覺入口)。它做：PDF 文字基準 → 一次解碼產生 1 fps 換頁探針（320×224，面積門檻 2.5%）與 5 秒配對畫面 → 頁面配對 → 補抓原尺寸換頁邊界 → 同頁局部差異 → 對差異前後的原尺寸裁切做 OCR。

輸出（`visual-review/`）：`page-baselines.json`、`change-scan.json`、`alignment.json`、`differences.json`、`region-ocr.json`、`crops/`、`source-frames/`、`status.json`。

成功判斷：最後一行的 `state` 是 `review_required`（不是「已完成發布」），`ocr_errors` 為 0。參考執行：60 秒，其中區域 OCR 47 秒；184 個探針、8 個換頁事件、58 個觀察點、5 個差異事件。

### 步驟 4：核對頁面區間與差異事件（**人工**）

先產生核對包：

```powershell
.\.venv\Scripts\python.exe examples/end-to-end/scripts/review_visual.py --job output/jobs/e2e-circular-queue
```

輸出 `output/jobs/e2e-circular-queue/visual-human-review/`：

- `review.md`：每個頁面候選區間（run）、換頁事件、差異事件與 OCR 線索。
- `runs.png`：每個 run 的第一張畫面。
- `diff-XX.png`：每個差異事件 before／after 的原尺寸裁切。
- `decisions.template.json`：所有 run 與差異事件，決定都是 `pending`。

人工工作：

1. 複製 `decisions.template.json` 為 `decisions.json`。
2. 打開 `runs.png`，確認每個 run 的候選頁正確；正確填 `confirmed`，頁碼錯就填 `corrected` 並改 `page_id`，不是投影片（例如黑畫面）填 `noise`。
3. 逐一打開 `diff-XX.png`，判斷 `annotation_add`、`annotation_erase`、`reveal`、`content_change` 或 `noise`，並在 `meaning` 用一句話寫出**畫面上實際改變了什麼**（例如「索引 2 上方加紅色 front 與箭頭」）。OCR 只是線索：空字串不代表沒有變化，有文字也不代表辨識正確。
4. 填 `reviewer`、`reviewed_at`、`method`（看了哪些圖、沒看哪些）。
5. 保留模板的 `id` 與來源欄位（run 的 `start`、`last_observed`、`status`、`candidate_page`；差異的 `page_id`、`before_time`、`after_time`）。可調整列順序，但不能改 ID、重複或刪漏項目。修正頁碼只改 run 的 `page_id`，不要改 `candidate_page`。
6. 若你另外看影片發現偵測器漏掉的變化，記在 `missed`，並說明目前工具不會自動把它加入證據。

**不要**打開 `expected_events.json` 來填決定；它是評估用的標準答案。

成功判斷：`decisions.json` 沒有 `pending`，所有 ID 與來源欄位通過驗證。若某個 run 是黑畫面或非投影片，請如實保留 `noise`；目前銜接工具不支援發布這類區間，下一步會停止。不要把它改成 `confirmed` 或刪掉來繞過檢查。局部差異標成 `noise` 則可以正常忽略，不改變頁面區間。

### 步驟 5：建立畫面證據（自動）

```powershell
.\.venv\Scripts\python.exe examples/end-to-end/scripts/build_evidence.py --job output/jobs/e2e-circular-queue --references output/e2e-circular-queue/references.json
```

規則：人工決定按唯一 ID 配對，順序改變不影響結果；缺漏、重複、未知 ID 或來源欄位不符會被拒絕。有任一 `noise` run 時，在寫入任何畫面或證據前停止，既有產物維持不變；不把非投影片時段歸給前一頁。每個核對過的 run 都是一次出現（回頁、短暫回頁各自保留，不合併），再在每個被接受的 reveal／註記／擦除事件處切開。每次出現附原尺寸畫面（沒有時用 960 寬無損比較畫面）、圖片 hash、頁碼、PDF 文字層（標明是原稿最終狀態）、OCR 線索、時間精度說明，並依時間重疊為每段 ASR 指定一個主要出現區間。

輸出：`course/slide_evidence.json`、`course/slides/occ-*.png`、`course/visual_provenance.json`（方法、alignment／differences／decisions 的 hash、核對者）、`course.reader.json`（閱讀器設定）。

成功判斷：印出出現區間清單。參考執行：14 次出現，頁序 1→2→3→3→3→4→4→2→4→4→4→5→3→6。

### 步驟 6：逐字稿校訂（**人工／AI 協助** + 自動套用）

原始 `transcript.json` 不改。校訂是另一層：

1. 看原始 ASR 與同時間投影片文字（`slide_evidence.json` 的 `deck_text_layer`），寫一份校訂計畫 `output/jobs/e2e-circular-queue/authoring/corrections.plan.json`。格式與規則見工具說明與 [AI 協助範本 1](../examples/end-to-end/ai-assist-templates.md#範本-1逐字稿校訂計畫)。
   - 本範例有旁白腳本（`narration_script.json`），可以作為校訂依據，`basis` 填 `narration-script`。真實課程沒有腳本，只能依投影片（`slide-text`）、前後文與回聽；未聽音就不能寫成已聽音確認。
2. 套用：

```powershell
.\.venv\Scripts\python.exe examples/end-to-end/scripts/apply_corrections.py --job output/jobs/e2e-circular-queue --plan output/jobs/e2e-circular-queue/authoring/corrections.plan.json
```

工具先做專案既有的繁體字形正規化（OpenCC s2tw），再逐條套用；`find` 找不到或次數不符就停下，不猜。輸出 `transcript.corrected.json`（段數、順序、時間不變）、`transcript.corrections.json`（逐段原文、校訂、依據）與 `transcript.corrections.provenance.json`。

注意：OpenCC 會把「只」誤轉成「隻」（例如「最多隻存」），要在計畫中用 `normalization-fix` 修正。參考執行：25 段校訂、19 段只有字形正規化。

### 步驟 7：閱讀稿（**AI 協助撰寫** + 自動驗證）

依 [講義規格](../profiles/computer-science/note-spec.md) 的「AI 修順閱讀稿的界線」撰寫 `authoring/reading.draft.json`（範本 2），每段標出連續的 `source_ids`，再逐句標出來源。然後：

```powershell
.\.venv\Scripts\python.exe examples/end-to-end/scripts/build_reading_layer.py --job output/jobs/e2e-circular-queue --draft output/jobs/e2e-circular-queue/authoring/reading.draft.json
```

工具補上原句、時間與 hash，並用閱讀器相同的驗證寫入 `course/transcript.reading.json`。可再用既有工具產生對照草稿檢查逐句對應：

```powershell
.\.venv\Scripts\python.exe align_reading_sentences.py draft --course output/jobs/e2e-circular-queue/course.reader.json --draft output/jobs/e2e-circular-queue/authoring/sentence-align.draft.json
```

這份草稿只用文字重疊排列，不能直接當成已核對的對應。

### 步驟 8：講義（**AI 協助撰寫**，人工教學品質檢查）

先完整讀 [講義規格](../profiles/computer-science/note-spec.md)（包括「直白好理解的講義」與「教學品質檢查」），再撰寫 `course/editorial_chapters.json`（範本 3）。資料結構：

```json
{
  "schema": 1, "author": "Claude Code", "status": "reviewed",
  "course_date": "…", "title": "…", "raw_transcript_sha256": "<transcript.json 的 SHA-256>",
  "overview": "核心問題 → 分段推進 → 結論，附代表時間",
  "chapters": [
    {"title": "…", "start": 0.0, "end": 15, "summary": "…",
     "paragraphs": [{"heading": "…", "time": 0.0, "source_ids": [0], "text": "…"}],
     "checks": [{"time": 95.6, "source_ids": [18], "message": "具體、可回看的疑點"}]}
  ]
}
```

驗證規則（`editorial_content.py`）：`author` 必須是 `Codex` 或 `Claude Code`（直接撰寫，不是本機文字模型）；章節從 0 連續到影片長度；段落時間在章內且遞增；全部 ASR 段落**依序恰好歸屬一次**；`raw_transcript_sha256` 必須等於目前原始 ASR。

建議章節起點對齊核對後的換頁時間（`slide_evidence.json` 的 `start`），否則閱讀頁會顯示章節起點那一刻、還沒換頁的投影片。參考執行原先以 ASR 句子起點分章，第 4 章因此先顯示前一頁；改為換頁時間後解決。

教學品質檢查不能省略，逐章回答規格中的問題，發現缺口就改稿。

### 步驟 9：驗證並建置閱讀頁（自動）

```powershell
.\.venv\Scripts\python.exe editorial_publish.py --course output/jobs/e2e-circular-queue/course.reader.json
.\.venv\Scripts\python.exe editorial_publish.py --course output/jobs/e2e-circular-queue/course.reader.json --check
```

輸出（任務資料夾）：`index.html`、`完整課程講義.md`、`畫面來源對照.md`、`待核對清單.md`、`review.html`、`review.json`，以及 `course/reading_alignment.json`、`coverage_report.json`、`authoring_provenance.json`。舊版先備份到 `course/backups/`。

成功判斷：`--check` 印出 `metadata_valid: True`、`raw_transcript_unchanged: True` 與正確的作者。這只證明來源 ID、時間與 hash 一致，**不代表內容正確**。

### 步驟 10：開啟閱讀頁（人工驗收）

```powershell
.\.venv\Scripts\python.exe serve_reader.py --course output/jobs/e2e-circular-queue/course.reader.json --port 8772
```

開啟 <http://127.0.0.1:8772/index.html>，Ctrl+C 結束服務。請實際檢查：投影片圖片顯示；章節切換時投影片跟著換；「聽此段」從段落起點播放並在段尾停止；「觀看影片」能播放並讓逐字稿綠色標記跟著走；拖曳影片到 1:40 左右可看到 4→0 箭頭；章節選單的「查看原始畫面」列出 14 個畫面，含 1:42 的短暫回頁與 2:44 的回到規則頁。必須用 `http://`，不要直接開 HTML 檔，否則無法保存校字與正確 seek。

### 步驟 11：對照標準答案評估（自動，只用於評估）

```powershell
.\.venv\Scripts\python.exe examples/end-to-end/scripts/evaluate.py
```

輸出 `output/e2e-circular-queue/evaluation/evaluation.md`、`evaluation.json`：

- ASR 對照腳本的字元錯誤率（原始、OpenCC 後、校訂後）與關鍵術語次數。校訂後的數字接近 0 是因為校訂本身用了腳本，不是 ASR 的表現。
- 每個預期事件是否被換頁探針／頁面區間／差異事件捕捉、延遲多少，列出漏失與額外偵測。
- 資料檢查：原始 ASR hash、校訂時間、畫面圖片 hash、閱讀稿基底、全段落歸屬。
- 講義關鍵字檢查（只是檢查有沒有寫到，不能取代教學品質檢查）。

參考執行結果：13 個主要事件全部捕捉、0 個額外偵測；0.6 秒挑戰頁（與其返回）未被捕捉；資料檢查全部通過。

### 模型與 GPU 的完整手動驗收

CI 不下載模型也不跑 ASR。要在新機器驗收整條流程，依序執行步驟 1–3、5（用你的 `decisions.json`）、6–9、11 的命令；步驟 4、6–8 的人工／撰寫內容可參考 [`examples/end-to-end/reference-run/`](../examples/end-to-end/reference-run/README.md)。它們綁定參考執行的 hash，新執行的 hash 不同時工具會拒絕，這時請依範本重新核對與撰寫，不要硬改 hash。

## 中斷後續跑與何時換新目錄

| 步驟 | 可以直接重跑 | 必須換新目錄／新 ID 的情況 |
|---|---|---|
| 1 產生素材 | 完整 receipt、來源、產生器與產物 hash 相符時，原樣沿用全部素材 | 來源／產生器變更、缺檔、修改或中斷未完成：新的 `--out`；不要覆寫已引用的素材 |
| 2 任務與 ASR | 是；已完成且 hash 相符的階段會略過 | 影片變了會報 `belongs to a different video`：用新的 `--job-id` |
| 3 visual | 是；同一個 `--out` 會沿用解碼、配對、裁切與 OCR | 影片、references 或視覺程式更新：報 `Visual inputs changed`，換新 `--out` |
| 4 核對包 | 是；只覆寫 template，不動 `decisions.json` | visual 輸出變了，舊 `decisions.json` 會被拒絕，需重新核對 |
| 5 證據 | 決定的 ID 與來源欄位有效，且沒有 `noise` run 時 | `noise` run 會阻止發布；保留核對資料，待支援非投影片證據後再處理 |
| 6 校訂 | 有閱讀稿或人工修訂層後拒絕重建基底 | 原始 ASR 變了：校訂計畫、閱讀稿、講義都要重新撰寫 |
| 7–9 | 是；發布前會備份 | 校訂稿 hash 變了，閱讀稿要重新核對再建置 |

## 常見錯誤

| 訊息 | 原因與處理 |
|---|---|
| `Material sources or generator changed`／`Material missing or changed`／`Incomplete materials directory` | 選新的 `generate_materials.py --out`；後續 `prepare_job.py --materials` 指到該目錄，並用新 `--job-id`。舊版生成的素材因產生器 hash 改變也適用；保留舊任務即可繼續檢視已發布成果 |
| `duplicate, missing or unknown decision IDs`／`source metadata differs` | 對照原核對模板，還原 ID 與來源欄位；不要按陣列位置猜測對應 |
| `Noise runs cannot be published` | 有非投影片區間，工具尚不支援建立其正式證據；保留 `noise` 決定與原始區間，停止本次發布，不要偽裝成前一頁 |
| `SAPI narration failed. The zh-TW voice "Microsoft Hanhan Desktop" must be installed` | 安裝中文（台灣）語音後重跑步驟 1 |
| `FileNotFoundError: [WinError 2]`（呼叫 ffmpeg 時） | 目前終端沒有 FFmpeg；依「開始前」加入 PATH |
| `Missing …lecture.mp4; run generate_materials.py first` | 先做步驟 1，或 `--materials` 指錯 |
| `… belongs to a different video; choose a new --job-id` | 素材重新產生過；用新的任務 ID |
| `Missing prerequisite` 或 `RapidOCR unavailable` | 沒有完整依賴或上游 checkout；見第 2 節 |
| ASR 階段失敗（看 `output/jobs/<id>/logs/transcribe.log`） | 多半是 CUDA／顯示記憶體；目前沒有 CPU 選項，需在有 NVIDIA GPU 的機器執行 |
| `Visual inputs changed; select a new --out directory`、`Visual output must be empty…` | 換一個新的 `--out` |
| `Reference changed; rebuild registry` | `deck.pdf`／`deck.json` 被改過；重新產生素材與 references |
| `decision must be one of …`、`describe what changed in "meaning"` | `decisions.json` 尚未填完 |
| `decisions.json was made for a different visual output` | visual 重跑過；重新產生核對包並核對 |
| `Segment N: expected 1 × '…', found 0` | 校訂計畫的 `find` 和正規化後文字不符；對照 OpenCC 後的文字修正 |
| `The plan was written for a different raw ASR` | ASR 重跑過；重新寫計畫 |
| `Editorial paragraphs must assign every transcript segment exactly once in order` | 講義段落漏掉或重複某些 `source_ids` |
| `Editorial raw transcript hash changed` | `raw_transcript_sha256` 不是目前 `transcript.json` 的 hash |
| `Editorial chapters must end at the course duration`／`…continuously cover the course` | 章節起訖不連續，或最後一章沒有結束在 `slide_evidence.json` 最後一筆的 `end` |
| `Reading sentences must split the paragraph text exactly` | 各句文字串起來不等於段落 `text` |
| 閱讀頁 port 被占用 | 換 `--port`，同時改網址 |
| pytest 無法寫暫存資料夾 | 加 `--basetemp=data/tmp/pytest` |

---

## B. 換成自己的影片與 PDF

本範例的工具大多可直接用在自己的課程，但需要自行準備有權使用的素材，且人工與撰寫步驟的工作量會隨影片長度增加。

1. **素材**：準備影片（MP4 等 FFmpeg 可讀格式）與原稿 PDF。原稿是 PPTX 時，先自行轉成 PDF 並核對頁數與內容；工具不會自動轉檔，也不會改原稿。
2. **references.json**：自己寫一個陣列，例如：

   ```json
   [{"deck_id": "ch1", "source": "C:\\Courses\\ch1.pptx", "source_sha256": "<SHA-256>",
     "render_pdf": "C:\\Courses\\ch1.pdf", "render_sha256": "<SHA-256>", "slide_count": 39}]
   ```

   hash 可用 `Get-FileHash -Algorithm SHA256 <檔案>` 取得（小寫十六進位）。
3. **任務與 ASR**：`prepare_job.py` 目前讀取範例素材資料夾的 `lecture.mp4`、`deck.json` 與 `deck.pdf`。自己的課程可以用相同方式呼叫 `lecture_pipeline.create_job` 與 `Worker.source`／`Worker.transcribe`，或執行 `lecture.cmd start` 完整舊路線（會使用本機 VLM 與文字模型，產生的講義屬於 AI 初稿）。ASR 術語提示固定使用 `profiles/computer-science/asr-glossary.txt`，內容偏向計算機系統與儲存課程；其他主題的術語可能誤聽較多。
4. **visual、核對、證據**：步驟 3–5 的命令只要換 `--job`、`--references`、`--out`。真實影片常有游標、錄影指示、攝影機畫面、縮放或手寫，差異事件會多很多；`noise` 決定也要逐一記錄。`build_evidence.py` 目前不支援把一個 run 手動拆成多頁（`split`）。
5. **校訂、閱讀稿、講義**：沒有腳本可對照，只能依投影片、前後文與回聽。同系列課程先讀前一堂的最新講義與待核對事項。依範本撰寫，並完成規格中的教學品質檢查。
6. **發布與閱讀**：步驟 9–10 相同；`build_evidence.py` 的 `--title`、`--description` 可改課程名稱與說明。
7. **評估**：沒有標準答案，`evaluate.py` 不適用；請以抽查原圖、回聽與規格驗收取代。

不要用本範例的參考結果推論任意影片的辨識或偵測準確率。
