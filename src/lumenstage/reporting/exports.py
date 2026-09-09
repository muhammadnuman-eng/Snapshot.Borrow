"""Export helpers."""

from __future__ import annotations

import csv
import io
import json

from lumenstage.storage.store import JsonDocumentStore


def export_collection_csv(store: JsonDocumentStore, collection: str) -> str:
    rows = store.read_collection(collection)
    if not rows:
        return ""
    fieldnames = sorted({key for row in rows for key in row})
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                k: json.dumps(v) if isinstance(v, list | dict) else ("" if v is None else str(v))
                for k in fieldnames
                for v in [row.get(k)]
            }
        )
    return buf.getvalue()
