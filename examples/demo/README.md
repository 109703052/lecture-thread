# 原創公開示範：堆疊與佇列

此資料集由 LectureThread 專案自行撰寫與繪製，依 repository 的 MIT 授權散布，不含原本實際課程的影片、投影片或逐字稿。

示範有 3 個投影片出現區間、6 個閱讀段落及 6 段示範文字，共 36 秒。最後一頁回看 stack，加入操作成本註記；這次出現與第一頁分開保留。

## 開啟

第一次使用、尚未建立 `.venv` 時，請先依 [公開示範入門](../../docs/quickstart.md) 準備環境。

在專案根目錄執行，使用既有 `.venv` 即可，不需要模型、GPU、上游 checkout、FFmpeg 或額外 Python 套件：

```powershell
.\.venv\Scripts\python.exe examples/demo/create_demo.py
.\.venv\Scripts\python.exe serve_reader.py --course courses/demo.json --port 8767
```

開啟 <http://127.0.0.1:8767/index.html>。關閉服務使用 Ctrl+C。

**音訊是程式自行產生的低音量提示音，並非口語教學。** 逐字稿欄中的文字是原創教學腳本，不是由這個音檔做語音辨識得到。三個章節使用不同音高，供驗證單句／段落停止、任意 seek 與連續跨章同步；這個音訊示範沒有影片，因此「觀看影片」停用，也不顯示 YouTube 連結。

`create_demo.py` 只寫入被 Git 忽略的 `output/demo/`。文字與 SVG 原始教材在此目錄；WAV、閱讀 HTML、對齊結果、草稿及手動修訂不納入公開原始碼。重跑會保留既有人工修訂；來源教材與本機示範拷貝不一致時會報錯，避免覆寫本機變更。

自行換課程時請建立其他課程設定檔，不要修改公開 demo 設定讓它指向私有課程。
