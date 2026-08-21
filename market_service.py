"""
market_service.py — 市場情緒資料
主要資料來源：FinMind 開放 API (https://api.finmindtrade.com) —— 大盤指數、三大法人買賣超
輔助資料來源：台灣證券交易所 OpenAPI (https://openapi.twse.com.tw) —— 全市場漲跌家數

⚠️ 這兩個都是公開資料集合，欄位名稱偶爾會微調。
本檔案的解析邏輯採「防禦性寫法」：抓不到預期欄位時回傳 None，
不會讓整個 API 掛掉，只是該項目顯示「—」。實際部署後如發現欄位對不上，
把錯誤訊息回報回來，可以很快修正。
"""

import os
import time
from datetime import date, timedelta

import requests

TWSE_BASE = "https://openapi.twse.com.tw/v1"
FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.environ.get("FINMIND_API_TOKEN", "")
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _get(path: str):
    url = f"{TWSE_BASE}{path}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _finmind_get(dataset: str, data_id: str = "", start_date: str = "", timeout: int = 15):
    params = {"dataset": dataset, "data_id": data_id, "start_date": start_date}
    headers = {}
    if FINMIND_TOKEN:
        headers["Authorization"] = f"Bearer {FINMIND_TOKEN}"
    r = requests.get(FINMIND_BASE, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    if "data" not in body:
        raise RuntimeError(body.get("msg") or body.get("detail") or "FinMind 回應格式異常")
    return body["data"]


def _to_float(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("+", "").strip())
    except Exception:
        return None


def get_taiex_summary():
    """大盤指數與成交量值，取最新一筆（改用 FinMind TaiwanStockPrice, data_id=TAIEX）。"""
    try:
        start = (date.today() - timedelta(days=10)).isoformat()
        rows = _finmind_get("TaiwanStockPrice", data_id="TAIEX", start_date=start)
        if not rows:
            return {"error": "FinMind 目前查不到 TAIEX 資料"}
        latest = rows[-1]
        return {
            "date": latest.get("date"),
            "taiex": _to_float(latest.get("close")),
            "change": _to_float(latest.get("spread")),
            "turnover_value": _to_float(latest.get("Trading_money")),
            "turnover_shares": _to_float(latest.get("Trading_Volume")),
            "trade_count": _to_float(latest.get("Trading_turnover")),
        }
    except Exception as e:
        return {"error": str(e)}


def get_market_breadth():
    """全市場漲跌家數（用當日收盤行情逐檔統計）。來源：TWSE OpenAPI，若失敗顯示為抓不到。"""
    try:
        data = _get("/exchangeReport/STOCK_DAY_ALL")
        up = down = flat = 0
        for row in data:
            diff = row.get("漲跌價差")
            sign = row.get("漲跌(+/-)", "")
            v = _to_float(diff)
            if v is None:
                continue
            if "-" in str(sign):
                v = -abs(v)
            elif v != 0:
                v = abs(v)
            if v > 0:
                up += 1
            elif v < 0:
                down += 1
            else:
                flat += 1
        total = up + down + flat
        return {"up": up, "down": down, "flat": flat, "total": total}
    except Exception as e:
        return {"error": str(e)}


def get_institutional_flow():
    """三大法人買賣超金額（外資／投信／自營商），單位：元。改用 FinMind。"""
    try:
        start = (date.today() - timedelta(days=10)).isoformat()
        rows = _finmind_get("TaiwanStockTotalInstitutionalInvestors", start_date=start)
        if not rows:
            return {"error": "FinMind 目前查不到三大法人資料"}
        latest_date = rows[-1].get("date")
        result = {}
        for row in rows:
            if row.get("date") != latest_date:
                continue
            name = row.get("name", "")
            buy = _to_float(row.get("buy"))
            sell = _to_float(row.get("sell"))
            net = (buy - sell) if (buy is not None and sell is not None) else None
            entry = {"buy": buy, "sell": sell, "net": net}
            if "Foreign" in name or "外資" in name:
                result["foreign"] = entry
            elif "Investment_Trust" in name or "投信" in name:
                result["investment_trust"] = entry
            elif "Dealer" in name or "自營商" in name:
                result.setdefault("dealer", {"buy": 0, "sell": 0, "net": 0})
                for k in ("buy", "sell", "net"):
                    if entry[k] is not None:
                        result["dealer"][k] = (result["dealer"].get(k) or 0) + entry[k]
        return result
    except Exception as e:
        return {"error": str(e)}


def get_market_sentiment():
    """整合市場情緒總覽區塊。"""
    return {
        "taiex": get_taiex_summary(),
        "breadth": get_market_breadth(),
        "institutional": get_institutional_flow(),
    }


def get_realtime_price(stock_id: str):
    """
    個股即時股價（用來做價格提醒）。
    優先試證交所即時揭示（tse/otc），抓不到時退回 FinMind 最新一筆收盤價（非即時，但至少有數字）。
    """
    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/"}
    for market in ("tse", "otc"):
        try:
            r = requests.get(url, params={"ex_ch": f"{market}_{stock_id}.tw"}, headers=headers, timeout=10)
            data = r.json()
            arr = data.get("msgArray", [])
            if arr:
                info = arr[0]
                price = _to_float(info.get("z")) or _to_float(info.get("y"))
                if price is not None:
                    return {
                        "stock_id": stock_id,
                        "name": info.get("n"),
                        "price": price,
                        "prev_close": _to_float(info.get("y")),
                        "time": info.get("t"),
                    }
        except Exception:
            continue

    try:
        start = (date.today() - timedelta(days=10)).isoformat()
        rows = _finmind_get("TaiwanStockPrice", data_id=stock_id, start_date=start)
        if rows:
            latest = rows[-1]
            return {
                "stock_id": stock_id,
                "name": None,
                "price": _to_float(latest.get("close")),
                "prev_close": None,
                "time": latest.get("date"),
            }
    except Exception:
        pass
    return None
