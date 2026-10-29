# 開發與測試

## 原始投影片配對（候選層）

正式整合入口為 `lecture.cmd visual --job ... --references ... --out ... [--ocr-regions]`，見 [操作說明](overnight.md)。`visual_pipeline.py` 串接頁面配對、換頁補抓、局部差異與選用的原尺寸區域 OCR，保持獨立 review workspace。`ocr_cache.py` 為區域 OCR 及 `profile_stage.py` 的上游 quick_ocr 轉接提供持久快取：只有解碼像素完全一致才共用辨識，模型／設定變動會失效，失敗結果不保存。原上游 checkout 不需修改。

重用規則（皆不降低取樣頻率、解析度或辨識設定）：

- **單次影片解碼**：`scan_slide_changes.scan(..., base_frames=...)` 以一個 FFmpeg 解碼同時輸出每秒 320×224 探針與每五秒 960 寬基礎畫面。兩種 fps 濾鏡都取各時槽之前最後一格，已驗證與舊 `fps=1/5` 擷取逐位元組相同（含 29.97 fps 與非五秒倍數尾端）。成功後才寫 `shared-decode/extraction.json`；中斷時清掉殘留畫面重解。原尺寸畫面只對換頁邊界、最後一個探針（影片尾端）與局部 OCR 補抓。
- **原稿特徵索引**：同次執行的五秒配對與邊界補抓共用 `SharedMatcher`，全部命中 checkpoint 時不建立。頁面 ORB 特徵存於 `data/cache/deck-features/`（`--feature-cache` 可改），鍵含原稿／呈現 PDF hash、頁數、960 寬灰階、ORB 參數、`FEATURE_VERSION` 與 OpenCV／PyMuPDF 版本，檔內再比對簽章與內容 hash；損壞或不符即重建。
- **裁切產物**：`crops/<key>.png` 以來源畫面 hash、原尺寸座標、影片座標、畫布、padding 與 `CROP_VERSION` 定址，旁附 receipt 保存像素識別；未變更時不解碼來源、不重寫，OCR 快取直接用該識別。同次執行以 `RunFacts` 共用檔案 hash，解碼後的來源畫面最多留兩張。
- `status.json` 的 `work` 列出完整解碼、Matcher／頁面特徵、邊界畫面、裁切與 OCR 呼叫／命中次數及各階段秒數。

快取完整性：`frame_cache.py` 在共用掃描續跑及獨立頁面對齊時檢查 extraction receipt 的張數、連續檔名與每張圖片 SHA-256；缺檔、多檔、改名、圖片被修改或舊 receipt 缺少完整性清單時，明確停止並要求新輸出目錄，不重新編排剩餘畫面的時間。裁切 receipt 的 checksum 包含來源／座標 identity、圖片 hash 與像素識別；缺少欄位、舊格式或 checksum 不符時重新裁切，再使用正確的像素識別查 OCR 快取。這是損壞偵測，不是對抗可同時改寫內容及 checksum 的簽章機制。回歸案例在 `tests/test_cache_integrity.py`。

`tests/test_visual_efficiency.py` 驗證單次解碼等同舊擷取、短暫頁面、回頁、微小註記與擦除、尾端註記、相同頁面保持 ambiguous、特徵快取損壞／換檔失效、裁切 receipt 損壞與版本失效、中斷續跑及記憶體上限。`tests/test_visual_pipeline.py` 驗證重複 OCR 呼叫數、微小變化隔離、失敗重試、座標換算、輸入版本、前後裁切保存與正式 CLI。這些測試不代表手寫辨識準確率或短暫畫面召回率已驗收。

`deck_alignment.py` 讀取原始投影片與呈現用 PDF 的 hash 登錄檔，以五秒畫面建立頁面候選。它不呼叫 OCR／VLM，不改寫正式來源證據。`--existing` 可改用既有全部畫面出現紀錄；`--frame-cache` 重用已驗證影片 hash 與取樣間隔的擷取結果。輸出包含逐筆 checkpoint、候選排名、幾何轉換及 ambiguous/unmatched 狀態。

此工具仍需課程實例驗證：候選區間邊界不是精確換頁時間，原始頁面的最終動畫狀態也不能取代影片當下畫面。測試 `tests/test_deck_alignment.py` 保護不確定配對與回看保存；語意及動畫核對另做。參閱 [ADR 0003](architecture/adr/0003-deck-assisted-visual-evidence.md)。

目前正式驗收環境是 Windows、Python 3.12 與 Node.js；其他平台尚未驗收。原始碼測試不需要 GPU、影片、模型或 Ollama。

## 最小開發環境

將官方可攜版 uv 放到 `tools/uv/uv.exe`，並在專案根目錄執行下列 PowerShell 指令。已有 `.venv` 時直接使用，不必重建。Python 套件只安裝在本專案 `.venv`。

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD 'tools/uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD 'tools/python'
$env:UV_PYTHON_BIN_DIR = Join-Path $PWD 'tools/python-bin'
$env:UV_TOOL_DIR = Join-Path $PWD 'tools/uv-tools'
.\tools\uv\uv.exe venv --python 3.12 --managed-python .venv
.\tools\uv\uv.exe pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
```

取得 uv 請參閱 [官方安裝文件](https://docs.astral.sh/uv/getting-started/installation/)。以上設定只作用於目前終端及其子行程，不需要改全域 PATH、PowerShell 執行原則或 Miniconda base。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
node --check reader.js
node --test tests/reader_playback.test.cjs tests/reader_sync.test.cjs tests/reader_resize.test.cjs tests/reader_transcript.test.cjs tests/reader_continuous.test.cjs
```

沒有本機課程匯出與上游 checkout 時，對應整合測試會明確跳過；其餘時間對齊、逐字稿保存、HTTP 媒體範圍回應及閱讀器邏輯測試可以獨立執行。這些測試不表示已完整驗收模型或瀏覽器。

## 選用的完整處理環境

`requirements.lock.txt` 是目前 Windows／CUDA 工作環境的完整鎖版清單，包含大型模型推論相依，並非最小開發需求。需要重現處理管線時才安裝到 `.venv`：

```powershell
.\tools\uv\uv.exe pip install --python .venv/Scripts/python.exe -r requirements.lock.txt
git clone https://github.com/drpwchen/lecture-to-notes.git vendor/lecture-to-notes
$upstreamRevision = (Get-Content upstream-commit.txt -Raw).Trim()
git -C vendor/lecture-to-notes checkout --detach $upstreamRevision
```

已有上游目錄時不要重新 clone 或重設使用者的變更。`vendor/` 是獨立、未納入本專案的 checkout；保留其授權。FFmpeg、可攜 Ollama 與模型需另外準備，未包含於此原始碼。

資工 VLM／grounding 使用 `run.py` 載入 `profile_stage.py` 與 `profiles/computer-science/`，不得直接繞過預設執行上游腳本。模型推論依序執行，工作結束停止本專案 Ollama。

`build_reader.py` 與 `serve_reader.py` 共用課程 JSON 設定，詳見 [課程設定](courses.md)。執行 `examples/demo/create_demo.py` 可在無模型／上游環境中產生可閱讀的公開示範。完整環境可使用 [課程任務 CLI](overnight.md) 串接下載、辨識、分批講義、校正及匯出；預設使用本機 Ollama，不需要雲端 API 憑證。

## 元件與資料流

| 元件 | 工作 |
|---|---|
| `vendor/lecture-to-notes` | 保留的上游原始碼與授權 |
| `run.py`、`profile_stage.py` | 專案環境與上游轉接，不直接改上游 |
| `profiles/computer-science` | 資工提示詞、術語與筆記規格 |
| `build_cs_deliverable.py`、`cs_timeline.py` | 出現區間、講稿歸屬及時間軸 |
| `course_config.py`、`build_reader.py`、`reader.js`、`reader.css` | 課程設定與共用閱讀介面 |
| `output/.../transcript*.json` | 原始轉錄、校正版與修訂紀錄 |
| `output/.../reading_alignment.json` | 講義段落與逐字稿對照 |

新增依賴只使用 `.venv`；不修改原本 Python、全域 PATH、顯卡驅動或系統服務。`run.py` 將模型與工具快取限制在專案。先完成語音推論，再啟動視覺階段；使用完停止專案 Ollama。

## 閱讀器驗收範圍

已在 Chrome 的本機 HTTP 頁面驗收單句／段落聲音、影片及同步，並檢查手機與低高度視窗。實體觸控與人工尾音聽感仍待確認。公開示範的首次環境建立與驗收紀錄見 [公開準備狀態](open-source-readiness.md)。
