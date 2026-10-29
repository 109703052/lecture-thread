# 參與 LectureThread／課脈

歡迎提出閱讀體驗、資工課程處理與資料品質方面的 issue 或 pull request。

請先讀 [README](README.md)、[開發與測試](docs/development.md) 及 [來源與授權](NOTICE.md)。目前是 Windows 本地研究原型，提供可在本機產生的原創示範；尚未提供任意影片的一鍵處理，舊整夜路線、原始投影片核對與直接撰寫發布也還是分開的流程。

## 回報問題

請提供作業系統、Python／Node 版本、重現步驟、預期與實際結果。介面問題可附不含個資或未授權素材的截圖。可使用自行撰寫的小型 JSON 或匿名化資料重現，請勿上傳老師的完整課程、學生資料、存取權杖或模型權重。

## 開發環境與測試

依 [開發與測試](docs/development.md) 建立專案內的 `.venv` 並安裝 `requirements-dev.txt`；不需要 GPU、模型、Ollama、上游 checkout 或私人課程。合成影片測試需要 FFmpeg／ffprobe，閱讀器測試需要 Node.js 24。提交前請在專案根目錄執行與 CI 相同的檢查：

```powershell
.\.venv\Scripts\python.exe examples/demo/create_demo.py
.\.venv\Scripts\python.exe examples/demo/verify_demo.py
.\.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider -rs
node --check reader.js
node --test "tests/*.test.cjs"
```

Pull request 會由 GitHub Actions 在 Windows 上執行同一組檢查。只有需要上游 checkout 或本機課程匯出的選用整合測試可以跳過；請不要以 `importorskip`、排除測試或放寬斷言讓結果通過。

## 提交變更

1. 每個變更集中處理一件事，說明使用者遇到的問題與修正後的行為。
2. 閱讀器請修改 `reader.js`、`reader.css`、`build_reader.py`，不要只修改產出的 HTML。
3. 執行上述測試；同步／播放修改需檢查句尾暫停、任意 seek、連續跨章與不重建播放器。
4. UI 修改附桌面與窄視窗驗收結果；測試模擬不能代替實際聲音／影片驗收。
5. 新增 Python 依賴時，開發測試需要的加入 `requirements-dev.txt` 並與 `requirements.lock.txt` 版本一致；只有完整處理才需要的不要加入開發依賴。
6. 不提交 `data/`、`output/`、`models/`、`tools/`、`.venv/` 或 `vendor/`。保持原始逐字稿不變，校正另存。

請保留上游作者及 MIT 聲明，並標明新增的第三方程式或素材來源。提交的變更應可依本專案 [MIT 授權](LICENSE) 散布；提交前請確認你有權提供內容。
