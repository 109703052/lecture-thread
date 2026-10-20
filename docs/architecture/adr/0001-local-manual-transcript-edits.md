# ADR 0001: 本地檔案作為人工逐字稿修訂的正式來源

Status: Accepted
Date: 2026-10-21

## Context

瀏覽器保存會隨網址來源或瀏覽器改變而分離，不能作為課程長期修訂的正式來源。使用者要求右欄儲存直接落盤，原始 ASR 與 AI 校正版不可覆寫，多分頁不得互相覆蓋。

## Decision

- `transcript.manual-edits.json` 是正式人工修訂；`transcript.json` 與 `transcript.corrected.json` 保持唯讀。閱讀與匯出以人工文字覆蓋顯示，來源時間不變。
- 本機 HTTP 服務提供固定課程的讀取／儲存端點。以檔案內容 hash 作版本，OS 檔案鎖協調程序，暫存檔 flush/fsync 後原子替換；每次成功儲存有新 save_id，使還原操作也使舊版本失效。
- 寫入比對 AI 基底版本與修訂版本；衝突回傳 409 與最新內容，保留草稿並要求使用者比較後再次明確儲存，不自動合併。
- sessionStorage 僅存各分頁的未儲存草稿、編輯基底版本及衝突狀態，重整可恢復，不會自動升格為正式修訂。關頁前仍應儲存或匯出；關閉分頁不保證保留 sessionStorage。
- 僅監聽 loopback；API 驗證 Host、相同 Origin、Fetch Metadata 及工作階段 token，不接受客戶端檔案路徑。這是本機單使用者服務，不是公開多使用者後端。

## Consequences

- 修訂可備份、重建閱讀頁，且原稿及 AI 校正版維持不變。
- 不同分頁或協作中的本機程序採樂觀版本檢查，不會靜默覆蓋。
- 需要執行本機服務才能直接儲存；靜態 HTML 可閱讀內嵌快照、寫草稿與匯出備份。
- 任一句修訂都更新整份版本；無關句子的舊分頁也可能需要比較後重試，先選擇保守保護。
- AI 基底變更時拒絕套用錯配修訂，需要人工核對。目前課程路徑仍沿用單一範例設定。

## Alternatives considered

- localStorage 作正式來源：不隨課程資料走，且多分頁容易覆寫。
- 直接覆寫 AI 校正版：失去機器校正與人工修改的界線，重跑管線容易蓋掉成果。
- 資料庫：現階段單機、單課程的修訂規模不需要額外服務或依賴。

Related: [HANDOFF](../../HANDOFF.md), [storage implementation](../../../manual_edits.py), [local server](../../../serve_reader.py).
