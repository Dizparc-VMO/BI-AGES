# PyInstaller build definition for the V8 Windows desktop app.
import os

project_root = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(project_root, "omplanering_app_v8.py")],
    pathex=[project_root, os.path.join(project_root, "service")],
    binaries=[],
    datas=[
        (os.path.join(project_root, "documentation_v8.html"), "."),
        (os.path.join(project_root, "instuktion.md"), "."),
        (os.path.join(project_root, "README_v8.md"), "."),
    ],
    hiddenimports=["pyodbc"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI-Omplanering-V8",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AI-Omplanering-V8",
)
