"""
market_service.py — 市場情緒資料
資料來源：台灣證券交易所 OpenAPI (https://openapi.twse.com.tw)
  - FMTQIK        大盤每日成交量值 + 加權指數漲跌
  - STOCK_DAY_ALL 全部上市公司當日收盤行情（用來算漲跌家數）
  - BFI82U        三大法人買賣金額統計表

⚠️ TWSE OpenAPI 為公開資料集合，欄位名稱偶爾會微調。
本檔案的解析邏輯採「防禦性寫法」：抓不到預期欄位時回傳 None，
不會讓整個 API 掛掉，只是該項目顯示「—」。實際部署後如發現欄位對不上，
把錯誤訊息回報回來，可以很快修正。
"""

import requests

TWSE_BASE = "https://openapi.twse.com.tw/v1"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _get(path: str):
    url = f"{TWSE_BASE}{path}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _to_float(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("+", "").strip())
    except Exception:
        return None


def get_taiex_summary():
    """大盤指數與成交量值，取最新一筆。"""
    try:
        data = _get("/exchangeReport/FMTQIK")
        if not data:
            return None
        latest = data[-1]
        return {
            "date": latest.get("日期"),
            "taiex": _to_float(latest.get("發行量加權股價指數")),
            "change": _to_float(latest.get("漲跌點數")),
            "turnover_value": _to_float(latest.get("成交金額")),
            "turnover_shares": _to_float(latest.get("成交股數")),
            "trade_count": _to_float(latest.get("成交筆數")),
        }
    except Exception as e:
        return {"error": str(e)}


def get_market_breadth():
    """全市場漲跌家數（用當日收盤行情逐檔統計，非官方直接提供的欄位）。"""
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
    """三大法人買賣超金額（外資／投信／自營商），單位：元。"""
    try:
        data = _get("/fund/BFI82U")
        result = {}
        for row in data:
            name = row.get("單位名稱", "")
            buy = _to_float(row.get("買進金額"))
            sell = _to_float(row.get("賣出金額"))
            net = _to_float(row.get("買賣差額"))
            if net is None and buy is not None and sell is not None:
                net = buy - sell
            entry = {"buy": buy, "sell": sell, "net": net}
            if "外資" in name and "陸資" not in name:
                result["foreign"] = entry
            elif "投信" in name:
                result["investment_trust"] = entry
            elif "自營商" in name and "避險" not in name:
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
    """個股即時股價（用來做價格提醒），先試上市(tse)再試上櫃(otc)。"""
    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/"}
    for market in ("tse", "otc"):
        try:
            r = requests.get(url, params={"ex_ch": f"{market}_{stock_id}.tw"}, headers=headers, timeout=10)
            data = r.json()
            arr = data.get("msgArray", [])
            if arr:
                info = arr[0]
                price = _to_float(info.get("z")) or _to_float(info.get("y"))  # z=成交價, y=昨收
                return {
                    "stock_id": stock_id,
                    "name": info.get("n"),
                    "price": price,
                    "prev_close": _to_float(info.get("y")),
                    "time": info.get("t"),
                }
        except Exception:
            continue
    return None
