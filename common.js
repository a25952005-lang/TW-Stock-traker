const API = "";

async function apiGet(path) {
  const res = await fetch(API + path);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `請求失敗 (${res.status})`);
  }
  return res.json();
}

async function apiPost(path, data) {
  const res = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `請求失敗 (${res.status})`);
  }
  return res.json();
}

async function apiDelete(path) {
  const res = await fetch(API + path, { method: "DELETE" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `請求失敗 (${res.status})`);
  }
  return res.json();
}

function fmtNum(v, digits = 1) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  return Number(v).toLocaleString("zh-TW", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function fmtPct(v, digits = 1) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  return `${v >= 0 ? "" : ""}${Number(v).toFixed(digits)}%`;
}

function yoyClass(v) {
  if (v === null || v === undefined || isNaN(v)) return "neutral";
  return v >= 0 ? "up" : "down";
}

function yoyArrow(v) {
  if (v === null || v === undefined || isNaN(v)) return "";
  return v >= 0 ? "▲" : "▼";
}

// 把「元」轉成「億元」方便閱讀（證交所 OpenAPI 金額欄位通常是元）
function fmtYiFromYuan(v, digits = 1) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  return fmtNum(v / 1e8, digits);
}
