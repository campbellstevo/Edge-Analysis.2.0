"""Build the downloadable MT5 auto-sync package, personalised per user."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "mt5_sync"


def build_zip(database_id: str = "", notion_token: str = "") -> bytes:
    """Zip the sync folder, personalised. With the signed-in user's own Notion
    token and journal id baked into config.ini there is NOTHING left to set up:
    download, run. The token is the same one their session already uses — it
    lives only in this file on their machine, like a saved password."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("ea_mt5_sync.py", "run_sync.bat", "README.md",
                     "config.example.ini"):
            z.writestr(f"edge-analysis-mt5-sync/{name}",
                       (_SRC / name).read_text(encoding="utf-8"))
        if database_id or notion_token:
            cfg = (_SRC / "config.example.ini").read_text(encoding="utf-8")
            if database_id:
                cfg = cfg.replace("PASTE-YOUR-DATABASE-ID-HERE",
                                  str(database_id).replace("-", ""))
            if notion_token:
                cfg = cfg.replace("PASTE-YOUR-TOKEN-HERE", str(notion_token))
                cfg = ("; Personal file — your journal key is inside. Don't share it.\n"
                       + cfg)
            z.writestr("edge-analysis-mt5-sync/config.ini", cfg)
    return buf.getvalue()
