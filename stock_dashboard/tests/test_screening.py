from datetime import datetime

import numpy as np
import pandas as pd
import pytest

import data_source as ds
import indicators
import screening


def make_prices(closes):
    idx = pd.bdate_range("2026-01-01", periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c.shift(1).fillna(c), "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1000.0})


def uptrend(n=120):
    # 穩定上漲並在最後幾天加速 → 所有技術關卡應通過
    base = np.linspace(100, 150, n - 5) + 2 * np.sin(np.arange(n - 5))
    return list(base) + [151, 153, 156, 160, 165]


def downtrend(n=120):
    return list(np.linspace(200, 120, n))


def inst_frame(values):
    idx = pd.bdate_range("2026-05-01", periods=len(values))
    f = pd.Series(values, index=idx, dtype=float)
    df = pd.DataFrame({"foreign": f, "trust": f / 2, "dealer": 0.0})
    df["total"] = df[["foreign", "trust", "dealer"]].sum(axis=1)
    return df


def test_rsi_bounds_and_trend():
    r = indicators.rsi(pd.Series(uptrend(), dtype=float))
    assert r.dropna().between(0, 100).all()
    assert r.iloc[-1] > 70
    r2 = indicators.rsi(pd.Series(downtrend(), dtype=float))
    assert r2.iloc[-1] < 30


def test_macd_hist_is_dif_minus_dea():
    m = indicators.macd(pd.Series(uptrend(), dtype=float))
    assert np.allclose(m["hist"], m["dif"] - m["dea"])


def test_uptrend_passes_all_gates():
    rep = screening.evaluate("0000", "測試", make_prices(uptrend()), inst_frame([100] * 20))
    assert [g.passed for g in rep.gates] == [True, True, True, True]
    assert rep.score == 4
    assert rep.rating == "強勢多頭"


def test_downtrend_fails_technical_gates():
    rep = screening.evaluate("0000", "測試", make_prices(downtrend()), inst_frame([-100] * 20))
    assert not any(g.passed for g in rep.gates)
    assert rep.rating == "弱勢迴避"


def test_missing_institutional_is_unknown():
    rep = screening.evaluate("0000", "測試", make_prices(uptrend()), None)
    assert rep.gates[3].passed is None
    assert rep.rating == "技術面轉強"


def test_rsi_above_50_but_falling_fails():
    closes = uptrend() + [163]  # 高檔拉回一天
    df = indicators.add_all(make_prices(closes), (5, 10, 20, 60))
    g = screening.check_rsi(df)
    assert df["rsi"].iloc[-1] > 50
    assert g.passed is False


def test_short_history_ma_gate_unknown():
    rep = screening.evaluate("0000", "測試", make_prices(list(np.linspace(10, 12, 30))), None)
    assert rep.gates[0].passed is None


def test_institutional_dealer_only_fails():
    idx = pd.bdate_range("2026-05-01", periods=5)
    df = pd.DataFrame({"foreign": -10.0, "trust": -10.0, "dealer": 100.0}, index=idx)
    df["total"] = df.sum(axis=1)
    assert screening.check_institutional(df).passed is False


def test_merge_realtime_updates_or_appends():
    p = make_prices(uptrend())
    last = p.index[-1]
    q = {"price": 170.0, "open": 166.0, "high": 171.0, "low": 165.0, "volume": 5000.0,
         "time": datetime.combine(last.date(), datetime.min.time())}
    same = ds.merge_realtime(p, q)
    assert len(same) == len(p) and same["close"].iloc[-1] == 170.0
    q["time"] = datetime.combine((last + pd.Timedelta(days=3)).date(), datetime.min.time())
    newer = ds.merge_realtime(p, q)
    assert len(newer) == len(p) + 1 and newer["close"].iloc[-1] == 170.0
    assert ds.merge_realtime(p, None) is p


def test_app_renders_with_stub_data(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(ds, "stock_info", lambda code: {"name": "測試股", "market": "twse"})
    monkeypatch.setattr(ds, "daily_prices", lambda code, market="": make_prices(uptrend()))
    monkeypatch.setattr(ds, "institutional", lambda code: inst_frame([50] * 30))
    monkeypatch.setattr(ds, "realtime_quote", lambda code, market="": None)
    import os
    at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "..", "app.py"), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    assert len(at.dataframe) == 1
    assert any("強勢多頭" in m.value for m in at.markdown)
