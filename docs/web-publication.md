# 唯讀網路版

網路版保留講義、全部畫面出現、已保存修訂及來源時間。觀看影片使用可見的 YouTube 官方播放器；聽句子使用獨立 AAC 音訊。本機閱讀頁和修訂檔不會被發布命令覆寫。

## 產生可攜發布包

在專案根目錄執行，output 必須是不存在的新資料夾：

```powershell
.\.venv\Scripts\python.exe export_web_readonly.py --course course.local.json --output output/web-release/0917
```

需要現有 FFmpeg。命令從課程設定的本機影片匯出完整音訊，不切除停頓，不重跑辨識或講義生成。發布包只有閱讀頁、引用的投影片、audio.m4a 與發布資訊；不包含原始影片、備份或模型資料。請只發布有權分享的課程素材。

## 分開部署音訊

先將 audio.m4a 上傳到支援 HTTPS、Content-Type audio/mp4 及 Range requests 的檔案服務。再指定正式網址重新匯出到新的目錄：

```powershell
.\.venv\Scripts\python.exe export_web_readonly.py --course course.local.json --output output/web-production/0917 --audio-url https://media.example.com/0917/audio.m4a
```

這時不會重新轉音訊，也不會將音訊複製進網頁包。將新目錄發布到靜態網站服務。R2 正式服務應使用自訂網域或適當的 Worker 路由；不要把 r2.dev 測試網址當正式服務。跨網域讀取若使用 CORS，允許實際網站來源及 GET/HEAD/Range。不要設定禁止傳送 Referer 的政策，以免 YouTube 缺少播放器識別。私有課程需要同時保護頁面、圖片與音訊；只有隱藏網址不是存取控制。

## 驗收

透過 HTTP/HTTPS 開啟，不用 file://。檢查桌面與手機的聽單句、聽段落、拖曳進度、影片跳轉、章節切換和關閉播放器。確認音訊與 YouTube 的同一時間確實是同一句；來源若有剪輯差異，需要先校對時間軸。YouTube 播放取決於原影片的嵌入權限及可用性，失敗時可用原影片時間連結；播放邊界為輪詢控制，不能保證逐音節精準。瀏覽器可能需要使用者再按一次播放。

目前唯讀模式不連線修訂 API，播放音訊也不載入 YouTube；只有按觀看影片才載入官方 API。部署後仍須驗證實際媒體 Range 回應與手機播放；本機測試不代表雲端已驗收。
