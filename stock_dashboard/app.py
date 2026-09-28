"""短線篩選看板：streamlit run app.py"""
from __future__ import annotations

import re
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import data_source as ds
import screening

st.set_page_config(page_title="短線篩選看板", page_icon="📈", layout="wide")

UP, DOWN = "#e53935", "#2e7d32"  # 台股慣例：紅漲綠跌

st.markdown(
    """
    <style>
    .gate {border-radius:10px;padding:12px 14px;margin-bottom:8px;border:1px solid #ddd;}
    .gate.pass {background:rgba(229,57,53,.08);border-color:#e53935;}
    .gate.fail {background:rgba(46,125,50,.08);border-color:#2e7d32;}
    .gate.na   {background:rgba(128,128,128,.08);}
    .gate h4 {margin:0 0 4px 0;font-size:1rem;}
    .gate .sum {font-weight:600;margin-bottom:6px;}
    .gate ul {margin:0;padding-left:18px;font-size:.88rem;}
    .rating {font-size:1.4rem;font-weight:700;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------- 側邊欄設定 ----------------
with st.sidebar:
    st.header("⚙️ 設定")
    raw = st.text_input("輸入股號（可多檔，以空白或逗號分隔）", value="2330 2317 2454")
    codes = list(dict.fromkeys(re.findall(r"[0-9A-Za-z]{4,6}", raw)))
    st.subheader("均線參數")
    c1, c2, c3 = st.columns(3)
    ma_s = c1.number_input("短", 2, 30, 5)
    ma_m = c2.number_input("中", 5, 120, 20)
    ma_l = c3.number_input("長", 10, 240, 60)
    inst_days = st.slider("法人買賣超統計天數", 3, 20, 5)
    auto = st.toggle("自動更新股價", value=True)
    interval = st.select_slider("更新頻率（秒）", options=[15, 30, 60, 120, 300], value=60)
    if st.button("🔄 立即重新抓取全部資料"):
        st.cache_data.clear()
    st.caption(
        "資料來源：FinMind 開放資料（日K、三大法人）、證交所基本市況報導（即時價）。"
        "盤中即時價會併入當日 K 棒重新計算指標。本工具僅供研究參考，不構成投資建議。"
    )


# ---------------- 資料抓取（快取） ----------------
@st.cache_data(ttl=24 * 3600, show_spinner=False)
def get_info(code: str) -> dict:
    return ds.stock_info(code)


@st.cache_data(ttl=1800, show_spinner=False)
def get_prices(code: str, market: str) -> pd.DataFrame:
    return ds.daily_prices(code, market)


@st.cache_data(ttl=1800, show_spinner=False)
def get_inst(code: str) -> pd.DataFrame | None:
    return ds.institutional(code)


@st.cache_data(ttl=10, show_spinner=False)
def get_quote(code: str, market: str) -> dict | None:
    return ds.realtime_quote(code, market)


def analyze(code: str):
    info = get_info(code)
    prices = get_prices(code, info["market"])
    quote = get_quote(code, info["market"])
    merged = ds.merge_realtime(prices, quote)
    name = info["name"] if info["name"] != code else (quote or {}).get("name") or code
    rep = screening.evaluate(
        code, name, merged, get_inst(code), ma=(int(ma_s), int(ma_m), int(ma_l)), inst_days=inst_days
    )
    return rep, quote


# ---------------- 圖表 ----------------
def make_chart(rep: screening.Report, inst: pd.DataFrame | None) -> go.Figure:
    df = rep.frame.tail(120)
    x = df.index.strftime("%m/%d")
    fig = make_subplots(
        rows=5, cols=1, shared_xaxes=True, vertical_spacing=0.025,
        row_heights=[0.44, 0.12, 0.14, 0.15, 0.15],
        subplot_titles=("K線與均線", "成交量(張)", "RSI(14)", "MACD 柱狀體", "三大法人買賣超(張)"),
    )
    fig.add_trace(go.Candlestick(
        x=x, open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="K",
        increasing_line_color=UP, decreasing_line_color=DOWN,
        increasing_fillcolor=UP, decreasing_fillcolor=DOWN,
    ), 1, 1)
    for w, color in zip((ma_s, ma_m, ma_l), ("#fb8c00", "#1e88e5", "#8e24aa")):
        fig.add_trace(go.Scatter(x=x, y=df[f"ma{w}"], name=f"{w}MA", line=dict(width=1.3, color=color)), 1, 1)
    vol_color = [UP if c >= o else DOWN for o, c in zip(df["open"], df["close"])]
    fig.add_trace(go.Bar(x=x, y=df["volume"], marker_color=vol_color, name="量", showlegend=False), 2, 1)
    fig.add_trace(go.Scatter(x=x, y=df["rsi"], name="RSI", line=dict(color="#6d4c41")), 3, 1)
    fig.add_hline(y=50, line_dash="dash", line_color="gray", row=3, col=1)
    fig.add_hline(y=80, line_dash="dot", line_color=UP, row=3, col=1)
    fig.add_hline(y=20, line_dash="dot", line_color=DOWN, row=3, col=1)
    fig.add_trace(go.Bar(x=x, y=df["hist"], name="OSC", showlegend=False,
                         marker_color=[UP if v > 0 else DOWN for v in df["hist"].fillna(0)]), 4, 1)
    fig.add_trace(go.Scatter(x=x, y=df["dif"], name="DIF", line=dict(width=1, color="#fb8c00")), 4, 1)
    fig.add_trace(go.Scatter(x=x, y=df["dea"], name="MACD", line=dict(width=1, color="#1e88e5")), 4, 1)
    if inst is not None and not inst.empty:
        ii = inst.reindex(df.index).fillna(0)
        for col, label, color in (("foreign", "外資", "#1e88e5"), ("trust", "投信", "#e53935"), ("dealer", "自營", "#fb8c00")):
            fig.add_trace(go.Bar(x=x, y=ii[col], name=label, marker_color=color), 5, 1)
    fig.update_layout(
        height=900, barmode="relative", xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=70, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.04, x=0),
    )
    fig.update_xaxes(type="category", nticks=12)
    return fig


def gate_card(g: screening.GateResult) -> str:
    cls = "na" if g.passed is None else "pass" if g.passed else "fail"
    items = "".join(f"<li>{d}</li>" for d in g.details)
    return f'<div class="gate {cls}"><h4>{g.title}　{g.badge}</h4><div class="sum">{g.summary}</div><ul>{items}</ul></div>'


def mark(g: screening.GateResult) -> str:
    return "⚪" if g.passed is None else "✅" if g.passed else "❌"


# ---------------- 看板主體（自動更新） ----------------
def dashboard():
    now = datetime.now()
    st.title("📈 短線篩選看板")
    st.caption(
        f"最後更新：{now:%Y-%m-%d %H:%M:%S}"
        + (f"｜每 {interval} 秒自動更新" if auto else "｜自動更新已關閉")
    )
    if not codes:
        st.info("請在左側輸入股號，例如 2330")
        return

    reports, quotes, errors = [], {}, []
    for code in codes:
        try:
            rep, q = analyze(code)
            reports.append(rep)
            quotes[code] = q
        except Exception as e:  # noqa: BLE001
            errors.append(f"{code}：{e}")
    for e in errors:
        st.error(e)
    if not reports:
        return

    # ---- 總覽表 ----
    st.subheader("🧭 篩選總覽")
    rows = []
    for r in sorted(reports, key=lambda r: -r.score):
        g = r.gates
        rows.append({
            "股號": r.code, "名稱": r.name, "現價": round(r.last["close"], 2),
            "漲跌%": round(r.last["pct"], 2),
            "①均線": mark(g[0]), "②RSI": mark(g[1]), "③MACD": mark(g[2]), "④主力": mark(g[3]),
            "通過": f"{r.score}/4", "評等": r.rating,
        })
    table = pd.DataFrame(rows)
    st.dataframe(
        table.style.map(lambda v: f"color:{UP}" if v > 0 else f"color:{DOWN}" if v < 0 else "", subset=["漲跌%"])
        .format({"現價": "{:,.2f}", "漲跌%": "{:+.2f}"}),
        hide_index=True, width="stretch",
    )

    # ---- 個股詳細 ----
    tabs = st.tabs([f"{r.code} {r.name}" for r in reports])
    for tab, rep in zip(tabs, reports):
        with tab:
            q = quotes.get(rep.code)
            L = rep.last
            m = st.columns(6)
            m[0].metric("股價", f"{L['close']:,.2f}", f"{L['change']:+.2f} ({L['pct']:+.2f}%)", delta_color="inverse")
            m[1].metric("成交量(張)", f"{L['volume']:,.0f}",
                        None if pd.isna(L["vol_ratio"]) else f"{L['vol_ratio']:.2f} 倍均量", delta_color="off")
            m[2].metric("RSI", f"{L['rsi']:.1f}")
            m[3].metric("KD", f"{L['k']:.0f} / {L['d']:.0f}")
            m[4].metric(f"{ma_m}MA 乖離", "—" if pd.isna(L["bias"]) else f"{L['bias']:+.2f}%")
            m[5].metric("關卡通過", f"{rep.score} / 4")
            st.caption(
                f"報價時間：{q['time']:%Y-%m-%d %H:%M:%S}（即時）" if q
                else f"即時報價取得失敗，使用 {L['date']:%Y-%m-%d} 收盤資料"
            )

            color = UP if rep.score >= 3 else "#f9a825" if rep.score == 2 else DOWN
            st.markdown(
                f'<div class="rating" style="color:{color}">建議：{rep.rating}</div><div>{rep.advice}</div>',
                unsafe_allow_html=True,
            )
            st.write("")
            cols = st.columns(2)
            for i, g in enumerate(rep.gates):
                cols[i % 2].markdown(gate_card(g), unsafe_allow_html=True)
            if rep.notes:
                st.markdown("**📝 其他觀察**\n\n" + "\n".join(f"- {n}" for n in rep.notes))
            st.plotly_chart(make_chart(rep, get_inst(rep.code)), width="stretch",
                            key=f"chart_{rep.code}")


if auto:
    st.fragment(run_every=interval)(dashboard)()
else:
    dashboard()
