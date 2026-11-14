"""Id helper. Prefixes in use: `case`, `ev`, `msg`, `act`."""

import uuid


def new_id(prefix: str) -> str:
    """A short unique id like `ev_3f9a1c0b2d4e`."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
