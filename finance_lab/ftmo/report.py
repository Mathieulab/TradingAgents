"""Persist the exact dataset, assumptions and results used in a test."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def save_run(result, root=Path("reports/ftmo")):
    name = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
    folder = Path(root) / name
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "result.json").write_text(
        json.dumps(result, indent=2, allow_nan=False), encoding="utf-8"
    )
    for period in ("development", "holdout", "stress"):
        trades = result[period]["trades"]
        with (folder / f"{period}_trades.csv").open("w", newline="", encoding="utf-8") as stream:
            fields = list(trades[0]) if trades else ["entry_time", "exit_time", "side", "pnl"]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(trades)
    return folder.resolve()
