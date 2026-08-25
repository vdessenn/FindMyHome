# -*- mode: python ; coding: utf-8 -*-
"""Standalone binary (`make binary`). PyInstaller does not cross-compile:
this spec produces an executable for the OS and architecture of the build machine.
"""

from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is injected by PyInstaller

# Without this metadata, importlib.metadata.version("findmyhome") raises PackageNotFoundError
# inside the frozen binary: the package is there, its distribution is not.
datas = copy_metadata("findmyhome")

a = Analysis(  # noqa: F821
    [str(ROOT / "findmyhome" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    # selectolax is a Cython extension: if PyInstaller misses a submodule once it is actually
    # imported, this is where to declare it.
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "doctest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="findmyhome",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX deliberately disabled: compression is the number one trigger of antivirus false
    # positives on an unsigned binary.
    upx=False,
    console=True,
)
