"""執行檔進入點：啟動 Streamlit 看板並自動開啟瀏覽器。"""
from __future__ import annotations

import os
import sys

# 讓 PyInstaller 分析時一併打包看板用到的套件
import numpy  # noqa: F401
import pandas  # noqa: F401
import plotly.graph_objects  # noqa: F401
import plotly.subplots  # noqa: F401
import requests  # noqa: F401
import streamlit.web.cli as stcli


def base_dir() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def skip_email_prompt() -> None:
    """Streamlit 首次執行會詢問 Email 並卡住，預先寫入空白憑證檔略過。"""
    cred = os.path.join(os.path.expanduser("~"), ".streamlit", "credentials.toml")
    if not os.path.exists(cred):
        os.makedirs(os.path.dirname(cred), exist_ok=True)
        with open(cred, "w", encoding="utf-8") as f:
            f.write('[general]\nemail = ""\n')


def main() -> None:
    skip_email_prompt()
    app = os.path.join(base_dir(), "app.py")
    sys.argv = [
        "streamlit", "run", app,
        "--global.developmentMode=false",
        "--server.headless=false",
        "--browser.gatherUsageStats=false",
        "--server.fileWatcherType=none",
        "--client.toolbarMode=minimal",
    ]
    print("短線篩選看板啟動中，瀏覽器將自動開啟（關閉此視窗即結束程式）……")
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
