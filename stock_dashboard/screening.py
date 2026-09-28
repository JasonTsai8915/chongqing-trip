"""短線篩選檢核機制：四道關卡 + 綜合建議。"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

import indicators


@dataclass
class GateResult:
    key: str
    title: str
    passed: bool | None  # None = 資料不足無法判斷
    summary: str
    details: list[str] = field(default_factory=list)

    @property
    def badge(self) -> str:
        if self.passed is None:
            return "⚪ 無資料"
        return "🟢 通過" if self.passed else "🔴 未通過"


@dataclass
class Report:
    code: str
    name: str
    last: dict
    gates: list[GateResult]
    score: int
    rating: str
    advice: str
    notes: list[str]
    frame: pd.DataFrame


def _fmt(v: float, nd: int = 2) -> str:
    return "—" if pd.isna(v) else f"{v:,.{nd}f}"


def check_ma(df: pd.DataFrame, short: int, mid: int, long: int) -> GateResult:
    """第一道關卡：短中長均線多頭排列，且 K 線站穩所有均線之上。"""
    row = df.iloc[-1]
    ms, mm, ml = row[f"ma{short}"], row[f"ma{mid}"], row[f"ma{long}"]
    title = f"第一關・均線（{short}/{mid}/{long}MA）"
    if pd.isna(ml):
        return GateResult("ma", title, None, f"K 線不足 {long} 根，無法計算長均線")

    aligned = ms > mm > ml
    above = row["close"] > max(ms, mm, ml)
    # 連續站上所有均線的天數
    cols = [f"ma{short}", f"ma{mid}", f"ma{long}"]
    above_series = df["close"] > df[cols].max(axis=1)
    streak = 0
    for v in reversed(above_series.tolist()):
        if not v:
            break
        streak += 1
    rising = df[f"ma{mid}"].iloc[-1] > df[f"ma{mid}"].iloc[-2]

    details = [
        f"收盤 {_fmt(row['close'])}｜{short}MA {_fmt(ms)}｜{mid}MA {_fmt(mm)}｜{long}MA {_fmt(ml)}",
        f"多頭排列（{short}>{mid}>{long}）：{'是' if aligned else '否'}",
        f"收盤站上所有均線：{'是' if above else '否'}（已連續 {streak} 日）",
        f"{mid}MA 方向：{'上揚' if rising else '下彎'}",
    ]
    passed = bool(aligned and above)
    if passed:
        summary = "多頭排列且站穩均線之上" + ("" if streak >= 2 else "（剛站上，留意是否站穩）")
    elif above:
        summary = "股價在均線上，但均線尚未多頭排列"
    elif aligned:
        summary = "均線多頭排列，但股價跌落均線之下"
    else:
        summary = "均線未成多頭、股價未站上均線"
    return GateResult("ma", title, passed, summary, details)


def check_rsi(df: pd.DataFrame) -> GateResult:
    """第二道關卡：RSI > 50 多空分水嶺，且方向向上。"""
    cur, prev = df["rsi"].iloc[-1], df["rsi"].iloc[-2]
    title = "第二關・RSI(14)"
    if pd.isna(cur) or pd.isna(prev):
        return GateResult("rsi", title, None, "資料不足無法計算 RSI")
    above50 = cur > 50
    up = cur > prev
    details = [
        f"RSI 今 {_fmt(cur)}｜昨 {_fmt(prev)}（{'+' if up else ''}{_fmt(cur - prev)}）",
        f"位於 50 分水嶺之上：{'是' if above50 else '否'}",
        f"方向：{'向上' if up else '向下'}",
    ]
    if cur >= 80:
        details.append("⚠️ RSI ≥ 80 進入超買區，追價風險升高")
    passed = bool(above50 and up)
    if passed:
        summary = "多方區且向上"
    elif above50:
        summary = "在 50 之上但轉弱向下"
    elif up:
        summary = "向上但仍在 50 之下（空方區）"
    else:
        summary = "空方區且向下"
    return GateResult("rsi", title, passed, summary, details)


def check_macd(df: pd.DataFrame) -> GateResult:
    """第三道關卡：MACD 柱狀體為正（紅柱），且動能擴張或翻揚。"""
    h, hp = df["hist"].iloc[-1], df["hist"].iloc[-2]
    hpp = df["hist"].iloc[-3] if len(df) >= 3 else float("nan")
    title = "第三關・MACD(12,26,9)"
    if pd.isna(h) or pd.isna(hp):
        return GateResult("macd", title, None, "資料不足無法計算 MACD")
    red = h > 0
    growing = h > hp
    turned_red = red and hp <= 0
    turned_up = growing and not pd.isna(hpp) and hp <= hpp  # 先縮後放 = 翻揚
    row = df.iloc[-1]
    details = [
        f"DIF {_fmt(row['dif'])}｜MACD {_fmt(row['dea'])}｜柱狀體 今 {_fmt(h, 3)}／昨 {_fmt(hp, 3)}",
        f"柱狀體顏色：{'紅柱(正)' if red else '綠柱(負)'}",
        f"動能：{'擴張' if growing else '收斂'}" + ("（翻揚）" if turned_up else ""),
        f"DIF {'在' if row['dif'] > 0 else '不在'}零軸之上",
    ]
    passed = bool(red and growing)
    if turned_red:
        summary = "柱狀體由綠翻紅，動能轉強"
    elif passed and turned_up:
        summary = "紅柱縮後再放大（翻揚）"
    elif passed:
        summary = "紅柱持續擴張"
    elif red:
        summary = "紅柱但動能收斂"
    elif growing:
        summary = "綠柱縮短，尚未翻紅"
    else:
        summary = "綠柱擴大，空方動能"
    return GateResult("macd", title, passed, summary, details)


def check_institutional(inst: pd.DataFrame | None, days: int = 5) -> GateResult:
    """第四道關卡：主力（三大法人）進出。

    inst：index 為日期，欄位 foreign / trust / dealer / total（買賣超張數）。
    通過條件：近 N 日三大法人合計買超，且外資或投信至少一方買超。
    """
    title = f"第四關・主力進出（三大法人 近{days}日）"
    if inst is None or inst.empty:
        return GateResult("inst", title, None, "取不到法人買賣超資料")
    recent = inst.tail(days)
    s = recent.sum()
    last = inst.iloc[-1]
    streak = 0
    sign = 1 if last["total"] > 0 else -1 if last["total"] < 0 else 0
    if sign:
        for v in reversed(inst["total"].tolist()):
            if (v > 0 and sign > 0) or (v < 0 and sign < 0):
                streak += 1
            else:
                break
    streak_txt = f"連{'買' if sign > 0 else '賣'} {streak} 日" if sign else "持平"
    s20 = inst.tail(20)["total"].sum()
    details = [
        f"最新（{inst.index[-1]:%m/%d}）合計 {last['total']:+,.0f} 張｜外資 {last['foreign']:+,.0f}｜投信 {last['trust']:+,.0f}｜自營 {last['dealer']:+,.0f}",
        f"近{days}日：合計 {s['total']:+,.0f}｜外資 {s['foreign']:+,.0f}｜投信 {s['trust']:+,.0f}｜自營 {s['dealer']:+,.0f}",
        f"近20日合計 {s20:+,.0f} 張；三大法人{streak_txt}",
    ]
    passed = bool(s["total"] > 0 and (s["foreign"] > 0 or s["trust"] > 0))
    if passed and s["foreign"] > 0 and s["trust"] > 0:
        summary = "外資、投信同步買超（土洋合作）"
    elif passed:
        summary = f"法人偏多，{'外資' if s['foreign'] > 0 else '投信'}主導買超"
    elif s["total"] > 0:
        summary = "合計買超但主要來自自營商，籌碼偏短線"
    else:
        summary = "法人近期站在賣方"
    return GateResult("inst", title, passed, summary, details)


def evaluate(
    code: str,
    name: str,
    price: pd.DataFrame,
    inst: pd.DataFrame | None,
    ma=(5, 20, 60),
    inst_days: int = 5,
) -> Report:
    short, mid, long = ma
    windows = sorted({short, mid, long, 10})
    df = indicators.add_all(price, ma_windows=windows)
    if len(df) < 3:
        raise ValueError("K 線資料不足")

    gates = [
        check_ma(df, short, mid, long),
        check_rsi(df),
        check_macd(df),
        check_institutional(inst, inst_days),
    ]
    tech_pass = sum(1 for g in gates[:3] if g.passed)
    score = sum(1 for g in gates if g.passed)

    row, prev = df.iloc[-1], df.iloc[-2]
    notes: list[str] = []
    bias = (row["close"] / row[f"ma{mid}"] - 1) * 100 if not pd.isna(row[f"ma{mid}"]) else float("nan")
    if not pd.isna(bias) and bias > 10:
        notes.append(f"⚠️ 乖離 {mid}MA 達 {bias:.1f}%，勿追高，等回測再佈局")
    if row["rsi"] >= 80:
        notes.append("⚠️ RSI 超買，短線易震盪")
    vol_ratio = row["volume"] / row["vol_ma5"] if row["vol_ma5"] else float("nan")
    if not pd.isna(vol_ratio):
        if vol_ratio >= 1.5 and row["close"] > prev["close"]:
            notes.append(f"📈 價漲量增（量為 5 日均量 {vol_ratio:.1f} 倍）")
        elif vol_ratio >= 1.5 and row["close"] < prev["close"]:
            notes.append(f"📉 價跌量增（量為 5 日均量 {vol_ratio:.1f} 倍），留意出貨")
    if row["k"] > row["d"] and prev["k"] <= prev["d"]:
        notes.append("KD 黃金交叉")
    elif row["k"] < row["d"] and prev["k"] >= prev["d"]:
        notes.append("KD 死亡交叉")

    low10 = df["low"].tail(10).min()
    supports = [v for v in (row[f"ma{mid}"], low10) if not pd.isna(v) and v < row["close"]]
    stop = max(supports) if supports else low10
    notes.append(f"🛡️ 停損參考：{_fmt(stop)}（{mid}MA 與近 10 日低點較高者，跌破即出場）")

    inst_ok = gates[3].passed
    if tech_pass == 3 and inst_ok:
        rating, advice = "強勢多頭", "三道技術關卡全數通過且法人站買方，可列入短線進場／續抱名單。"
    elif tech_pass == 3:
        rating, advice = "技術面轉強", "技術面三關全過，但籌碼未同步，建議小量試單並觀察法人動向。"
    elif tech_pass == 2:
        rating, advice = "偏多觀察", "僅部分關卡通過，列入觀察名單，等待未過關卡轉強再進場。"
    elif tech_pass == 1:
        rating, advice = "中性偏弱", "多數關卡未通過，暫不進場。"
    else:
        rating, advice = "弱勢迴避", "技術面全面偏弱，持有者宜減碼或嚴守停損。"

    last = {
        "date": df.index[-1],
        "close": row["close"],
        "change": row["close"] - prev["close"],
        "pct": (row["close"] / prev["close"] - 1) * 100,
        "open": row["open"],
        "high": row["high"],
        "low": row["low"],
        "volume": row["volume"],
        "rsi": row["rsi"],
        "k": row["k"],
        "d": row["d"],
        "hist": row["hist"],
        "bias": bias,
        "vol_ratio": vol_ratio,
    }
    return Report(code, name, last, gates, score, rating, advice, notes, df)
