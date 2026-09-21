from __future__ import annotations

import argparse
import json
from pathlib import Path

from poweragentbench.benchmark_utils import (
    ACTIONCOST_FILE,
    ACTIONSPACE_FILE,
    NETWORK_FILE,
    evaluate_solution,
    load_solution,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate an action plan for the level_1 steady-state case39 benchmark."
    )
    parser.add_argument(
        "--solution",
        required=True,
        type=Path,
        help="Path to a JSON solution file with an 'actions' list.",
    )
    parser.add_argument(
        "--network",
        default=NETWORK_FILE,
        type=Path,
        help="Path to the prepared PyPSA netCDF scenario file.",
    )
    parser.add_argument(
        "--actionspace",
        default=ACTIONSPACE_FILE,
        type=Path,
        help="Path to actionspace.json.",
    )
    parser.add_argument(
        "--actioncost",
        default=ACTIONCOST_FILE,
        type=Path,
        help="Path to actioncost.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    solution = load_solution(args.solution)
    result = evaluate_solution(
        solution,
        network_path=args.network,
        actionspace_path=args.actionspace,
        actioncost_path=args.actioncost,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
