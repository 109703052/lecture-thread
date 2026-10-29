# 原創端到端範例：循環佇列如何分辨空與滿

約 3 分鐘的原創資工微課程，用來驗證外部使用者能用自己產生的影片與 PDF，走過轉錄、視覺核對、人工修訂、講義撰寫與閱讀頁建置。**完整操作見 [docs/end-to-end-example.md](../../docs/end-to-end-example.md)。**

內容：用容量 N = 5 的陣列追蹤 front／rear，示範 enqueue、dequeue 與索引繞回；只採用「保留一格空位」的判定（空：`front == rear`；滿：`(rear + 1) % N == front`）。影片刻意安排正常換頁、回到先前頁面、同頁逐步出現、小型手寫註記（4→0 箭頭、front 標記）、擦除、短暫回頁，以及一個 0.6 秒的挑戰換頁（低於 1 fps 取樣，標為限制，不要求偵測）。

## 檔案

| 路徑 | 用途 | Git |
|---|---|---|
| `course/deck.json` | 投影片內容與註記定義（可編輯） | 追蹤 |
| `course/storyboard.json` | 原創旁白腳本與畫面變化 | 追蹤 |
| `course/content-baseline.json` | 講義內容核對基準（不給偵測步驟讀） | 追蹤 |
| `scripts/generate_materials.py` | 產生 PDF、合成旁白、影片、標準答案 | 追蹤 |
| `scripts/prepare_job.py` | 建立任務、references.json，只跑轉碼與 ASR | 追蹤 |
| `scripts/review_visual.py` | 視覺核對包與決定範本 | 追蹤 |
| `scripts/build_evidence.py` | 人工決定 → `slide_evidence.json` | 追蹤 |
| `scripts/apply_corrections.py` | 校訂計畫 → 校訂逐字稿與紀錄 | 追蹤 |
| `scripts/build_reading_layer.py` | 閱讀稿草稿 → `transcript.reading.json` | 追蹤 |
| `scripts/evaluate.py` | 對照標準答案評估（只用於評估） | 追蹤 |
| `ai-assist-templates.md` | 校訂、閱讀稿、講義與視覺核對的提示範本 | 追蹤 |
| `reference-run/` | 參考執行的人工／撰寫層（綁定 hash 的範例） | 追蹤 |
| `output/e2e-circular-queue/`、`output/jobs/e2e-circular-queue/` | 影片、音訊、PDF、ASR、visual、閱讀頁等產物 | **忽略，只留本機** |

## 素材來源與授權

- 投影片文字、腳本、註記、產生器與參考撰寫層：本專案原創，依 repository 的 MIT 授權散布。
- 字型：PyMuPDF 內建的 CJK 字型（Droid Sans Fallback，Apache License 2.0），不需系統字型。
- 旁白：Windows 內建 SAPI 語音「Microsoft Hanhan Desktop」（zh-TW，`TTS_MS_ZH-TW_HANHAN_11.0`）在本機朗讀腳本，SAPI 速度 +2。**這是合成語音，不是真人授課，也不模仿任何特定人物。** 該語音的使用受 Windows 授權條款規範；本專案不散布生成的音訊或影片，也不宣稱可再散布，請在每台電腦重新產生。
- 不包含任何真實課程的影片、投影片、逐字稿或私人素材。

## 重建需要什麼

乾淨 checkout 只靠本目錄就能重建 PDF、旁白與影片，條件是：Windows 並已安裝 zh-TW Hanhan 語音、FFmpeg、專案 `.venv`（PyMuPDF）。不同 Windows 語音版本可能讓語音長度與時間點略有不同，因此 `expected_events.json` 每次都依實際合成時長重新計算。ASR 另需完整依賴、上游 checkout、NVIDIA GPU 與 Whisper large-v3（第一次需網路下載）。


## 續跑與核對資料完整性

完整素材生成後，產生器依 `materials.json` 驗證來源、程式與六項主要產物的 hash；相符時原樣沿用，不重寫 PDF 或影片。來源／程式改變、缺檔、修改或中斷未完成時，改用新的 `--out`，並讓後續 `--materials` 指向新目錄。舊版產物也不會被覆寫。PDF 停用隨機文件 ID，相同工具版本與輸入可重現相同 bytes。

核對決定依 `R01`／`D01` 等唯一 ID 配對，允許調整順序；不可刪漏、重複 ID 或改寫模板的來源欄位。非投影片 run 如實標為 `noise`，證據工具會明確停止，保留資料供後續處理；不會延長前一頁去填補這段時間。局部差異的 `noise` 決定仍可正常使用。完整指令與錯誤處理見主要指南。
