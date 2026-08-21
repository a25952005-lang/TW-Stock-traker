# 📊 台灣股票投資儀表板

輸入台股代碼，即時從 Goodinfo.tw 抓取財報，自動算出經營 / 獲利 / 財務健全度三大維度指標，
並提供「觀察清單首頁總覽」+「個股詳細三分頁儀表板」。

## 功能總覽

| 功能 | 說明 | 資料來源 |
|---|---|---|
| 📊 財報分析 | 個股經營/獲利/財務健全度三分頁儀表板 | Goodinfo.tw |
| ⭐ 自選股 | 觀察清單、分類標籤、跌破/漲過價格提醒 | Goodinfo.tw + 證交所即時行情 |
| 📈 市場情緒 | 加權指數、成交量、漲跌家數、三大法人買賣超 | 證交所 OpenAPI |
| 🗓️ 市場行事曆 | 自選股除權息日、財報法定截止日、總經事件 | 證交所 OpenAPI + 使用者可編輯清單 |

## 專案結構

```
tw-stock-dashboard/
├── backend/
│   ├── main.py               # FastAPI：API 路由 + 掛載前端靜態檔案
│   ├── goodinfo_service.py   # 抓取 Goodinfo.tw + 計算財務指標
│   ├── market_service.py     # 大盤情緒、三大法人買賣超、個股即時股價
│   ├── calendar_service.py   # 除權息預告、財報截止日規則、總經事件
│   ├── requirements.txt
│   └── data/                 # 執行後自動產生：watchlist.json、cache.json、macro_events.json
├── frontend/
│   ├── index.html            # 首頁：市場情緒總覽 + 自選股清單
│   ├── stock.html            # 個股詳情：經營/獲利/財務健全度 三分頁
│   ├── calendar.html         # 市場行事曆
│   ├── style.css
│   └── common.js
├── Dockerfile
└── README.md
```

## 各功能的重要限制（老實跟你說）

- **市場情緒 / 行事曆的除權息資料**：呼叫的是證交所公開 OpenAPI
  (`openapi.twse.com.tw`)，我在建立這個專案的沙盒環境連不出去，所以無法在這裡
  實際跑一次確認 JSON 欄位名稱 100%正確。程式碼已經用「防禦性寫法」處理
  （抓不到欄位就顯示「—」，不會讓網站掛掉），但部署後如果數字看起來怪怪的
  （例如三大法人數字對不上），把畫面截圖或錯誤訊息給我，我可以照實際回傳的
  JSON 調整欄位對應。
- **財報法定截止日**：這是「規則計算」，不是即時公告，永遠準確（因為是法規訂的固定日期），
  但只是「最晚期限」，公司通常會提早公告。
- **總體經濟事件（央行會議、CPI）**：這類日期每年由官方另行公告、常會微調，
  我沒有把確切日期寫死進去（怕給你錯誤資訊），而是放在
  `backend/data/macro_events.json`，你可以直接編輯這個檔案加入確切日期，
  或之後請我幫你查最新公告的日期再更新進去。
- **價格提醒**：目前是「你打開網站時即時檢查」，不是背景推播通知。也就是說，
  你要真的打開首頁，才會看到提醒被觸發的紅色標籤。如果你想要「就算沒開網站
  也會收到 Email/LINE 通知」，這需要再加一個排程 (cron) + 通知管道，
  跟我說要哪一種通知方式，我可以幫你加上去。

## 本機測試

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

打開瀏覽器到 `http://localhost:8000`，輸入股票代碼（例如 2330）加入觀察清單即可。

> ⚠️ 注意：我在建立這個專案的沙盒環境中，對外網路只開放了 GitHub / PyPI 等少數幾個網域，
> 沒辦法連到 goodinfo.tw，所以無法在這裡實際測試抓取結果。抓取邏輯是照原始 skill
> 的程式碼原封不動搬過來的，理論上部署到一般雲端主機（對外連線沒有限制）就能正常運作。
> 如果你本機測試時噴錯，把錯誤訊息貼給我，我可以馬上幫你修。

## 部署到網路上（讓其他人也能連）

### 方法一：Render（最簡單，免費額度可用）

1. 把這個資料夾推到你自己的 GitHub repo
2. 到 [render.com](https://render.com) → New → Web Service → 連接你的 repo
3. 設定：
   - Environment: `Docker`（會自動偵測到 `Dockerfile`）
   - 或不用 Docker 的話：Build Command 用 `pip install -r backend/requirements.txt`，
     Start Command 用 `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`
4. 部署完成後會拿到一個 `https://xxx.onrender.com` 網址，直接分享出去就能用

### 方法二：Railway / Fly.io

流程大同小異：連接 repo → 偵測到 `Dockerfile` → 一鍵部署，會自動給一個對外網址。

### 方法三：自己的伺服器（VPS）

```bash
docker build -t tw-stock-dashboard .
docker run -d -p 80:8000 -v $(pwd)/backend/data:/app/backend/data tw-stock-dashboard
```

`-v` 這段是把 `data/` 資料夾掛到主機上，這樣觀察清單跟快取資料不會在容器重啟後消失。

## 重要提醒

- **資料來源**：Goodinfo.tw 是公開網站，抓取方式沿用原 skill 的做法（用一組計算出來的
  `CLIENT_KEY` cookie 換取財報頁面），屬於讀取公開頁面，並沒有繞過付費或登入牆。
  但這類爬蟲仍可能因對方網站改版或加強防護而失效，屬於正常維護範圍。
- **快取機制**：同一支股票 12 小時內重複查詢會直接吃快取，避免太頻繁打 Goodinfo，
  也讓首頁載入更快。可在 `main.py` 的 `CACHE_TTL_SECONDS` 調整。
- **僅供學習研究**：所有頁面都標註「不構成投資建議」，數字如需正式引用請以
  公開資訊觀測站 (MOPS) 為準。
- **觀察清單資料**目前存成本機 JSON 檔（`backend/data/watchlist.json`），是「單一使用者」
  的簡易版本；如果要多人各自登入、各自有自己的清單，需要再加上帳號系統跟資料庫，
  這部分我還沒做，之後有需要可以再幫你擴充。
