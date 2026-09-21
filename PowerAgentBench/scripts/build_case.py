from __future__ import annotations

from poweragentbench.benchmark_utils import (
    ACTIONCOST_FILE,
    ACTIONSPACE_FILE,
    BASELINE_SUMMARY_FILE,
    NETWORK_FILE,
    export_scenario_network,
    generate_baseline_summary,
)


def main() -> None:
    export_scenario_network(NETWORK_FILE)
    generate_baseline_summary(NETWORK_FILE, ACTIONSPACE_FILE, ACTIONCOST_FILE, BASELINE_SUMMARY_FILE)
    print(f"Wrote {NETWORK_FILE.name} and {BASELINE_SUMMARY_FILE.name}")


if __name__ == "__main__":
    main()
