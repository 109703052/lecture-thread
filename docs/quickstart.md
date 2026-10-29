# 開啟公開示範

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

示範生成的音訊、HTML 與修訂皆留在被忽略的 `output/demo/`；原創教材與產生器位於 [examples/demo](../examples/demo/README.md)。要確認建置結果完整，可另外執行 `.\.venv\Scripts\python.exe examples/demo/verify_demo.py`，它會檢查閱讀頁、內嵌資料、三張投影片與 36 秒音訊，CI 也執行同一檢查。

這是三種使用情境中最輕的一種。要修改程式或執行測試，請改看 [開發與測試](development.md)，那裡需要另外安裝開發依賴、Node.js 與 FFmpeg。

操作方式見 [閱讀器使用說明](reader-guide.md)。準備自己的課程前，請先閱讀 [課程設定與必要輸入](courses.md)。

[返回專案介紹](../README.md)
