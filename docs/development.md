# 開發與測試

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

`build_reader.py` 與 `serve_reader.py` 共用課程 JSON 設定，詳見 [課程設定](courses.md)。執行 `examples/demo/create_demo.py` 可在無模型／上游環境中產生可閱讀的公開示範；實際課程的匯入、辨識與講義撰寫仍需另外完成。

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
