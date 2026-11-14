"""Export the contracts as one JSON Schema: `python -m scripts.export_schema <out_path>`."""

import json
import sys
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema

from app.contracts import Case, Decision, StreamEvent


class Contracts(BaseModel):
    """Root that references every type the frontend needs."""

    case: Case
    decision: Decision
    event: StreamEvent


class ServerOutputSchema(GenerateJsonSchema):
    """Serialization schema where defaulted fields are required: the API always sends them.

    Same effect as `json_schema_serialization_defaults_required=True` on every contract model,
    without touching `app/contracts`.
    """

    def field_is_required(self, field, total):  # type: ignore[override]
        if self.mode == "serialization" and field["type"] != "typed-dict-field":
            return field.get("serialization_exclude_if") is None
        return super().field_is_required(field, total)


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            Contracts.model_json_schema(mode="serialization", schema_generator=ServerOutputSchema),
            indent=2,
        )
    )
