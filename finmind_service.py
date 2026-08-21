"""
finmind_service.py
改用 FinMind (https://finmindtrade.com) 開放 API 取得台灣上市/上櫃公司財報，
取代原本爬 Goodinfo.tw 的做法。

為什麼換成這個：
- FinMind 是正規的 REST API 伺服器（api.finmindtrade.com），回傳乾淨的 JSON，
  不是用「爬蟲繞過防護」的方式拿資料，所以不會有 Goodinfo 那種被雲端主機 IP
  擋下來（403）的問題。
- 這是台灣開發者社群裡最多人用來做股票資料分析的開放資料集之一。

資料格式差異：
FinMind 回傳的是「長格式」：每一列是 {date, stock_id, type, value, origin_name}，
跟 Goodinfo 原本「一列一個科目、橫向攤開好幾年」的格式不同，這裡會做轉換，
轉成跟原本 goodinfo_service.py 一樣的 {科目: {年度: 數值}} 格式，
這樣後面計算財務比率的邏輯完全不用重寫。

台灣財報揭露慣例：每季公告的數字是「累計數」（第一季=Q1本身、第二季=上半年累計、
第三季=前三季累計、第四季/年報=全年累計），所以只要抓「12/31 期別」的那筆，
就是完整的全年度數字，等同於原本 Goodinfo 年度欄位的概念。
"""

import os
import time
from collections import defaultdict
from datetime import date

import requests

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.environ.get("FINMIND_API_TOKEN", "")  # 選填，沒有 token 也能用，但有請求次數限制


class GoodinfoFetchError(Exception):
    """沿用舊名稱，避免呼叫端 (main.py) 還要跟著改 import。"""
    pass


def _request(dataset: str, data_id: str = "", start_date: str = "", timeout: int = 20) -> list:
    params = {"dataset": dataset, "data_id": data_id, "start_date": start_date}
    headers = {}
    if FINMIND_TOKEN:
        headers["Authorization"] = f"Bearer {FINMIND_TOKEN}"
    r = requests.get(FINMIND_BASE, params=params, headers=headers, timeout=timeout)
    if r.status_code != 200:
        raise GoodinfoFetchError(
            f"FinMind API 回應狀態碼 {r.status_code}（dataset={dataset}, data_id={data_id}）"
        )
    body = r.json()
    if "data" not in body:
        msg = body.get("msg") or body.get("detail") or body
        raise GoodinfoFetchError(f"FinMind API 回應異常：{msg}")
    return body["data"]


def _company_name(stock_id: str) -> str:
    try:
        rows = _request("TaiwanStockInfo", data_id=stock_id)
        if rows:
            return rows[0].get("stock_name", stock_id)
    except Exception:
        pass
    return stock_id


def _pivot_annual(records: list, years_back: int = 3):
    """
    把 FinMind 長格式資料，轉成 {origin_name: {年度: 數值}}，只保留每年 12/31（全年累計）那期。
    回傳 (data, years)，years 由新到舊排序，最多 years_back 年。
    """
    by_year_end = defaultdict(dict)  # {year: {origin_name: value}}
    for row in records:
        d = row.get("date", "")
        if not d.endswith("-12-31"):
            continue
        yr = d[:4]
        name = row.get("origin_name") or row.get("type")
        val = row.get("value")
        if name is None or val is None:
            continue
        by_year_end[yr][name] = val

    years = sorted(by_year_end.keys(), reverse=True)[:years_back]
    data = defaultdict(dict)
    for yr in years:
        for name, val in by_year_end[yr].items():
            data[name][yr] = val
    return dict(data), years


def _find_key(table: dict, *any_of_keyword_groups) -> str | None:
    """
    每個 keyword group 是一組「必須同時出現」的關鍵字（AND）；
    多組 keyword group 之間依序嘗試，找到第一組有命中的就回傳（等同 OR 多套備援關鍵字）。
    """
    for group in any_of_keyword_groups:
        for k in table:
            if all(kw in k for kw in group):
                return k
    return None


def _g(table: dict, key, yr):
    if key is None:
        return None
    return table.get(key, {}).get(yr)


def _safe_div(a, b, pct=True):
    if a is None or b is None or b == 0:
        return None
    v = a / b
    return v * 100 if pct else v


def compute_metrics(is_d: dict, bs_d: dict, cf_d: dict, years: list) -> dict:
    keys = {
        "rev": _find_key(is_d, ["營業收入合計"], ["營業收入"], ["收入合計"]),
        "gp": _find_key(is_d, ["營業毛利"], ["毛利"]),
        "sell": _find_key(is_d, ["推銷費用"]),
        "admin": _find_key(is_d, ["管理費用"]),
        "rd": _find_key(is_d, ["研究發展費用"], ["研究發展費"]),
        "op": _find_key(is_d, ["營業利益"], ["營業利益（損失）"]),
        "ni": _find_key(is_d, ["本期淨利", "母公司"], ["稅後淨利"], ["本期淨利"], ["淨利（淨損）"]),
        "eps": _find_key(is_d, ["每股", "盈餘"]),
        "cash": _find_key(bs_d, ["現金及約當現金"]),
        "inv": _find_key(bs_d, ["存貨"]),
        "ca": _find_key(bs_d, ["流動資產合計"]),
        "cl": _find_key(bs_d, ["流動負債合計"]),
        "tl": _find_key(bs_d, ["負債總計"], ["負債總額"]),
        "ta": _find_key(bs_d, ["資產總計"], ["資產總額"]),
        "eq": _find_key(bs_d, ["權益總計"], ["股東權益總額"], ["權益總額"]),
        "op_cf": _find_key(cf_d, ["營業活動之淨現金流入"], ["營業活動淨現金流入"]),
        "inv_cf": _find_key(cf_d, ["投資活動之淨現金流入"], ["投資活動淨現金流入"]),
        "fin_cf": _find_key(cf_d, ["籌資活動之淨現金流入"], ["融資活動之淨現金流入"]),
        "capex": _find_key(cf_d, ["取得", "不動產"], ["購置固定資產"], ["固定資產"]),
        "div_cash": _find_key(cf_d, ["發放現金股利"], ["支付現金股利"]),
    }

    metrics = {}
    for yr in years:
        rev = _g(is_d, keys["rev"], yr)
        gp = _g(is_d, keys["gp"], yr)
        sell = _g(is_d, keys["sell"], yr)
        admin = _g(is_d, keys["admin"], yr)
        rd = _g(is_d, keys["rd"], yr)
        op = _g(is_d, keys["op"], yr)
        ni = _g(is_d, keys["ni"], yr)
        eps = _g(is_d, keys["eps"], yr)

        cash = _g(bs_d, keys["cash"], yr)
        inv = _g(bs_d, keys["inv"], yr)
        ca = _g(bs_d, keys["ca"], yr)
        cl = _g(bs_d, keys["cl"], yr)
        tl = _g(bs_d, keys["tl"], yr)
        ta = _g(bs_d, keys["ta"], yr)
        eq = _g(bs_d, keys["eq"], yr)

        op_cf = _g(cf_d, keys["op_cf"], yr)
        inv_cf = _g(cf_d, keys["inv_cf"], yr)
        fin_cf = _g(cf_d, keys["fin_cf"], yr)
        capex = _g(cf_d, keys["capex"], yr)
        div_cash = _g(cf_d, keys["div_cash"], yr)

        # FinMind 金額單位是「元」，跟原本 Goodinfo 的「億元」不同，這裡統一換算成億元方便沿用前端顯示邏輯
        def to_yi(v):
            return v / 1e8 if v is not None else None

        rev, gp, sell, admin, rd, op, ni = map(to_yi, (rev, gp, sell, admin, rd, op, ni))
        cash, inv, ca, cl, tl, ta, eq = map(to_yi, (cash, inv, ca, cl, tl, ta, eq))
        op_cf, inv_cf, fin_cf, capex, div_cash = map(to_yi, (op_cf, inv_cf, fin_cf, capex, div_cash))

        fcf = None
        if op_cf is not None and capex is not None:
            fcf = op_cf - abs(capex)

        metrics[yr] = {
            "revenue": rev, "gross_profit": gp, "sell_exp": sell, "admin_exp": admin,
            "rd_exp": rd, "op_income": op, "net_income": ni, "eps": eps,
            "cash": cash, "inventory": inv, "current_assets": ca, "current_liabilities": cl,
            "total_liabilities": tl, "total_assets": ta, "equity": eq,
            "operating_cf": op_cf, "investing_cf": inv_cf, "financing_cf": fin_cf,
            "capex": capex, "cash_dividend": div_cash, "fcf": fcf,
            "gross_margin": _safe_div(gp, rev),
            "op_margin": _safe_div(op, rev),
            "net_margin": _safe_div(ni, rev),
            "sell_ratio": _safe_div(sell, rev),
            "admin_ratio": _safe_div(admin, rev),
            "rd_ratio": _safe_div(rd, rev),
            "total_opex_ratio": _safe_div((sell or 0) + (admin or 0) + (rd or 0), rev) if rev else None,
            "current_ratio": _safe_div(ca, cl),
            "debt_ratio": _safe_div(tl, ta),
            "roe": _safe_div(ni, eq),
            "roa": _safe_div(ni, ta),
        }

    for i in range(len(years) - 1):
        curr_yr, prev_yr = years[i], years[i + 1]
        curr, prev = metrics[curr_yr], metrics[prev_yr]
        for field in ("revenue", "net_income", "eps"):
            cv, pv = curr.get(field), prev.get(field)
            curr[f"{field}_yoy"] = (cv - pv) / abs(pv) * 100 if (cv is not None and pv) else None

    return metrics


def sanity_check(metrics_by_year: dict, years: list):
    warnings = []
    for yr in years:
        m = metrics_by_year.get(yr, {})
        gm = m.get("gross_margin")
        if gm is not None:
            if gm > 100:
                warnings.append({"level": "error", "field": f"{yr} 毛利率", "msg": f"{gm:.1f}% 超過 100%，數據可能有誤"})
            elif gm < -50:
                warnings.append({"level": "error", "field": f"{yr} 毛利率", "msg": f"{gm:.1f}% 低於 -50%，請確認是否為特殊損失年度"})
        cr = m.get("current_ratio")
        if cr is not None and cr < 0:
            warnings.append({"level": "error", "field": f"{yr} 流動比率", "msg": f"{cr:.1f}% 為負值，請檢查資產負債表數據"})
        dr = m.get("debt_ratio")
        if dr is not None and dr > 100:
            warnings.append({"level": "warn", "field": f"{yr} 負債比率", "msg": f"{dr:.1f}% 超過 100%，若非金融業則為警示訊號"})
        roe = m.get("roe")
        if roe is not None and roe > 100:
            warnings.append({"level": "warn", "field": f"{yr} ROE", "msg": f"{roe:.1f}% 超過 100%，可能為高槓桿，請確認股東權益是否偏低"})

    nm_list = [(yr, metrics_by_year[yr].get("net_margin")) for yr in years if yr in metrics_by_year]
    for i in range(1, len(nm_list)):
        yr_prev, nm_prev = nm_list[i - 1]
        yr_curr, nm_curr = nm_list[i]
        if nm_prev is not None and nm_curr is not None:
            delta = nm_curr - nm_prev
            if abs(delta) > 30:
                warnings.append({"level": "warn", "field": f"{yr_prev}→{yr_curr} 淨利率", "msg": f"波動 {delta:+.1f} 個百分點，建議確認是否有一次性損益"})
    return warnings


def analyze_stock(stock_id: str) -> dict:
    if not (stock_id.isdigit() and 4 <= len(stock_id) <= 6):
        raise GoodinfoFetchError("股票代碼格式錯誤，請輸入 4-6 碼數字")

    start_date = date(date.today().year - 5, 1, 1).isoformat()

    is_records = _request("TaiwanStockFinancialStatements", data_id=stock_id, start_date=start_date)
    is_data, years = _pivot_annual(is_records)
    if not years:
        raise GoodinfoFetchError(f"查無股票代碼 {stock_id} 的財報資料，請確認代碼是否正確")

    company_name = _company_name(stock_id)

    bs_records = _request("TaiwanStockBalanceSheet", data_id=stock_id, start_date=start_date)
    bs_data, _ = _pivot_annual(bs_records)

    cf_records = _request("TaiwanStockCashFlowsStatement", data_id=stock_id, start_date=start_date)
    cf_data, _ = _pivot_annual(cf_records)

    metrics = compute_metrics(is_data, bs_data, cf_data, years)
    warnings = sanity_check(metrics, years)

    metadata = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "source": "FinMind (api.finmindtrade.com)",
        "source_urls": {
            "financial_statements": f"https://finmind.github.io/tutor/TaiwanMarket/DataList/#taiwanstockfinancialstatements",
        },
        "mops_url": f"https://mops.twse.com.tw/mops/web/t05st01?step=1&co_id={stock_id}&TYPEK=sii",
        "years_covered": years,
        "currency": "TWD 億元",
    }

    return {
        "stock_id": stock_id,
        "company_name": company_name,
        "years": years,
        "metrics": metrics,
        "verification": {"sanity": warnings, "sanity_pass": all(w["level"] != "error" for w in warnings)},
        "metadata": metadata,
    }
