"""
calendar_service.py — 市場行事曆
三種事件來源：
  1. 個股除權息預告（TWSE OpenAPI TWTB4U，只有「當月」資料，屬於官方預告非長期行事曆）
  2. 財報法定公告截止日（依證交所規定的固定規則計算，年年適用，不需外部資料）
  3. 總體經濟事件（央行理監事會議、CPI 公布等）— 存在 macro_events.json，
     因為這類日期每年官方另行公告、且會微調，先用使用者可自行編輯的檔案維護，
     避免我這邊自己編出不準確的日期給你。
"""

import json
import time
from datetime import date
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent / "data"
MACRO_EVENTS_FILE = DATA_DIR / "macro_events.json"

TWSE_BASE = "https://openapi.twse.com.tw/v1"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


# ─── 1. 除權息預告（即時抓取）─────────────────────────────

def get_dividend_calendar(stock_codes: list):
    """回傳觀察清單中，本月有除權息預告的股票。"""
    try:
        r = requests.get(f"{TWSE_BASE}/exchangeReport/TWTB4U", headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": str(e), "events": []}

    codes = set(stock_codes)
    events = []
    for row in data:
        code = row.get("股票代號") or row.get("證券代號")
        if code not in codes:
            continue
        events.append({
            "type": "dividend",
            "stock_id": code,
            "stock_name": row.get("股票名稱") or row.get("證券名稱"),
            "date": row.get("除權息日期") or row.get("資料日期"),
            "detail": f"除權息前收盤價 {row.get('除權息前收盤價', '—')}",
        })
    return {"events": events}


# ─── 2. 財報法定公告截止日（規則計算，不用連網）──────────────

def get_report_deadlines(stock_codes: list, months_ahead: int = 6):
    """
    台灣上市櫃公司財報法定公告截止日（一般業）：
      Q1 季報 → 5/15
      Q2 半年報 → 8/14
      Q3 季報 → 11/14
      年報（Q4）→ 次年 3/31
    這是法規規定的「最晚」截止日，實際公告日通常更早；金融/保險業截止日略有不同，
    此處採一般行業規則，僅供參考排程用。
    """
    today = date.today()
    deadlines_template = [
        (5, 15, "第一季季報"),
        (8, 14, "上半年報"),
        (11, 14, "第三季季報"),
        (3, 31, "年報（次年公告）"),
    ]

    events = []
    for year_offset in (0, 1):
        yr = today.year + year_offset
        for month, day, label in deadlines_template:
            try:
                d = date(yr, month, day)
            except ValueError:
                continue
            delta_days = (d - today).days
            if 0 <= delta_days <= months_ahead * 31:
                for code in stock_codes:
                    events.append({
                        "type": "report_deadline",
                        "stock_id": code,
                        "date": d.isoformat(),
                        "detail": f"{label}法定公告截止日",
                    })
    events.sort(key=lambda e: e["date"])
    return events


# ─── 3. 總體經濟事件（使用者可編輯的靜態清單）─────────────────

DEFAULT_MACRO_EVENTS = [
    {
        "date": None,
        "recurrence": "每年 3、6、9、12 月，約當月中下旬",
        "title": "中央銀行理監事聯席會議",
        "detail": "公布重貼現率等政策利率決議，確切日期請至央行官網「理監事會議」頁面確認",
        "source_url": "https://www.cbc.gov.tw/tw/lp-46-1.html",
    },
    {
        "date": None,
        "recurrence": "每月上旬（美國時間）",
        "title": "美國 FOMC / CPI 公布（如當月有會議）",
        "detail": "影響全球資金風向與台股連動，確切日期請至 Fed 官網確認",
        "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    },
    {
        "date": None,
        "recurrence": "每月 5 號左右",
        "title": "台灣消費者物價指數 (CPI) 公布",
        "detail": "行政院主計總處公布上月 CPI 年增率",
        "source_url": "https://www.dgbas.gov.tw/",
    },
]


def _load_macro_events():
    if MACRO_EVENTS_FILE.exists():
        try:
            return json.loads(MACRO_EVENTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    DATA_DIR.mkdir(exist_ok=True)
    MACRO_EVENTS_FILE.write_text(json.dumps(DEFAULT_MACRO_EVENTS, ensure_ascii=False, indent=2), encoding="utf-8")
    return DEFAULT_MACRO_EVENTS


def get_macro_events():
    return _load_macro_events()


def save_macro_events(events: list):
    DATA_DIR.mkdir(exist_ok=True)
    MACRO_EVENTS_FILE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── 整合 ────────────────────────────────────────────────

def get_calendar(stock_codes: list):
    dividend = get_dividend_calendar(stock_codes)
    report_deadlines = get_report_deadlines(stock_codes)
    macro = get_macro_events()
    return {
        "dividend_events": dividend.get("events", []),
        "dividend_error": dividend.get("error"),
        "report_deadlines": report_deadlines,
        "macro_events": macro,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }
