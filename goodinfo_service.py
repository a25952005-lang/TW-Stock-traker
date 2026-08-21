"""
goodinfo_service.py
從 Goodinfo.tw 抓取台灣上市/上櫃公司財報，計算三維財務指標。
邏輯改編自 taiwan-stock-analysis skill 的 fetch_goodinfo.py。
"""

import time
import requests
from bs4 import BeautifulSoup

TZ_OFFSET = -480  # 台灣 UTC+8


class GoodinfoFetchError(Exception):
    pass


# ─── 抓取層 ───────────────────────────────────────────────

def _get_client_key():
    now_ms = time.time() * 1000
    days_since_epoch = now_ms / 86400000
    days_adjusted = days_since_epoch - TZ_OFFSET / 1440
    client_key = f"2.8|38057.1435627105|46946.0324515993|{TZ_OFFSET}|{days_adjusted}|{days_adjusted}"
    return client_key, days_adjusted


def _fetch_report(stock_id: str, rpt_cat: str, days_adjusted: float, client_key: str) -> BeautifulSoup:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://goodinfo.tw/",
    }
    cookies = {"CLIENT_KEY": client_key}
    url = (
        f"https://goodinfo.tw/tw/StockFinDetail.asp?RPT_CAT={rpt_cat}"
        f"&STOCK_ID={stock_id}&REINIT={days_adjusted:.10f}"
    )
    r = requests.get(url, headers=headers, cookies=cookies, timeout=15)
    r.encoding = "utf-8"
    if r.status_code != 200:
        raise GoodinfoFetchError(f"Goodinfo 回應狀態碼 {r.status_code}（股票代碼 {stock_id}）")
    return BeautifulSoup(r.text, "html.parser")


def _parse_table(soup: BeautifulSoup):
    """解析 Goodinfo 財報表格，回傳 ({欄位名: {年度: 數值}}, [年度...])"""
    tables = soup.find_all("table")
    if len(tables) < 7:
        return {}, []

    t = tables[6]
    rows = t.find_all("tr")
    years = []
    data = {}

    for i, row in enumerate(rows):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        row_data = [c.get_text(strip=True) for c in cells]

        if i == 0 and any(y in row_data for y in ["2025", "2024", "2023", "2022", "2021", "2020"]):
            for val in row_data[1:]:
                if len(val) == 4 and val.isdigit():
                    years.append(val)
            continue

        if len(row_data) >= 3 and row_data[0]:
            field_name = row_data[0]
            values = {}
            val_cols = row_data[1:]
            for j, yr in enumerate(years):
                if j * 2 < len(val_cols):
                    raw = val_cols[j * 2]
                    try:
                        values[yr] = float(raw.replace(",", ""))
                    except Exception:
                        values[yr] = None
            if values:
                data[field_name] = values

    return data, years


def _company_name(soup: BeautifulSoup, stock_id: str) -> str:
    title = soup.find("title")
    if title and title.text:
        txt = title.text.strip()
        # Goodinfo 標題通常長得像「台積電(2330) 財務...」
        if "(" in txt:
            return txt.split("(")[0].strip()
    return stock_id


# ─── 指標計算層 ───────────────────────────────────────────

def _find_key(table: dict, *keywords: str):
    for k in table:
        if all(kw in k for kw in keywords):
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
        "rev": _find_key(is_d, "營業收入合計") or _find_key(is_d, "營業收入"),
        "gp": _find_key(is_d, "營業毛利"),
        "sell": _find_key(is_d, "推銷費用"),
        "admin": _find_key(is_d, "管理費用"),
        "rd": _find_key(is_d, "研究發展費用"),
        "op": _find_key(is_d, "營業利益") or _find_key(is_d, "營業利益（損失）"),
        "ni": _find_key(is_d, "稅後淨利"),
        "eps": _find_key(is_d, "每股", "盈餘"),
        "cash": _find_key(bs_d, "現金及約當現金"),
        "inv": _find_key(bs_d, "存貨"),
        "ca": _find_key(bs_d, "流動資產合計"),
        "cl": _find_key(bs_d, "流動負債合計"),
        "tl": _find_key(bs_d, "負債總額"),
        "ta": _find_key(bs_d, "資產總額"),
        "eq": _find_key(bs_d, "股東權益總額"),
        "op_cf": _find_key(cf_d, "營業活動之淨現金流入"),
        "inv_cf": _find_key(cf_d, "投資活動之淨現金流入"),
        "fin_cf": _find_key(cf_d, "融資活動之淨現金流入"),
        "capex": _find_key(cf_d, "固定資產"),
        "div_cash": _find_key(cf_d, "發放現金股利"),
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

        fcf = None
        if op_cf is not None and capex is not None:
            fcf = op_cf + capex  # capex 為負值代表資產增加

        metrics[yr] = {
            "revenue": rev,
            "gross_profit": gp,
            "sell_exp": sell,
            "admin_exp": admin,
            "rd_exp": rd,
            "op_income": op,
            "net_income": ni,
            "eps": eps,
            "cash": cash,
            "inventory": inv,
            "current_assets": ca,
            "current_liabilities": cl,
            "total_liabilities": tl,
            "total_assets": ta,
            "equity": eq,
            "operating_cf": op_cf,
            "investing_cf": inv_cf,
            "financing_cf": fin_cf,
            "capex": capex,
            "cash_dividend": div_cash,
            "fcf": fcf,
            "gross_margin": _safe_div(gp, rev),
            "op_margin": _safe_div(op, rev),
            "net_margin": _safe_div(ni, rev),
            "sell_ratio": _safe_div(sell, rev),
            "admin_ratio": _safe_div(admin, rev),
            "rd_ratio": _safe_div(rd, rev),
            "total_opex_ratio": _safe_div(
                (sell or 0) + (admin or 0) + (rd or 0), rev
            ) if rev else None,
            "current_ratio": _safe_div(ca, cl),
            "debt_ratio": _safe_div(tl, ta),
            "roe": _safe_div(ni, eq),
            "roa": _safe_div(ni, ta),
        }

    # 年增率 (YoY)，依年度由舊到新排序後計算
    ordered = years  # years 已由 Goodinfo 依新到舊排列，保留原順序給前端自行處理
    for i in range(len(ordered) - 1):
        curr_yr, prev_yr = ordered[i], ordered[i + 1]
        curr, prev = metrics[curr_yr], metrics[prev_yr]
        for field in ("revenue", "net_income", "eps"):
            cv, pv = curr.get(field), prev.get(field)
            curr[f"{field}_yoy"] = (
                (cv - pv) / abs(pv) * 100 if (cv is not None and pv) else None
            )

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


# ─── 對外主函式 ───────────────────────────────────────────

def analyze_stock(stock_id: str) -> dict:
    if not (stock_id.isdigit() and 4 <= len(stock_id) <= 6):
        raise GoodinfoFetchError("股票代碼格式錯誤，請輸入 4-6 碼數字")

    client_key, days_adjusted = _get_client_key()

    is_soup = _fetch_report(stock_id, "IS_YEAR", days_adjusted, client_key)
    is_data, years = _parse_table(is_soup)
    if not years:
        raise GoodinfoFetchError(f"查無股票代碼 {stock_id} 的財報資料，請確認代碼是否正確")
    company_name = _company_name(is_soup, stock_id)

    time.sleep(1)
    bs_soup = _fetch_report(stock_id, "BS_YEAR", days_adjusted, client_key)
    bs_data, _ = _parse_table(bs_soup)

    time.sleep(1)
    cf_soup = _fetch_report(stock_id, "CF_YEAR", days_adjusted, client_key)
    cf_data, _ = _parse_table(cf_soup)

    years3 = years[:3]
    metrics = compute_metrics(is_data, bs_data, cf_data, years3)
    warnings = sanity_check(metrics, years3)

    metadata = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "source": "Goodinfo.tw",
        "source_urls": {
            "income_statement": f"https://goodinfo.tw/tw/StockFinDetail.asp?RPT_CAT=IS_YEAR&STOCK_ID={stock_id}",
            "balance_sheet": f"https://goodinfo.tw/tw/StockFinDetail.asp?RPT_CAT=BS_YEAR&STOCK_ID={stock_id}",
            "cash_flow": f"https://goodinfo.tw/tw/StockFinDetail.asp?RPT_CAT=CF_YEAR&STOCK_ID={stock_id}",
        },
        "mops_url": f"https://mops.twse.com.tw/mops/web/t05st01?step=1&co_id={stock_id}&TYPEK=sii",
        "years_covered": years3,
        "currency": "TWD 億元",
    }

    return {
        "stock_id": stock_id,
        "company_name": company_name,
        "years": years3,
        "metrics": metrics,
        "verification": {"sanity": warnings, "sanity_pass": all(w["level"] != "error" for w in warnings)},
        "metadata": metadata,
    }
