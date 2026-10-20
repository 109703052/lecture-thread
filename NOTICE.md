# 來源與授權

LectureThread／課脈由本專案維護者發展，基於 [drpwchen/lecture-to-notes](https://github.com/drpwchen/lecture-to-notes) 的課程處理基礎，新增以閱讀與原句對照為核心的介面及資工領域設定。

## 上游

- 作者：drpwchen 及其貢獻者。
- 授權：MIT；Copyright (c) 2026 drpwchen。
- 固定版本：`cc06141939ce56def13a15410d8d07e861028d94`，另存於 `upstream-commit.txt`。
- 提供：影片轉錄、投影片擷取、OCR、去重、對齊及原始筆記匯出。
- 上游原始碼另行取得於 `vendor/lecture-to-notes/`，不納入本專案 Git。該 checkout 的 LICENSE 保持原樣。

## LectureThread 新增部分

- 資工預設、領域提示、術語及講義規格。
- 每次投影片出現的證據、回頁與註記變化保留、覆蓋檢查及時間對齊。
- 投影片與講義並排、逐字稿抽屜、章節浮標及版面偏好保存。
- 原句／段落聲音播放、任意 seek、自由播放跨章同步與隨選影片。
- 人工校字、草稿、版本衝突比較及本地原子保存。
- 本專案的新增程式碼以 MIT 散布；Copyright (c) 2026 LectureThread contributors。

原型的需求、設計方向與檢閱由專案維護者主導，AI 工具協助程式實作及講義整理。Whisper、OCR、模型及上游處理管線的貢獻仍歸其原作者。

根目錄 [LICENSE](LICENSE) 保留上游 MIT 聲明，並另列 LectureThread 貢獻者。原始上游 LICENSE 未修改；散布上游程式或其實質部分時應一併保留原授權與著作權聲明。

課程影片、投影片、逐字稿、模型權重與第三方相依各適用其原有權利及授權，不因本專案的 MIT 授權而自動開放散布。此 repository 的公開範圍為程式碼、設定、文件、測試，以及 `examples/demo/` 自行製作的文字、SVG 與提示音產生器；不含實際本機課程素材、生成的媒體與模型。
