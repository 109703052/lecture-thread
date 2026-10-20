# 課程設定與本機資料

閱讀器只有一份程式碼。`build_reader.py` 與 `serve_reader.py` 都接受相同的 `--course` JSON 設定。

## 公開示範

```powershell
.\.venv\Scripts\python.exe examples/demo/create_demo.py
.\.venv\Scripts\python.exe serve_reader.py --course courses/demo.json --port 8767
```

開啟 <http://127.0.0.1:8767/index.html>。示範以原創教材與 SVG 呈現 stack／queue，共 36 秒。提示音在本機生成，沒有使用真實課程內容；詳見 [示範說明](../examples/demo/README.md)。

## 自己的課程

將設定存為根目錄的 `course.local.json`，或 `courses/` 內的 `名稱.local.json`。這些檔名已被 Git 忽略。每個課程使用自己的 `course_dir`、`web_root` 與穩定且唯一的 `id`，不要與 demo 共用資料目錄。

```json
{
  "schema": 1,
  "id": "my-course",
  "title": "我的課程",
  "description": "課程簡介",
  "course_dir": "output/my-course/course",
  "web_root": "output/my-course",
  "output_html": "index.html",
  "media": "output/my-course/media/lecture.mp4",
  "media_kind": "video",
  "youtube_id": ""
}
```

上例存於根目錄；若放到 `courses/my-course.local.json`，`course_dir`、`web_root`、`media` 應加 `../`。這三個路徑一律相對於**設定檔所在目錄**；`output_html` 則相對於 `web_root`。

| 欄位 | 說明 |
|---|---|
| `schema` | 目前為整數 `1` |
| `id` | 唯一課程識別碼，英數字開頭，可含 `_`、`.`、`-`；更換時會形成另一份瀏覽器偏好與修訂身分 |
| `title` | 必填，顯示於閱讀頁及瀏覽器標題 |
| `description` | 選填，顯示於課程說明列 |
| `course_dir` | 課程 JSON 與 `slides/` 所在目錄，必須位於 `web_root` 內 |
| `web_root` | 此課程 HTTP 服務與相對資源的根目錄 |
| `output_html` | 匯出的 HTML 相對路徑，預設 `index.html`；不得離開 `web_root` |
| `media` | 已存在的音訊或影片檔；必須位於 `web_root` 內 |
| `media_kind` | `video`（預設）或 `audio`；音訊課程停用觀看影片按鈕 |
| `youtube_id` | 選填的 11 字元影片 ID；空字串不顯示 YouTube 連結 |

`course_dir` 需要以下資料：

- `authored_notes.json`：每次投影片出現一筆，含 `title`、`region`、`points`、`caution`、`lesson`。每段 lesson 含 `time`、`heading`、`text`。
- `slide_evidence.json`：每次出現的 `start`、`end`、`image`（相對 `slides/`）；筆數必須與 notes 一致，保留回頁與註記變化。
- `transcript.corrected.json`：依時間排列的 `start`、`end`、`text` 陣列，作為人工修訂的基底。
- `transcript.json`：原始逐字稿，保持原樣；建置器不覆寫。
- `slides/`：設定中引用的投影片圖片。

以上是**已完成處理與撰寫的輸入格式**，不是匯入任意影片就會自動產生的內容。請參考公開示範與資工 [講義規格](../profiles/computer-science/note-spec.md)。

```powershell
.\.venv\Scripts\python.exe build_reader.py --course course.local.json
.\.venv\Scripts\python.exe serve_reader.py --course course.local.json --port 8766
```

兩個命令不傳 `--course` 時，優先使用根目錄 `course.local.json`；沒有本機設定時使用 `courses/demo.json`。公開 clone 需先執行示範產生器，才會有可閱讀的 HTML 與媒體。

服務一次載入一個課程；同時開兩個課程請使用不同 port。修訂只寫入該課程的 `transcript.manual-edits.json`；原始逐字稿與 AI 校正版不變。瀏覽器偏好依 origin 與課程 id 區分，既有課程若沿用原本 id 及 port，偏好仍可沿用。

## 公開範圍

公開的是 `courses/demo.json`、`examples/demo/` 的原創素材／產生器，以及共用程式碼。個人的 `*.local.json`、`data/`、`output/`、模型與 generated 媒體保持本機使用，不提交。Git 忽略規則用來防止一般 `git add` 誤加入；請勿以 `git add -f` 強制加入私有設定或課程資料。
