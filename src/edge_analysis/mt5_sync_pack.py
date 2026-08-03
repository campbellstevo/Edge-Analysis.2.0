"""Build the downloadable MT5 auto-sync package, personalised per user."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "mt5_sync"


def build_zip(database_id: str = "") -> bytes:
    """Zip the sync folder; when we know the user's journal, config.ini ships
    pre-filled so their only edit is pasting the token."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("ea_mt5_sync.py", "run_sync.bat", "README.md",
                     "config.example.ini"):
            z.writestr(f"edge-analysis-mt5-sync/{name}",
                       (_SRC / name).read_text(encoding="utf-8"))
        if database_id:
            cfg = (_SRC / "config.example.ini").read_text(encoding="utf-8")
            cfg = cfg.replace("PASTE-YOUR-DATABASE-ID-HERE",
                              str(database_id).replace("-", ""))
            z.writestr("edge-analysis-mt5-sync/config.ini", cfg)
    return buf.getvalue()
