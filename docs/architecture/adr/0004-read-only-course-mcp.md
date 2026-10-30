# ADR 0004: 以本機唯讀 MCP 提供課程證據查詢

Status: Proposed
Date: 2026-10-30

## Implementation status（2026-10-30）

第一版已依決策與設計實作：`course_query.py`（純查詢）、`lecture_mcp_server.py`（SDK 轉接，`mcp==2.3.0`，stdio）、四個唯讀工具、公開 registry 範例與 [操作文件](../../mcp.md)。本機已通過純查詢測試、以官方 SDK client 實際啟動 stdio server 的協定測試、乾淨副本從零安裝與測試，以及 Claude Code 2.1.303 作為 AI host 的實際連接（[展示紀錄](../../mcp-ai-host-demo.md)）。

仍維持 Proposed，差距只有一項：新增的 CI 步驟尚未在 GitHub Actions 實際執行（變更未提交、未推送）。Actions 在 `windows-2025` 上通過後改為 Accepted；若失敗，先修正再評估。與原設計的介面差異列在 [MCP 設計](../../mcp-design.md) 文末。

## Context

LectureThread 已有結構化逐字稿、直接撰寫講義與畫面出現紀錄。作業希望把實際功能提供給 AI agent；現有課程含多種資料層，且長時間推論、人工修訂與發布有不同生命週期。

## Decision

第一版採官方 Python SDK、stdio 與明確登錄的課程清單，提供四個唯讀工具。用來源 ID、時間、資料層與快照 revision 回傳證據，由 host 的模型組織答案。查詢邏輯與協定轉接分層，不執行模型、修改課程或發布。詳細契約見 [MCP 設計](../../mcp-design.md)。

## Consequences

- 可以重用既有 JSON 與來源驗證；以原創小型 fixture 在 Windows CI 做真正的 MCP client/server 驗收。
- 不需遠端部署與 GPU，但初版只適用已處理的課程；不支援語意搜尋、圖片理解或自動課程處理。
- 需維護 SDK／host 相容性、資料版本與讀取邊界。連接雲端 host 時，回傳片段可能離開本機，需讓使用者清楚知道。

## Alternatives considered

- 先提供影片處理／發布工具：功能有價值，但要先處理長任務、鎖、取消、寫入授權與恢復，不作第一版。
- 遠端 HTTP MCP：便於多人使用，但增加部署、認證與課程隔離成本，待有跨機需求再做。
- 直接給 agent 檔案或 shell：可快速操作，但缺少穩定的課程契約、可控範圍與來源語意。
