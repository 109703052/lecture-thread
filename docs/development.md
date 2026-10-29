# 開發與測試

本頁對應 README 的第二種情境：**沒有 GPU、模型、Ollama、上游 checkout 或私人課程，也能開發與執行測試**。只想開啟閱讀器示範時，見 [公開示範入門](quickstart.md)；完整課程處理見後段「選用的完整處理環境」。

目前驗收平台是 Windows x64、PowerShell、Python 3.12 與 Node.js 24；其他平台尚未驗收。

## 先決條件

| 工具 | 用途 | 取得方式 |
|---|---|---|
| uv 可攜版 | 下載專案專用 Python 3.12、建立 `.venv`、安裝依賴 | 依 [uv 官方安裝文件](https://docs.astral.sh/uv/getting-started/installation/) 取得 Windows x64 `uv.exe`，放到 `tools/uv/uv.exe`。CI 使用 uv 0.13.3 |
| Node.js 24 | `reader.js` 語法檢查與閱讀器 Node 測試 | [Node.js 官方下載](https://nodejs.org/)。CI 使用 24.15.0，較舊版本未驗證 |
| FFmpeg／ffprobe | 以合成影片測試抽圖、換頁掃描與比較畫面 | [FFmpeg 官方下載頁](https://ffmpeg.org/download.html) 列出的 Windows 版本。CI 使用 8.0.1（gyan.dev release build） |

FFmpeg 不必加到全域 PATH；只在目前 PowerShell 加入即可，關閉視窗後失效：

```powershell
$env:PATH = 'C:\path\to\ffmpeg\bin;' + $env:PATH
ffmpeg -version
ffprobe -version
```

沒有 FFmpeg 時，合成影片測試會以「ffmpeg unavailable」等明確原因跳過，其餘測試照常執行。

## 建立開發環境

在專案根目錄的 PowerShell 執行。這些設定只作用於目前終端及其子行程，不需要改全域 PATH、PowerShell 執行原則或使用其他 Python／Conda 環境；Python 與套件都留在本專案的 `tools/` 與 `.venv/`（皆被 Git 忽略）。已有 `.venv` 時直接安裝依賴即可，不必重建。

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD 'tools/uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD 'tools/python'
$env:UV_PYTHON_BIN_DIR = Join-Path $PWD 'tools/python-bin'
$env:UV_TOOL_DIR = Join-Path $PWD 'tools/uv-tools'
.\tools\uv\uv.exe venv --python 3.12 --managed-python .venv
.\tools\uv\uv.exe pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
```

`requirements-dev.txt` 只列測試與其匯入的正式模組實際需要的套件，版本與 `requirements.lock.txt` 相同，並以該檔作為 constraint 固定間接依賴；不會安裝 Whisper、CUDA 套件或下載模型。

| 套件 | 用途 |
|---|---|
| pytest | 測試執行 |
| numpy、opencv-python、pillow、pymupdf | 原稿頁面配對、換頁掃描、比較畫面、裁切與測試用合成圖片／PDF。PyMuPDF 2.0 會連帶安裝 onnxruntime（CPU 版）等套件 |
| psutil | 任務管線與專案 Ollama 管理的程序核對 |
| pyyaml | 資工 profile 轉接器 `profile_stage.py` |
| opencc-python-reimplemented | 逐字稿繁體中文正規化 |

## 執行測試（與 CI 相同）

```powershell
.\.venv\Scripts\python.exe examples/demo/create_demo.py
.\.venv\Scripts\python.exe examples/demo/verify_demo.py
.\.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider -rs
node --check reader.js
node --test "tests/*.test.cjs"
```

先產生示範，可讓以示範課程為資料的閱讀對照整合測試一併執行。`-rs` 會列出每個跳過項目及原因。`node --test "tests/*.test.cjs"` 由 Node 自行展開，涵蓋 `tests/` 內全部閱讀器測試檔。

若本機暫存目錄無法寫入，可另加 `--basetemp=data/tmp/pytest`（`data/` 被 Git 忽略）。

### 測試分類

| 類別 | 條件 | 內容 |
|---|---|---|
| 一般開發測試 | 只需 `requirements-dev.txt` | 課程設定、閱讀器建置、逐字稿與人工修訂保存、HTTP 媒體範圍、任務管線狀態與鎖、原稿配對、差異比較、OCR／裁切／畫面快取完整性等；以及全部 Node 閱讀器測試 |
| 合成影片測試 | 另需 FFmpeg／ffprobe | `tests/test_comparison_frames.py`、`tests/test_visual_efficiency.py` 的 FFmpeg 案例、`tests/test_lecture_pipeline.py` 的抽圖案例。以程式產生的短片驗證，不使用真實課程 |
| 選用整合測試 | 需要上游 checkout 或本機課程匯出 | `tests/test_cs_profile.py`、`tests/test_visual_pipeline.py` 的上游 quick_ocr 案例、`tests/test_viewer_sync.py`。原始碼不含這些資料，會明確跳過 |

設定環境變數 `LECTURETHREAD_REQUIRE_FFMPEG=1` 時（CI 使用），缺少 FFmpeg／ffprobe 會直接失敗，任何因 FFmpeg 跳過的測試也會讓測試結果變成失敗，避免合成影片測試靜默略過。

`tests/test_reading_alignment.py` 的整合案例讀取預設課程：有私有 `course.local.json` 時是該課程，否則是公開示範；兩者都尚未建置時才跳過。

這些測試不代表已驗收模型輸出、手寫辨識、實際瀏覽器操作或聲音品質。

## 持續整合（GitHub Actions）

`.github/workflows/ci.yml` 在 push、pull request 及手動執行時，於 `windows-2025` runner 執行：

1. 安裝固定版本的 uv（0.13.3）、Node.js（24.15.0）與 FFmpeg 8.0.1（Chocolatey 套件），並印出版本。
2. 以 uv 建立 Python 3.12 `.venv`，只安裝 `requirements-dev.txt`，列出已安裝套件並確認是虛擬環境。
3. 產生公開示範，並以 `examples/demo/verify_demo.py` 檢查閱讀頁、內嵌資料、投影片與音訊。
4. 執行 pytest（`-rs` 列出跳過原因；`LECTURETHREAD_REQUIRE_FFMPEG=1`）。
5. `node --check reader.js` 與全部 Node 測試。

工作流程只有 `contents: read` 權限，不使用 secret，checkout 不保存憑證。外部 Actions 以 commit SHA 固定，旁註版本：actions/checkout v7.0.1、astral-sh/setup-uv v10.3.3、actions/setup-node v7.1.0。只快取 uv 的套件下載（以兩個 requirements 檔為鍵）；示範產物、課程、模型與上游 checkout 每次都不存在，也不快取。CI 不需要 GPU、Ollama、模型、私人課程、個人憑證或 vendor。

更新 Actions 版本時，請從各 Action 的官方 release 取得新 tag 對應的 commit SHA，一併更新註解。

## 選用的完整處理環境

這是 README 的第三種情境，需要額外工具與模型，CI 不涵蓋。`requirements.lock.txt` 是目前 Windows／CUDA 工作環境的完整鎖版清單，包含大型模型推論相依，並非開發測試需求。需要重現處理管線時才安裝到 `.venv`：

```powershell
.\tools\uv\uv.exe pip install --python .venv/Scripts/python.exe -r requirements.lock.txt
git clone https://github.com/drpwchen/lecture-to-notes.git vendor/lecture-to-notes
$upstreamRevision = (Get-Content upstream-commit.txt -Raw).Trim()
git -C vendor/lecture-to-notes checkout --detach $upstreamRevision
```

已有上游目錄時不要重新 clone 或重設使用者的變更。`vendor/` 是獨立、未納入本專案的 checkout；保留其授權。FFmpeg、CUDA GPU、可攜 Ollama 與模型需另外準備，未包含於此原始碼。有上游 checkout 時，前述選用整合測試中需要上游的部分會執行。

資工 VLM／grounding 使用 `run.py` 載入 `profile_stage.py` 與 `profiles/computer-science/`，不得直接繞過預設執行上游腳本。模型推論依序執行，工作結束停止本專案 Ollama。

`build_reader.py` 與 `serve_reader.py` 共用課程 JSON 設定，詳見 [課程設定](courses.md)。執行 `examples/demo/create_demo.py` 可在無模型／上游環境中產生可閱讀的公開示範。

### 三條處理路線

目前三條路線分開執行，彼此不會自動銜接。操作細節見 [睡前處理一堂課](overnight.md)。

| 路線 | 入口 | 做什麼 | 不做什麼 |
|---|---|---|---|
| 舊整夜路線 | `lecture.cmd prepare`／`start`／`status`／`resume`／`serve` | 下載或讀取影片、Whisper 轉錄、每 2 秒抽圖、OCR、VLM、grounding、本機文字模型分批寫講義初稿、建置閱讀頁與待核對清單；可背景執行與失敗續跑 | 不使用原始投影片，也不使用 `visual` 的配對、比較畫面或快取；講義為待抽查的 AI 初稿 |
| 原始投影片核對 | `lecture.cmd visual --job ... --references ... --out ... [--ocr-regions]` | 對既有任務的影片與原稿做頁面配對、換頁補抓、局部差異與選用的區域 OCR，輸出獨立核對資料 | 不啟動 Ollama，不改寫正式證據，不撰寫或發布講義；完成狀態是 `review_required` |
| 直接撰寫與發布 | `editorial_publish.py --course ...`（`--check` 只驗證） | 讀取 AI 助理依 [講義規格](../profiles/computer-science/note-spec.md) 直接撰寫的 `editorial_chapters.json`，驗證來源與時間後建置閱讀頁 | 不呼叫任何模型；撰寫本身不是自動化步驟 |

## 原始投影片核對的實作細節

### 原始投影片配對（候選層）

正式整合入口為 `lecture.cmd visual --job ... --references ... --out ... [--ocr-regions]`，見 [操作說明](overnight.md)。`visual_pipeline.py` 串接頁面配對、換頁補抓、局部差異與選用的原尺寸區域 OCR，保持獨立 review workspace。`ocr_cache.py` 為區域 OCR 及 `profile_stage.py` 的上游 quick_ocr 轉接提供持久快取：只有解碼像素完全一致才共用辨識，模型／設定變動會失效，失敗結果不保存。原上游 checkout 不需修改。

重用規則（皆不降低取樣頻率、解析度或辨識設定）：

- **單次影片解碼**：`scan_slide_changes.scan(..., base_frames=...)` 以一個 FFmpeg 解碼同時輸出每秒 320×224 探針與每五秒 960 寬基礎畫面。兩種 fps 濾鏡都取各時槽之前最後一格，已驗證與舊 `fps=1/5` 擷取逐位元組相同（含 29.97 fps 與非五秒倍數尾端）。成功後才寫 `shared-decode/extraction.json`；中斷時清掉殘留畫面重解。原尺寸畫面只對換頁邊界、最後一個探針（影片尾端）與局部 OCR 補抓。
- **原稿特徵索引**：同次執行的五秒配對與邊界補抓共用 `SharedMatcher`，全部命中 checkpoint 時不建立。頁面 ORB 特徵存於 `data/cache/deck-features/`（`--feature-cache` 可改），鍵含原稿／呈現 PDF hash、頁數、960 寬灰階、ORB 參數、`FEATURE_VERSION` 與 OpenCV／PyMuPDF 版本，檔內再比對簽章與內容 hash；損壞或不符即重建。
- **裁切產物**：`crops/<key>.png` 以來源畫面 hash、原尺寸座標、影片座標、畫布、padding 與 `CROP_VERSION` 定址，旁附 receipt 保存像素識別；未變更時不解碼來源、不重寫，OCR 快取直接用該識別。同次執行以 `RunFacts` 共用檔案 hash，解碼後的來源畫面最多留兩張。
- **差異比較畫面**：同一次解碼另以單一縮放器輸出 960 寬無損 PNG（`shared-decode/compare/`），只保留五秒樣本、換頁事件前後與後一秒、最後一個探針，其餘邊解碼邊刪除。`alignment.json` 每筆觀察記錄 `comparison_image`／`comparison_sha256`／`comparison_slot`，`deck_differences` 兩側都有才用它比較（schema 4，事件另記 `before_compared`／`after_compared`）。配對仍用原本的五秒 JPEG 與原尺寸 seek 畫面，OCR 仍裁切原尺寸畫面。比較畫面的清單與 SHA-256 存在 `extraction.json` 的 `comparison`，續跑時缺檔、多檔、修改或舊 receipt 皆明確停止；缺少某觀察的比較畫面也停止，不退回混用來源。此修正未調整差異門檻、模糊或面積過濾。
- `status.json` 的 `work` 列出完整解碼、Matcher／頁面特徵、邊界畫面、裁切與 OCR 呼叫／命中次數及各階段秒數。

快取完整性：`frame_cache.py` 在共用掃描續跑及獨立頁面對齊時檢查 extraction receipt 的張數、連續檔名與每張圖片 SHA-256；缺檔、多檔、改名、圖片被修改或舊 receipt 缺少完整性清單時，明確停止並要求新輸出目錄，不重新編排剩餘畫面的時間。裁切 receipt 的 checksum 包含來源／座標 identity、圖片 hash 與像素識別；缺少欄位、舊格式或 checksum 不符時重新裁切，再使用正確的像素識別查 OCR 快取。這是損壞偵測，不是對抗可同時改寫內容及 checksum 的簽章機制。回歸案例在 `tests/test_cache_integrity.py`。

`tests/test_comparison_frames.py` 以合成 H.264 影片重現五秒 JPEG 對 seek 原尺寸畫面的假差異，驗證比較畫面與 1 fps 探針同一格、只保留需要的時槽、比較畫面損壞或舊 receipt 被拒，以及完整流程中靜止配對不再產生事件，同時保留小負號寫上、擦除與逐步出現的文字。舊版程式在最後一項會多出 15→16 秒的假事件。

`tests/test_visual_efficiency.py` 驗證單次解碼等同舊擷取、短暫頁面、回頁、微小註記與擦除、尾端註記、相同頁面保持 ambiguous、特徵快取損壞／換檔失效、裁切 receipt 損壞與版本失效、中斷續跑及記憶體上限。`tests/test_visual_pipeline.py` 驗證重複 OCR 呼叫數、微小變化隔離、失敗重試、座標換算、輸入版本、前後裁切保存與正式 CLI。這些測試不代表手寫辨識準確率或短暫畫面召回率已驗收。

`deck_alignment.py` 讀取原始投影片與呈現用 PDF 的 hash 登錄檔，以五秒畫面建立頁面候選。它不呼叫 OCR／VLM，不改寫正式來源證據。`--existing` 可改用既有全部畫面出現紀錄；`--frame-cache` 重用已驗證影片 hash 與取樣間隔的擷取結果。輸出包含逐筆 checkpoint、候選排名、幾何轉換及 ambiguous/unmatched 狀態。

此工具仍需課程實例驗證：候選區間邊界不是精確換頁時間，原始頁面的最終動畫狀態也不能取代影片當下畫面。測試 `tests/test_deck_alignment.py` 保護不確定配對與回看保存；語意及動畫核對另做。參閱 [ADR 0003](architecture/adr/0003-deck-assisted-visual-evidence.md)。


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
