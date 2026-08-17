"""Render-safe process entry (no shell PORT expansion)."""
from __future__ import annotations

import os
import sys


def main() -> None:
    port = int(os.environ.get("PORT", "10000"))
    print(f"[canopy] boot python={sys.version.split()[0]} port={port}", flush=True)
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        log_level="info",
        timeout_keep_alive=30,
    )


if __name__ == "__main__":
    main()
