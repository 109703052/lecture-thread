# AI 協助範本：校訂、閱讀稿與講義

這些範本讓你在**不知道任何先前對話**的情況下，把撰寫工作交給一個 AI 助理（或自己照著做）。每個範本都列出：要提供的輸入、可直接貼上的要求、輸出格式，以及收稿後的驗收方法。AI 的輸出一律先經人工檢查，再交給工具驗證；工具驗證只檢查格式、來源與 hash，不檢查內容是否正確。

所有範本都要求 AI **先完整讀** `profiles/computer-science/note-spec.md`。下文的 `<job>` 指任務資料夾，例如 `output/jobs/e2e-circular-queue`。

## 範本 1：逐字稿校訂計畫

**提供的輸入**

- `<job>/course/transcript.json`（原始 ASR，不可修改）與其 SHA-256。
- OpenCC 正規化後的文字：工具會先做正規化，所以 `find` 必須對正規化後的文字比對。可用以下命令列出：

  ```powershell
  .\.venv\Scripts\python.exe -c "import json,copy,sys; sys.stdout.reconfigure(encoding='utf-8'); from traditional_chinese import normalize_transcript; t=json.load(open(r'<job>\course\transcript.json',encoding='utf-8')); normalize_transcript(t,[]); [print(i,r['start'],r['end'],r['text']) for i,r in enumerate(t)]"
  ```

- `<job>/course/slide_evidence.json`（每次畫面出現的時間與 `deck_text_layer`）。
- 若有：講者腳本（本範例的 `narration_script.json`）。真實課程通常沒有。

**要求（可直接貼上）**

> 請先完整讀 profiles/computer-science/note-spec.md 的「閱讀優先與逐字稿校正」。根據我提供的 OpenCC 正規化後 ASR、同時間投影片文字與（若有）講者腳本，列出需要校訂的地方。只修正：同音誤聽的術語與詞、被辨成字母的數字（例如「加 e」應為「加 1」）、投影片上寫明的識別字大小寫、字形轉換造成的錯字。不要改寫語序、不要補講者沒說的內容、不要把不確定的數字改成標準答案；無法確認的列在另一個「疑點」清單並附時間。每一條都要寫依據。只輸出 JSON。

**輸出格式**：`<job>/authoring/corrections.plan.json`

```json
{"schema": 1, "raw_transcript_sha256": "<transcript.json SHA-256>",
 "reviewer": "誰核對", "method": "依據什麼、有沒有回聽",
 "corrections": [
   {"segment_id": 0, "find": "註列", "replace": "佇列", "count": 2,
    "basis": "narration-script", "reason": "腳本為「佇列」；同音誤聽"}]}
```

`basis` 只能是 `narration-script`、`slide-text`、`normalization-fix`。`count` 是該段中 `find` 出現的次數（全部替換）。

**驗收**

1. 執行 `apply_corrections.py`；任何 `find` 不符都會停下。
2. 逐條抽查：依據是否真的在投影片或腳本上？是否改動了原意、否定、條件或數字？
3. 確認 `transcript.json` 的 hash 沒變，`transcript.corrected.json` 段數與時間相同。
4. 沒有回聽就不要寫成「已聽音確認」。

## 範本 2：閱讀稿草稿

**提供的輸入**：`<job>/course/transcript.corrected.json`（附段落編號與時間）、note-spec。

**要求（可直接貼上）**

> 請先完整讀 profiles/computer-science/note-spec.md 的「AI 修順閱讀稿的界線」。把校訂逐字稿分成依序、連續、不重疊且涵蓋全部段落的段落，每段寫成通順的繁體中文閱讀稿：可以刪冗詞、補標點、合併被 ASR 切斷的句子；必須保留數字、單位、英文術語、條件、否定、因果、例子與講者的自我指涉（例如「我在下方畫一個箭頭」）。不得新增知識或改寫成講義。每段再逐句切開，每句標出它濃縮的連續原句編號；句子依原話順序，涵蓋整段所有原句，相鄰兩句最多共用一個邊界原句。只輸出 JSON。

**輸出格式**：`<job>/authoring/reading.draft.json`

```json
{"author": "撰寫者名稱", "authoring_method": "如何撰寫與核對",
 "paragraphs": [
   {"source_ids": [1, 2, 3], "text": "句一。句二。",
    "sentences": [{"text": "句一。", "source_ids": [1]}, {"text": "句二。", "source_ids": [2, 3]}]}]}
```

`sentences` 的文字串起來必須**完全等於** `text`。

**驗收**

1. 執行 `build_reading_layer.py`，通過閱讀器相同的驗證。
2. 可再用 `align_reading_sentences.py draft` 產生文字重疊的對照草稿，比較逐句對應的差異。
3. 逐段比對原話：沒有遺漏實質資訊、沒有改變語氣或條件、沒有新增主張、數字與術語一致。

## 範本 3：講義（editorial_chapters.json）

**提供的輸入**

- note-spec 全文（必讀，含「直白好理解的講義」與「教學品質檢查」）。
- `transcript.corrected.json`（附編號與時間）、`transcript.json` 的 SHA-256。
- `slide_evidence.json`：每次出現的時間、頁碼、`deck_text_layer`、`visual_change_meaning`。
- 投影片圖片（`course/slides/`）。
- 同系列課程：前一堂最新講義與待核對清單。
- 已知疑點（例如口述與畫面不一致、OCR 失敗）。

**要求（可直接貼上）**

> 請先完整讀 profiles/computer-science/note-spec.md，包括「直白好理解的講義：寫作流程與驗收」。依講者的講解順序，用直白的繁體中文寫一份可獨立閱讀的講義：先寫全課總覽（核心問題 → 分段推進 → 結論，附代表時間 HH:MM:SS）；再按概念分章，每章有一句摘要與數個段落。段落要說明問題、機制、操作步驟（起點、每一步誰做什麼、狀態如何改變、結果）、例子與條件；算例要能照文字重算。講者沒說、為了理解而補的內容，句首標「整理補充：」；由前後內容推得的銜接標「（推論）」。章節起點請對齊投影片換頁時間（slide_evidence 的 start）。每段列出 source_ids：全部 ASR 段落依序恰好歸屬一次。口述和投影片矛盾、OCR 不可靠等具體疑點放在該章 checks，附時間與 source_ids；不要在正文反覆寫警語。寫完逐章做教學品質檢查並修改，再輸出 JSON。

**輸出格式**：見 [指南步驟 8](../../docs/end-to-end-example.md#步驟-8講義ai-協助撰寫人工教學品質檢查)。`author` 填實際撰寫的助理（`Codex` 或 `Claude Code`）；本機文字模型產生的內容不能用這個欄位冒充直接撰寫。

**驗收**

1. 執行 `editorial_publish.py` 與 `--check`。
2. 用 `content-baseline.json`（本範例）或自己的重點清單逐項核對：規則、每一步的狀態、結論是否正確且講清楚；`must_not_claim` 有沒有出現。
3. 逐章回答 note-spec 的教學品質問題，記錄發現與修改。
4. 在閱讀頁實際讀一次，確認段落和投影片、原句能互相對上。

## 範本 4：視覺核對（給人看的檢查表）

視覺核對本身是人工步驟；如果請 AI 協助看圖，也要提供圖片並保留它的判斷理由。

- 輸入：`visual-human-review/review.md`、`runs.png`、`diff-XX.png`、`decisions.template.json`。
- 對每個 run：縮圖是否就是候選頁？有沒有一個 run 其實包含兩頁？
- 對每個差異事件：before／after 實際差在哪裡？是新增註記、擦除、逐步出現、其他內容變化，還是雜訊（游標、錄影指示、壓縮雜訊）？OCR 空白時看圖，不看 OCR。
- 輸出：`decisions.json`，每筆有 `decision` 與 `meaning`，加上 `reviewer`、`reviewed_at`、`method`、`missed`。
- 驗收：`build_evidence.py` 接受；再抽看幾個 `course/slides/occ-*.png` 是否就是那次出現的畫面。
- 不要讀評估用的標準答案（`expected_events.json`）來填決定。
