"""
main.py — 台灣股票投資儀表板後端
提供：
  GET  /api/stock/{code}        單支股票完整三維分析
  GET  /api/watchlist           觀察清單摘要（首頁總覽用）
  POST /api/watchlist           新增股票到觀察清單  body: {"code": "2330", "note": ""}
  DELETE /api/watchlist/{code}  移除股票
並在根目錄掛載 frontend 靜態檔案。
"""

import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from finmind_service import analyze_stock, GoodinfoFetchError
import market_service
import calendar_service

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
WATCHLIST_FILE = DATA_DIR / "watchlist.json"
CACHE_FILE = DATA_DIR / "cache.json"
CACHE_TTL_SECONDS = 12 * 60 * 60  # 12 小時內重複查詢直接吃快取，減少對 FinMind API 的請求

app = FastAPI(title="台灣股票投資儀表板 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 簡易 JSON 儲存 ─────────────────────────────────────────

def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_watchlist() -> list:
    return _load_json(WATCHLIST_FILE, [])


def save_watchlist(items: list):
    _save_json(WATCHLIST_FILE, items)


def get_cache() -> dict:
    return _load_json(CACHE_FILE, {})


def save_cache(cache: dict):
    _save_json(CACHE_FILE, cache)


def get_cached_analysis(code: str):
    cache = get_cache()
    entry = cache.get(code)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL_SECONDS:
        return entry["data"]
    return None


def set_cached_analysis(code: str, data: dict):
    cache = get_cache()
    cache[code] = {"ts": time.time(), "data": data}
    save_cache(cache)


# ─── API ────────────────────────────────────────────────────

@app.get("/api/stock/{code}")
def get_stock(code: str, force_refresh: bool = False):
    code = code.strip()
    if not force_refresh:
        cached = get_cached_analysis(code)
        if cached:
            cached["from_cache"] = True
            return cached
    try:
        data = analyze_stock(code)
    except GoodinfoFetchError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"抓取財報資料時發生錯誤：{e}")
    data["from_cache"] = False
    set_cached_analysis(code, data)
    return data


class WatchlistAdd(BaseModel):
    code: str
    note: str = ""
    category: str = "觀察中"          # 分類/標籤，例如：核心持股、觀察中
    alert_below: float | None = None  # 跌破這個價位提醒
    alert_above: float | None = None  # 漲過這個價位提醒


class WatchlistUpdate(BaseModel):
    note: str | None = None
    category: str | None = None
    alert_below: float | None = None
    alert_above: float | None = None
    clear_alert_below: bool = False
    clear_alert_above: bool = False


@app.get("/api/watchlist")
def list_watchlist():
    items = get_watchlist()
    summaries = []
    for item in items:
        code = item["code"]
        try:
            data = get_cached_analysis(code)
            if not data:
                data = analyze_stock(code)
                data["from_cache"] = False
                set_cached_analysis(code, data)
        except Exception as e:
            summaries.append({
                "code": code, "note": item.get("note", ""),
                "category": item.get("category", "觀察中"), "error": str(e),
            })
            continue

        years = data["years"]
        latest = years[0] if years else None
        m = data["metrics"].get(latest, {}) if latest else {}

        # 即時股價 + 價格提醒判斷
        alert_below = item.get("alert_below")
        alert_above = item.get("alert_above")
        alert_triggered = None
        realtime = None
        if alert_below is not None or alert_above is not None:
            try:
                realtime = market_service.get_realtime_price(code)
            except Exception:
                realtime = None
            if realtime and realtime.get("price") is not None:
                price = realtime["price"]
                if alert_below is not None and price <= alert_below:
                    alert_triggered = "below"
                elif alert_above is not None and price >= alert_above:
                    alert_triggered = "above"

        summaries.append({
            "code": code,
            "name": data.get("company_name", code),
            "note": item.get("note", ""),
            "category": item.get("category", "觀察中"),
            "alert_below": alert_below,
            "alert_above": alert_above,
            "alert_triggered": alert_triggered,
            "current_price": realtime.get("price") if realtime else None,
            "latest_year": latest,
            "revenue": m.get("revenue"),
            "revenue_yoy": m.get("revenue_yoy"),
            "eps": m.get("eps"),
            "eps_yoy": m.get("eps_yoy"),
            "net_margin": m.get("net_margin"),
            "roe": m.get("roe"),
            "debt_ratio": m.get("debt_ratio"),
            "warnings": len(data.get("verification", {}).get("sanity", [])),
        })
    return summaries


@app.post("/api/watchlist")
def add_watchlist(item: WatchlistAdd):
    code = item.code.strip()
    if not (code.isdigit() and 4 <= len(code) <= 6):
        raise HTTPException(status_code=400, detail="股票代碼格式錯誤，請輸入 4-6 碼數字")
    items = get_watchlist()
    if any(i["code"] == code for i in items):
        raise HTTPException(status_code=409, detail="這支股票已經在觀察清單中")
    items.append({
        "code": code,
        "note": item.note,
        "category": item.category or "觀察中",
        "alert_below": item.alert_below,
        "alert_above": item.alert_above,
        "added_at": time.time(),
    })
    save_watchlist(items)
    return {"ok": True}


@app.patch("/api/watchlist/{code}")
def update_watchlist(code: str, update: WatchlistUpdate):
    items = get_watchlist()
    for i in items:
        if i["code"] == code:
            if update.note is not None:
                i["note"] = update.note
            if update.category is not None:
                i["category"] = update.category
            if update.clear_alert_below:
                i["alert_below"] = None
            elif update.alert_below is not None:
                i["alert_below"] = update.alert_below
            if update.clear_alert_above:
                i["alert_above"] = None
            elif update.alert_above is not None:
                i["alert_above"] = update.alert_above
            save_watchlist(items)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="觀察清單中找不到這支股票")


@app.delete("/api/watchlist/{code}")
def remove_watchlist(code: str):
    items = get_watchlist()
    new_items = [i for i in items if i["code"] != code]
    if len(new_items) == len(items):
        raise HTTPException(status_code=404, detail="觀察清單中找不到這支股票")
    save_watchlist(new_items)
    return {"ok": True}


# ─── 市場情緒 ─────────────────────────────────────────────

@app.get("/api/market/sentiment")
def market_sentiment():
    return market_service.get_market_sentiment()


# ─── 市場行事曆 ───────────────────────────────────────────

@app.get("/api/calendar")
def calendar():
    codes = [i["code"] for i in get_watchlist()]
    return calendar_service.get_calendar(codes)


# ─── 掛載前端靜態檔案（放在所有 /api 路由之後）───────────────
FRONTEND_DIR = APP_DIR.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
