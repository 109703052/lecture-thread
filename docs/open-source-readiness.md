# 公開原始碼準備狀態

## 目前狀態

核對日期：2026-10-29。

- 原始碼已公開於 GitHub。課程影音、模型、產生的閱讀頁、私有課程設定與本機開發歷史都不在 repository 內。
- 同一份程式碼支援本機課程與公開示範，建置器及本地服務均使用課程 JSON 設定。
- 公開示範採自行製作的 stack／queue 文字與 SVG，含回頁註記。36 秒合成提示音由標準函式庫在本機產生；逐字稿是預先撰寫的教學腳本。**沒有口語旁白或影片，不是語音辨識或自動講義品質的示範。**
- 開發依賴 `requirements-dev.txt` 涵蓋所有一般開發測試需要的套件，不含模型推論或 GPU 環境；完整處理仍使用 `requirements.lock.txt`、上游 checkout、FFmpeg、可攜 Ollama 與模型。
- `.github/workflows/ci.yml` 在 Windows 上建立乾淨環境、安裝 FFmpeg、產生並檢查示範、執行 Python 與 Node 測試。下方的本機驗收不代表 GitHub Actions 已通過；實際結果以 repository 的 Actions 頁面為準。
- 完整課程處理仍是三條分開的路線：舊整夜路線 `start`／`resume`、原始投影片核對 `visual`，以及直接撰寫後以 `editorial_publish.py` 發布。`start`／`resume` 不會使用 `visual` 的配對與比較結果，尚無一鍵完成的流程。
- MIT 授權保留原上游聲明，另列 LectureThread contributors；NOTICE 說明雙方貢獻。

## 目前驗收（2026-10-29）

條件：

- 以 Git 追蹤檔案加上本輪新增的 CI 設定、`tests/conftest.py` 與 `examples/demo/verify_demo.py`，共 103 個檔案，建立獨立原始碼副本。副本沒有 `.venv`、`vendor/`、`data/`、`output/`、`tools/`、模型或私有課程設定。
- 只放入 uv 0.13.3 執行檔；uv 快取、Python 安裝與虛擬環境都在副本內重新建立，Python 3.12.15 重新下載。清除 `PYTHONPATH`、`PYTHONHOME`、`VIRTUAL_ENV` 等變數；以 `python -I` 確認 `sys.path` 只有副本內的 Python 與 `.venv`，各套件皆從副本 `.venv` 載入。
- Windows 11 x64、Node.js 24.15.0、FFmpeg／ffprobe 8.0.1（gyan.dev 版本，只在該終端的 PATH），並設定 `LECTURETHREAD_REQUIRE_FFMPEG=1`。
- 依序執行與 CI 相同的命令（見 [開發與測試](development.md)）。

結果：

| 項目 | 結果 |
|---|---|
| 公開示範（未安裝任何第三方套件的虛擬環境） | 產生成功，`verify_demo.py` 通過：4 個導覽項目、6 句逐字稿、36 秒音訊 |
| 開發依賴安裝 | 20 個套件，版本與 `requirements.lock.txt` 一致 |
| pytest | 136 passed、3 skipped；合成影片測試全部執行 |
| 跳過原因 | `test_cs_profile.py`、`test_visual_pipeline.py` 的上游 quick_ocr 案例：沒有上游 checkout；`test_viewer_sync.py`：沒有本機課程匯出與上游 checkout |
| `node --check reader.js` | 通過 |
| Node 閱讀器測試（`tests/*.test.cjs`，9 個檔案） | 74 passed |
| 移除 FFmpeg 後 | 未設定 `LECTURETHREAD_REQUIRE_FFMPEG` 時 129 passed、10 skipped（7 項以 FFmpeg 為原因）；設定後 pytest 直接以錯誤結束 |

未涵蓋：GitHub Actions 的實際執行（含 Chocolatey 安裝 FFmpeg 的步驟）、其他作業系統、全新 Windows 虛擬機、瀏覽器互動、聲音品質、模型推論與完整課程處理。

## 後續工作

- 補原創口語旁白及可散布影片，使示範涵蓋完整影片體驗。
- 完整模型管線在全新機器上的依賴重建驗收。
- 把原始投影片核對結果接進正式證據與撰寫流程；任意影片的一鍵工作流程。

## 歷史紀錄（2026-10-21）

以下保留當時的驗收紀錄。測試數量、「尚未建立 GitHub repository」等描述是當時狀態，已由上方「目前狀態」取代。

### 公開候選原始碼驗證

以 Git 可公開候選檔案建立 55 檔原始碼副本，排除所有本機 output、data、私有課程設定、vendor、tools、模型及虛擬環境。在副本使用既有專案 Python 執行示範產生器與預設建置器，均可產出閱讀頁；30 項 Python、35 項 Node 測試通過，3 個跳過項目需要未散布的本機素材／上游（含整個 upstream 測試模組）。原工作環境為 34 項 Python、35 項 Node 通過。這是乾淨原始碼驗證，並非全新作業系統的安裝驗收。

Chrome 實測示範圖載入、音訊句尾暫停、自由跨章、示範校字保存與重整恢復；測試文字已還原。390×844 手機無橫向溢出，桌面與手機都能使用共用閱讀器。

根目錄 LICENSE 扣除新增的 LectureThread copyright 行後，與本機上游原始 LICENSE 一致。此前常見私鑰／token 格式掃描無命中；未宣稱全面安全稽核。

### README 下載流程再驗收

再次以公開候選的 55 個原始碼檔案建立獨立副本，路徑包含中文與空白。副本起初沒有 `.venv`、Python、課程產物、私有設定、上游 checkout 或模型。

README 當時列出 Windows x64／PowerShell、官方 uv 可攜版的放置位置、所有專案範圍的 UV 環境變數、建立 `.venv`、產生示範與啟動服務的步驟，以及 port 被占用時的處理。測試使用同版本官方 uv 工具，實際重新下載 Python 3.12.15 建立新 `.venv`，未借用原本專案的 Python 安裝或第三方套件；新環境的第三方套件清單為空。

依 README 執行示範產生器後可開啟頁面，SVG 載入成功、36 秒音訊載入成功。第一次下載需網路；執行示範不需要 GPU、模型、FFmpeg、Node 或額外 Python 套件。這是本機 Windows 的獨立執行環境驗證，未宣稱跨作業系統或全新 Windows 虛擬機驗收。

公開候選檔案與本機課程的長文字逐段比對，未發現課程文字；亦未含原課程識別碼、個人絕對路徑、私有設定、媒體、模型、產物或常見憑證格式。兩個整合測試已改由課程設定取得路徑，移除舊開發課程 ID 與固定筆數。

請勿將整個工作資料夾（含被 Git 忽略的本機資料）直接壓縮散布；公開範圍以 Git 追蹤的檔案為準。
