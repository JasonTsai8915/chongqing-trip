"""資料來源：
- 日 K 線、三大法人買賣超、股票名稱：FinMind 開放資料 API（上市、上櫃皆可）
- 日 K 線備援：Yahoo Finance chart API
- 盤中即時報價：證交所基本市況報導 (mis.twse.com.tw)

若有 FinMind token，可設定環境變數 FINMIND_TOKEN 提高查詢額度。
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pandas as pd
import requests

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (short-term-screener)"}
TIMEOUT = 15


class DataError(RuntimeError):
    pass


def _finmind(dataset: str, code: str, start: date | None = None) -> pd.DataFrame:
    params = {"dataset": dataset, "data_id": code}
    if start:
        params["start_date"] = start.isoformat()
    token = os.environ.get("FINMIND_TOKEN")
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(FINMIND_URL, params=params, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    js = r.json()
    if js.get("status") not in (200, None):
        raise DataError(js.get("msg", "FinMind 查詢失敗"))
    return pd.DataFrame(js.get("data", []))


def stock_info(code: str) -> dict:
    """回傳 {'name': 名稱, 'market': 'twse' | 'tpex' | ''}。"""
    try:
        df = _finmind("TaiwanStockInfo", code)
    except Exception:
        return {"name": code, "market": ""}
    if df.empty:
        return {"name": code, "market": ""}
    row = df.iloc[-1]
    return {"name": row.get("stock_name", code), "market": row.get("type", "")}


def daily_prices(code: str, market: str = "", days: int = 400) -> pd.DataFrame:
    """日 K 線，index 為日期，欄位 open/high/low/close/volume（volume 單位：張）。"""
    start = date.today() - timedelta(days=days)
    try:
        df = _finmind("TaiwanStockPrice", code, start)
        if not df.empty:
            df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")[["open", "high", "low", "close", "volume"]].astype(float)
            df["volume"] = df["volume"] / 1000
            df = df[df["close"] > 0]  # 去除停牌日
            if len(df) > 30:
                return df
    except Exception:
        pass
    return _yahoo_prices(code, market)


def _yahoo_prices(code: str, market: str) -> pd.DataFrame:
    suffixes = [".TWO", ".TW"] if market == "tpex" else [".TW", ".TWO"]
    for suf in suffixes:
        try:
            r = requests.get(
                YAHOO_URL.format(symbol=code + suf),
                params={"range": "2y", "interval": "1d"},
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("Asia/Taipei")
            df = pd.DataFrame(
                {k: q[k] for k in ("open", "high", "low", "close", "volume")},
                index=idx.tz_localize(None).normalize(),
            ).dropna()
            df["volume"] = df["volume"] / 1000
            if len(df) > 30:
                return df
        except Exception:
            continue
    raise DataError(f"查無 {code} 的股價資料，請確認股號是否正確")


def institutional(code: str, days: int = 60) -> pd.DataFrame | None:
    """三大法人買賣超（張），index 為日期，欄位 foreign/trust/dealer/total。"""
    start = date.today() - timedelta(days=days)
    try:
        df = _finmind("TaiwanStockInstitutionalInvestorsBuySell", code, start)
    except Exception:
        return None
    if df.empty:
        return None
    df["net"] = (df["buy"].astype(float) - df["sell"].astype(float)) / 1000
    group = {
        "Foreign_Investor": "foreign",
        "Foreign_Dealer_Self": "foreign",
        "Investment_Trust": "trust",
        "Dealer_self": "dealer",
        "Dealer_Hedging": "dealer",
        "Dealer": "dealer",
    }
    df["who"] = df["name"].map(group)
    df = df.dropna(subset=["who"])
    out = df.pivot_table(index="date", columns="who", values="net", aggfunc="sum").fillna(0)
    for c in ("foreign", "trust", "dealer"):
        if c not in out:
            out[c] = 0.0
    out.index = pd.to_datetime(out.index)
    out["total"] = out[["foreign", "trust", "dealer"]].sum(axis=1)
    return out.sort_index()[["foreign", "trust", "dealer", "total"]]


def realtime_quote(code: str, market: str = "") -> dict | None:
    """證交所即時報價；非交易時段回傳最後一筆。失敗回傳 None。"""
    prefixes = ["otc", "tse"] if market == "tpex" else ["tse", "otc"]
    ex_ch = "|".join(f"{p}_{code}.tw" for p in prefixes)
    try:
        s = requests.Session()
        s.headers.update(HEADERS)
        s.get("https://mis.twse.com.tw/stock/index.jsp", timeout=TIMEOUT)
        r = s.get(MIS_URL, params={"ex_ch": ex_ch, "json": 1, "delay": 0}, timeout=TIMEOUT)
        r.raise_for_status()
        arr = r.json().get("msgArray", [])
    except Exception:
        return None
    for m in arr:
        price = _num(m.get("z"))
        if price is None:  # 尚未成交或瞬間無成交價 → 用最佳買價
            price = _num((m.get("b") or "").split("_")[0])
        if price is None:
            continue
        try:
            ts = datetime.strptime(f"{m['d']} {m['t']}", "%Y%m%d %H:%M:%S")
        except (KeyError, ValueError):
            ts = datetime.now()
        return {
            "price": price,
            "open": _num(m.get("o")) or price,
            "high": _num(m.get("h")) or price,
            "low": _num(m.get("l")) or price,
            "prev_close": _num(m.get("y")),
            "volume": _num(m.get("v")) or 0.0,  # 張
            "time": ts,
            "name": m.get("n", ""),
        }
    return None


def _num(v) -> float | None:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def merge_realtime(prices: pd.DataFrame, quote: dict | None) -> pd.DataFrame:
    """把即時報價併入日 K：同日則更新最後一根，新交易日則新增一根。"""
    if not quote or prices.empty:
        return prices
    df = prices.copy()
    day = pd.Timestamp(quote["time"].date())
    bar = {
        "open": quote["open"],
        "high": quote["high"],
        "low": quote["low"],
        "close": quote["price"],
        "volume": quote["volume"],
    }
    last_day = df.index[-1]
    if day == last_day:
        for k, v in bar.items():
            df.loc[last_day, k] = v
    elif day > last_day:
        df.loc[day] = bar
    return df
