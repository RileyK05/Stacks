"""Write the API's OpenAPI spec to a file, for frontend type generation
without a running server:

    .venv/Scripts/python -m scripts.dump_openapi runs/openapi.json
    cd src/frontend && OPENAPI_FILE=../../runs/openapi.json npm run gen:api
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.backend.main import create_api


def main(argv: list[str]) -> int:
    target = Path(argv[0] if argv else "runs/openapi.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(create_api().openapi(), indent=2), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
