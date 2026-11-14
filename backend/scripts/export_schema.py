"""Export the contracts as one JSON Schema: `python -m scripts.export_schema <out_path>`."""

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from app.contracts import Case, Decision, StreamEvent


class Contracts(BaseModel):
    """Root that references every type the frontend needs."""

    case: Case
    decision: Decision
    event: StreamEvent


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(Contracts.model_json_schema(), indent=2))
