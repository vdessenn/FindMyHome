# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""FindMyHome — aggregates property listings from small estate agencies."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("findmyhome")
except PackageNotFoundError:  # pragma: no cover - depends on packaging
    # Under PyInstaller, distribution metadata is only present if the spec calls copy_metadata().
    __version__ = "unknown (metadata missing)"

__all__ = ["__version__"]
