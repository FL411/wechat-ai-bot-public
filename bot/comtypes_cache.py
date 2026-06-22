"""配置 comtypes 生成缓存目录。

uiautomation 依赖 comtypes 按需生成 UIAutomationCore 包装代码。系统级 Python
安装在 Program Files 时，默认缓存目录不可写，所以这里把生成目录切到项目内。
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMTYPES_CACHE_DIR = os.path.join(PROJECT_ROOT, "data", "runtime", "comtypes_cache")


def configure_comtypes_cache() -> str:
    """将 comtypes 的生成缓存目录设置到项目内可写位置。"""
    os.makedirs(COMTYPES_CACHE_DIR, exist_ok=True)

    import comtypes.client
    import comtypes.gen

    comtypes.client.gen_dir = COMTYPES_CACHE_DIR

    existing_paths = [path for path in list(comtypes.gen.__path__) if path != COMTYPES_CACHE_DIR]
    comtypes.gen.__path__ = [COMTYPES_CACHE_DIR, *existing_paths]

    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    return COMTYPES_CACHE_DIR
