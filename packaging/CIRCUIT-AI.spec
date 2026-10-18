# PyInstaller spec:  PyInstaller packaging/CIRCUIT-AI.spec
from pathlib import Path
ROOT = Path(SPECPATH).parent
datas = [
    (str(ROOT / "database" / "schema.sql"), "database"),
    (str(ROOT / "data"), "data"),
    (str(ROOT / "config"), "config"),
]
a = Analysis([str(ROOT / "desktop_app" / "__main__.py")], pathex=[str(ROOT)],
             datas=datas, hiddenimports=[], excludes=["streamlit", "pandas"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="CIRCUIT-AI",
          console=False, upx=False)
