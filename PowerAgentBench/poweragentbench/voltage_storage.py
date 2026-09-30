"""Local evaluator storage policy, not an OS sandbox for file-enabled agents."""
from pathlib import Path

from poweragentbench.voltage_case import REPO_ROOT


def evaluator_output_root(path: str | Path) -> Path:
    root = Path(path).resolve()
    checkout = REPO_ROOT.parent.resolve()
    private = checkout / '.local-data'
    if root == checkout or checkout in root.parents:
        if private not in root.parents:
            raise ValueError('output must be outside PowerAgentBench checkout or a child of its .local-data directory')
    return root
