"""Hatchling build hook: regenerate ``_sync/`` from ``_async/`` before
every wheel/sdist build."""

from __future__ import annotations

import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class UnasyncBuildHook(BuildHookInterface):
    PLUGIN_NAME = "unasync"

    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        scripts = root / "scripts"
        sys.path.insert(0, str(scripts))
        try:
            import gen_sync

            gen_sync.regenerate()
        finally:
            sys.path.remove(str(scripts))
