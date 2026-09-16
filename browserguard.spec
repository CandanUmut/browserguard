# PyInstaller build spec, shared by Windows and macOS.
#
# Windows produces two single-file executables:
#   BrowserGuard.exe      - the window, elevation requested via the manifest
#   browserguard-cli.exe  - the same features from a console
#
# macOS produces:
#   BrowserGuard.app      - the window
#   browserguard-cli      - the console tool
#
# Build with:  pyinstaller browserguard.spec --noconfirm

import sys

IS_MACOS = sys.platform == "darwin"

block_cipher = None

DATAS = [("src/browserguard/data", "browserguard/data")]

# Qt modules the app never touches. Dropping them cuts roughly 30 MB.
EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtPdf",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtNetwork",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "pytest",
]

gui_analysis = Analysis(
    ["src/browserguard/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=DATAS,
    hiddenimports=["browserguard.gui.app", "browserguard.gui.wizard"],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    cipher=block_cipher,
    noarchive=False,
)

gui_pyz = PYZ(gui_analysis.pure, gui_analysis.zipped_data, cipher=block_cipher)

gui_exe = EXE(
    gui_pyz,
    gui_analysis.scripts,
    gui_analysis.binaries,
    gui_analysis.zipfiles,
    gui_analysis.datas,
    [],
    name="BrowserGuard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows: writing to HKLM needs administrator rights, so ask for them up
    # front rather than failing halfway through applying policy. Ignored on macOS,
    # where the app asks for authorisation at the point it is needed instead.
    uac_admin=not IS_MACOS,
)

cli_analysis = Analysis(
    ["src/browserguard/cli.py"],
    pathex=["src"],
    binaries=[],
    datas=DATAS,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES + ["PySide6", "shiboken6"],
    cipher=block_cipher,
    noarchive=False,
)

cli_pyz = PYZ(cli_analysis.pure, cli_analysis.zipped_data, cipher=block_cipher)

cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    cli_analysis.binaries,
    cli_analysis.zipfiles,
    cli_analysis.datas,
    [],
    name="browserguard-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Deliberately not elevated: read-only commands such as `status`, `detect`
    # and `verify` should run without a prompt. Commands that write policy check
    # their own permissions and say so if they are missing.
    uac_admin=False,
)

if IS_MACOS:
    app = BUNDLE(
        gui_exe,
        name="BrowserGuard.app",
        icon=None,
        bundle_identifier="org.browserguard.app",
        info_plist={
            "CFBundleName": "BrowserGuard",
            "CFBundleDisplayName": "BrowserGuard",
            "CFBundleShortVersionString": "1.1.0",
            "CFBundleVersion": "1.1.0",
            "NSHighResolutionCapable": True,
            # No reason for this to appear in the Dock switcher as a document app.
            "LSApplicationCategoryType": "public.app-category.utilities",
            "LSMinimumSystemVersion": "11.0",
        },
    )
