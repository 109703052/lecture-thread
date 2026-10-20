# LectureThread／課脈

串起投影片與講解，沿著老師的思路讀懂課程。

目前為持續開發中的 Windows 本地研究原型。歡迎從 [開發與測試](docs/development.md) 開始；參與方式見 [CONTRIBUTING.md](CONTRIBUTING.md)。公開原始碼包含自行撰寫的示範教材與產生器，不包含實際課程資料、模型或已產生的閱讀頁。

LectureThread 是基於 **[lecture-to-notes](https://github.com/drpwchen/lecture-to-notes)** 的課程閱讀工具。上游作者 **drpwchen 及其貢獻者**提供影片轉錄、投影片擷取、OCR、去重、對齊與筆記匯出的重要基礎；本專案在此之上新增閱讀體驗及資工領域整理。完整來源與貢獻見 [NOTICE.md](NOTICE.md)，MIT 授權全文見 [LICENSE](LICENSE)。上游版本記錄於 [upstream-commit.txt](upstream-commit.txt)。

## 閱讀與學習

- 投影片與總整理左右並排（預設 45%／55%）；章節導航由左側浮標移入展開（點擊可固定），校正逐字稿從底部展開並可拖曳上緣調整高度。
- 捲動或點選講義，標亮對應原句；點原句返回講義。
- 逐字稿可跳到影片時間，選擇頁內播放或 YouTube。
- 逐字稿旁「聽此句」、講義段落旁「聽此段」直接在文字下方播放聲音，保留閱讀位置與投影片，不切換手機面板。點逐字稿文字仍只返回講義；「觀看影片」是另一個獨立按鈕。
- 聽一句／一段或觀看影片先播放所選來源範圍，尾端加 0.3 秒緩衝後自動暫停。再次按播放器的播放鍵會接續往下聽；手動拖曳進度條會切換成自由播放，可跳到整部媒體的任意時間。自由播放跨章或跳轉時，投影片、總整理與逐字稿同步跟隨，保留原播放器不中斷。重新點「聽此句／此段」或「觀看影片」會開始新的範圍播放。可用停止按鈕或 Esc 收起播放器。
- 投影片依原始比例自動適應區域，可顯示／隱藏，並可一鍵放大查看細節。
- 拖曳左右分隔線調整區域比例；總整理獨立捲動並切換對應投影片。手機改為上下對照。投影片比例、逐字稿高度與展開／收合狀態會依課程儲存在目前瀏覽器，重新整理或下次開啟同一網址時恢復；清除網站資料、換瀏覽器或換網址的主機／port 不會沿用。
- 保留原始轉錄、校正版及修訂紀錄，對數字矛盾與無法確認的詞標示待核對。
- 逐字稿每句可編輯、儲存或取消；透過本機服務按儲存會直接寫入課程的 `transcript.manual-edits.json`，原始 ASR 與 AI 校正版保持不變。多分頁版本衝突會保留草稿並顯示最新文字，比較後才能明確重試。
- 未儲存草稿與衝突狀態保留於目前分頁，重新整理可恢復；關閉分頁前請先儲存或匯出。舊版瀏覽器修訂會轉成待確認草稿，不會自動寫入正式檔案。
- 聽一句／一段時，逐字稿區以綠色及「正在播放」標示目前原句；原有黃色仍表示講義來源。跟隨開啟時只捲動逐字稿區，編輯中暫停自動捲動；暫停或結束會清除播放標記。

## 開啟公開示範

以下步驟以 **Windows x64、PowerShell** 為準。下載原始碼 ZIP 並解壓縮後，先在解壓縮的專案根目錄開啟 PowerShell；不要在 ZIP 內直接執行。

先從 [uv 官方安裝文件](https://docs.astral.sh/uv/getting-started/installation/) 取得 Windows x64 可攜版 `uv.exe`，放到專案的 `tools/uv/uv.exe`（自行建立資料夾）。uv 與 Python 不包含在原始碼 ZIP；第一次建立 Python 環境需要網路連線。示範本身不需要模型、GPU、FFmpeg、Node.js 或任何額外 Python 套件。

第一次開啟時，在專案根目錄依序執行：

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD 'tools/uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD 'tools/python'
$env:UV_PYTHON_BIN_DIR = Join-Path $PWD 'tools/python-bin'
$env:UV_TOOL_DIR = Join-Path $PWD 'tools/uv-tools'
.\tools\uv\uv.exe venv --python 3.12 --managed-python .venv
.\.venv\Scripts\python.exe examples/demo/create_demo.py
.\.venv\Scripts\python.exe serve_reader.py --course courses/demo.json --port 8767
```

已有這個專案的 `.venv` 時，可略過環境建立，只執行最後兩行。服務啟動後請保留 PowerShell 視窗，結束時按 Ctrl+C。若 8767 已被其他服務占用，將最後一行的 `--port 8767` 改成 `--port 8768`，並使用對應 port 的網址。

開啟 <http://127.0.0.1:8767/index.html>。此原創示範介紹 stack／queue，包含回頁與新增註記，共 36 秒。**聲音為合成提示音，逐字稿是教學腳本，沒有口語旁白或影片。** 可操作投影片／講義對照、播放、任意跳轉、跨章同步及人工校字保存。

示範生成的音訊、HTML 與修訂皆留在被忽略的 `output/demo/`；原創教材與產生器位於 [examples/demo](examples/demo/README.md)。

## 載入自己的課程

建置器與服務共用 `--course` 設定檔，不需複製或修改閱讀器程式。根目錄 `course.local.json` 與 `courses/*.local.json` 僅留本機，已排除於 Git；課程格式與欄位見 [課程設定](docs/courses.md)。

```powershell
.\.venv\Scripts\python.exe build_reader.py --course course.local.json
.\.venv\Scripts\python.exe serve_reader.py --course course.local.json --port 8766
```

不傳設定時，優先使用 `course.local.json`，否則使用公開 demo 設定。服務僅監聽 loopback，一次載入一個課程，提供本地修訂保存及媒體 byte-range 定位。原本已完成的本機課程可以沿用原有檔案與網址；不會被複製到公開 demo。

## 目前完成與限制

- 已完成閱讀介面、課程設定檔及可在本機生成的公開示範；開發者的既有完整課程維持本機使用。
- 講義撰寫與校正仍由 AI 助手協助，**尚未做成貼 YouTube 網址即可全自動產生筆記的服務**。
- 講義與逐字稿依時間區間對照，不是逐句語意對齊；切頁時間為抽樣估計。
- 已在 Chrome 的本機 HTTP 頁面驗收單句／段落聲音、影片、同步及舊版尺寸控制，並檢查手機與低高度視窗。實體觸控與人工尾音聽感仍待確認。

## 架構與維護

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

## 接下來的工作

- 為公開示範加入可散布的口語旁白與影片素材。
- 將講義生成及校正做成可重跑的獨立步驟。
- 建立乾淨環境的端到端安裝與瀏覽器驗收。

## 致謝與授權

本專案保留 lecture-to-notes 的作者、來源、版本及 MIT 聲明。新增功能與上游貢獻的區分見 [NOTICE.md](NOTICE.md)。課程素材及第三方依賴各自適用原有權利與授權。
