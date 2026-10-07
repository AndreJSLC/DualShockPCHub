# PyInstaller spec for DualShock PC Hub.
#
#   .venv\Scripts\python -m PyInstaller packaging\dshub.spec --noconfirm
#
# Produces dist\DualShockPCHub\DualShockPCHub.exe (one-folder build: starts
# faster than one-file and is not unpacked to %TEMP% on every launch).
# Only QtCore/QtGui/QtWidgets are shipped to keep the download and the
# memory footprint small. License texts for everything bundled are copied to
# dist\DualShockPCHub\licenses.

import importlib.metadata
import re
import shutil
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "dshub" / "__init__.py").read_text()).group(1)
_v = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:4])
VERSION_TUPLE = _v + (0,) * (4 - len(_v))

# Qt modules we never import; PyInstaller's PySide6 hook would otherwise
# collect some of them (and their plugins) transitively.
QT_EXCLUDES = [
    f"PySide6.{m}" for m in (
        "QtNetwork", "QtQml", "QtQuick", "QtQuickWidgets", "QtQuickControls2", "QtWebEngineCore",
        "QtWebEngineWidgets", "QtWebChannel", "QtWebSockets", "QtMultimedia", "QtMultimediaWidgets",
        "QtCharts", "QtDataVisualization", "QtGraphs", "Qt3DCore", "Qt3DRender", "QtPdf", "QtPdfWidgets",
        "QtSql", "QtTest", "QtXml", "QtSvg", "QtSvgWidgets", "QtOpenGL", "QtOpenGLWidgets", "QtBluetooth",
        "QtPositioning", "QtSerialPort", "QtSensors", "QtDesigner", "QtHelp", "QtUiTools", "QtConcurrent",
        "QtDBus", "QtPrintSupport", "QtSpatialAudio", "QtTextToSpeech", "QtRemoteObjects", "QtScxml",
        "QtStateMachine", "QtHttpServer", "QtLocation", "QtNfc",
    )
]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    # dshub.ui.flat and dshub.system load some modules by name (importlib), which
    # PyInstaller can't see; without this the flat drawings are silently missing.
    hiddenimports=["hid", *collect_submodules("dshub")],
    excludes=["tkinter", "unittest", "pydoc", "doctest", "pytest", *QT_EXCLUDES],
    noarchive=False,
)

# Drop Qt plugins/translations we don't use (only the Windows platform
# plugin, the modern Windows style and the ICO image reader are needed).
KEEP_PLUGIN_DIRS = ("platforms", "styles", "imageformats")
KEEP_IMAGEFORMATS = ("qico",)


def _wanted(dest: str) -> bool:
    d = dest.replace("\\", "/").lower()
    if "/translations/" in d:
        return False
    if "/plugins/" in d:
        sub = d.split("/plugins/", 1)[1]
        folder = sub.split("/", 1)[0]
        if folder not in KEEP_PLUGIN_DIRS:
            return False
        if folder == "imageformats" and not any(k in sub for k in KEEP_IMAGEFORMATS):
            return False
    for heavy in ("qt6webengine", "qt6quick", "qt6qml", "qt6pdf", "qt6network", "qt6opengl", "qt6svg",
                  "opengl32sw", "d3dcompiler"):
        if heavy in d:
            return False
    return True


a.binaries = [b for b in a.binaries if _wanted(b[0])]
a.datas = [d for d in a.datas if _wanted(d[0])]

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DualShockPCHub",
    console=False,
    icon=str(ROOT / "packaging" / "app.ico"),
    # Shown in the exe's Properties -> Details.
    version=VSVersionInfo(
        ffi=FixedFileInfo(filevers=VERSION_TUPLE, prodvers=VERSION_TUPLE),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("ProductName", "DualShock PC Hub"),
                StringStruct("FileDescription", "DualShock PC Hub"),
                StringStruct("ProductVersion", VERSION),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", "DualShockPCHub"),
                StringStruct("OriginalFilename", "DualShockPCHub.exe"),
                StringStruct("CompanyName", "AndreJSLC"),
                StringStruct("LegalCopyright", "Copyright (c) 2026 AndreJSLC. MIT License."),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    ),
    upx=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="DualShockPCHub",
    upx=False,
)

# License texts next to the exe: ours, the notices summary, Qt's LGPL/GPL,
# Python's (which also covers OpenSSL, bzip2 and libffi) and hidapi's.
licenses = Path(DISTPATH) / "DualShockPCHub" / "licenses"  # noqa: F821 - provided by PyInstaller
licenses.mkdir(exist_ok=True)
shutil.copyfile(ROOT / "LICENSE", licenses / "LICENSE.txt")
for f in (ROOT / "packaging" / "licenses").glob("*.txt"):
    shutil.copyfile(f, licenses / f.name)
shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python-LICENSE.txt")
for f in importlib.metadata.distribution("hidapi").files:
    if f.name.upper().startswith("LICENSE"):
        shutil.copyfile(f.locate(), licenses / f"hidapi-{f.name}")
