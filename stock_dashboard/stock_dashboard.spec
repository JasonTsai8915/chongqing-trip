# PyInstaller 打包設定：pyinstaller stock_dashboard.spec
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = [(f, ".") for f in ("app.py", "screening.py", "indicators.py", "data_source.py")]
binaries, hiddenimports = [], []
for pkg in ("streamlit", "plotly"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
datas += copy_metadata("streamlit")

a = Analysis(
    ["launcher.py"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="StockDashboard",
    console=True,
    upx=False,
)
