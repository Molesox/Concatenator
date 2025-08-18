# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Set


@dataclass
class Options:
    recursive: bool
    include_exts: Set[str]
    exclude_dirs: Set[str]
    ignore_binaries: bool
    max_mb: float
    add_headers: bool
    normalize_eol: bool
    cs_remove_comments: bool = False
    cs_remove_usings: bool = False