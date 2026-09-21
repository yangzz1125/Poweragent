# powerskills-tool

Progressive-disclosure skills for power-system software, designed to sit on top of [PowerMCP](https://github.com/Power-Agent/PowerMCP). Each skill walks an agent through *load → inspect → solve → modify → advanced studies*, so it starts with the lowest-risk action and only escalates once the base case is credible. When a study surfaces a real problem, the skill's **Escalation triggers** table points at the matching [`powerskills-engineering`](../powerskills-engineering/) playbook.

## Skills

| Skill | Scope |
| --- | --- |
| `andes` | Dynamic security, small-signal, and time-domain studies |
| `egret` | Market and operations optimization (DC-OPF, AC-OPF, unit commitment) |
| `ltspice` | Circuit simulation workflow (netlist, run, traces) |
| `opendss` | Distribution-feeder studies |
| `pslf` | Transmission power flow and contingencies |
| `psse` | PSS/E base case and PSSPY-guided automation |
| `powerworld` | Steady-state analysis, contingencies, sensitivities |
| `pypsa` | Planning, OPF, and capacity-expansion studies |
| `pandapower` | AC analysis and fast screening |
| `potpourri` | AC/DC and multi-period OPF for pandapower distribution grids, with flexible resources and storage |
| `surge` | Transmission analysis, sensitivities, OPF, contingency, ATC, dispatch |

`pandapower`, `pypsa`, `potpourri`, and `surge` also bundle runnable `scripts/`, `references/`, and example cases.

`potpourri` has no PowerMCP server yet, so its ladder drives the installed `opf-potpourri` Python package through the bundled scripts rather than MCP tools.

See the [repository README](../README.md) for install instructions (Claude Code, Codex, Claude Desktop).
