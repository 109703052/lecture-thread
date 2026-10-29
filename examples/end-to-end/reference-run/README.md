# 參考執行的人工與撰寫層

這裡保存 2026-10-29 參考執行中，**人工核對與 AI 直接撰寫**的四個檔案，作為格式與品質的範例。它們不是偵測器輸出，也不能取代你自己的核對。

| 檔案 | 步驟 | 撰寫／核對者 | 綁定 |
|---|---|---|---|
| `decisions.json` | 4 視覺核對 | Claude Code（看過 runs.png 與每張 diff 裁切；沒讀標準答案） | alignment `e0702fad…`、differences `368042ed…` |
| `corrections.plan.json` | 6 逐字稿校訂 | Claude Code（對照旁白腳本與投影片文字；未聽音） | 原始 ASR `81049fe6…` |
| `reading.draft.json` | 7 閱讀稿 | Claude Code | 內容依原始 ASR `81049fe6…` 的段落編號 |
| `editorial_chapters.json` | 8 講義 | Claude Code（依 note-spec 撰寫並完成教學品質檢查） | 原始 ASR `81049fe6…` |

使用方式：

- 你的原始 ASR SHA-256 若與上表相同（同模型、同設定、同影片時可能一致，但不保證），可以把這些檔案複製到對應位置（`<job>/authoring/`、`<job>/visual-human-review/`、`<job>/course/`）並照指南執行，工具會再驗證一次。
- hash 不同時，工具會拒絕使用它們（`decisions.json was made for a different visual output`、`The plan was written for a different raw ASR`、`Editorial raw transcript hash changed`）。請依 [AI 協助範本](../ai-assist-templates.md) 重新核對與撰寫；**不要只改 hash 讓檢查通過**，因為段落編號與內容可能已經不同。
- `decisions.json` 綁定的 alignment 內含本機絕對路徑，因此在另一台電腦或另一個資料夾幾乎一定需要重新核對。

這些文字是本專案原創內容，依 repository 的 MIT 授權散布。
