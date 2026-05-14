#!/usr/bin/env python3
"""Export API contract JSON Schema from backend Pydantic models."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.schemas import json_schema_bundle


def main() -> None:
    output_path = ROOT / "docs" / "api-schema.json"
    output_path.write_text(
        json.dumps(json_schema_bundle(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
