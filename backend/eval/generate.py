"""Generate fictional development cases: python -m eval.generate [--validate-only]."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from eval.synthetic.storage import validate_dataset, write_dataset

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "fixtures" / "cases" / "synthetic"


def main() -> int:
    """Build or validate the dataset, reporting counts without making API calls."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=20261114)
    parser.add_argument("--without-paraphrases", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    try:
        manifest = (
            validate_dataset(args.output)
            if args.validate_only
            else write_dataset(args.output, args.seed, paraphrases=not args.without_paraphrases)
        )
    except (ValueError, OSError, KeyError) as exc:
        sys.stderr.write(f"Synthetic dataset failed validation: {exc}\n")
        return 2
    sys.stdout.write(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "cases": len(manifest.cases),
                "scope": manifest.dataset_scope,
                "seed": manifest.seed,
                "variants": dict(Counter(entry.variant for entry in manifest.cases)),
                "truth": dict(Counter(entry.truth for entry in manifest.cases)),
                "follow_ups": sum(entry.follow_up_trigger is not None for entry in manifest.cases),
                "generation_api_cost_usd": manifest.generation_api_cost_usd,
                "label_review": "pending_agent_owner_review",
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
