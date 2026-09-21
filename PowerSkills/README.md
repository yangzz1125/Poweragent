# PowerSkills

PowerSkills is the skill layer on top of [PowerMCP](https://github.com/Power-Agent/PowerMCP). PowerMCP exposes raw software tools. PowerSkills tells an agent which tool to reach for first, what to verify before escalating to advanced studies, and what mitigation playbooks to follow when a study finds a real operating problem.

The skills are packaged as two [Agent Skills](https://agentskills.io/) plugins inside a Claude Code marketplace, so you can install them in one step (see [Install](#install)).

| Plugin | What it is | Skills |
| --- | --- | --- |
| [`powerskills-tool`](powerskills-tool/) | Progressive-disclosure workflows for power-system software | 11 |
| [`powerskills-engineering`](powerskills-engineering/) | Senior-engineer mitigation playbooks | 10 |

## How this repo differs from PowerMCP

1. **Progressive disclosure of software tools**
   - Start with the lowest-risk actions first: open or load the case, inspect the model, solve the base case, and only then move to advanced studies.
   - Avoid jumping directly into contingency analysis, dynamics, matrix extraction, or investment optimization before the base case is credible.
2. **Senior engineer mitigation skills**
   - Add issue-driven playbooks for voltage violations, thermal overloads, contingency findings, dynamic stability problems, planning infeasibilities, convergence failures, fault-duty problems, frequency response, interconnection impacts, and DER hosting capacity.
   - Move beyond violation reporting into corrective action, tradeoff discussion, and validation steps.

Every `powerskills-tool` skill ends with an **Escalation triggers** table that maps a concrete observation (e.g. a bus below 0.95 pu, a branch above 100% loading, a binding N-1) to the matching `powerskills-engineering` playbook — so the handoff is driven by numbers, not vibes.

## Available software skills (`powerskills-tool`)

These skills mirror the current software list in PowerMCP, except `potpourri`, which has no PowerMCP server yet and is driven through its Python API by the scripts bundled in the skill.

| Skill | Scope | First tools to expose | Advanced tools to expose later |
| --- | --- | --- | --- |
| [ANDES](powerskills-tool/skills/andes/) | Dynamic security and small-signal studies | `run_power_flow`, `get_system_info` | `run_eigenvalue_analysis`, `run_time_domain_simulation` |
| [Egret](powerskills-tool/skills/egret/) | Market and operations optimization | `solve_dc_opf` | `solve_ac_opf`, `solve_unit_commitment_problem` |
| [LTSpice](powerskills-tool/skills/ltspice/) | Circuit simulation workflow | `create_simulation_session`, `run_simulation` | `list_available_traces`, `plot_specific_traces`, GUI viewing |
| [OpenDSS](powerskills-tool/skills/opendss/) | Distribution feeder studies | `compile_and_solve`, `get_total_power`, `get_bus_voltages` | `set_load_multiplier`, `run_daily_energy_meter`, `get_harmonic_results` |
| [PSLF](powerskills-tool/skills/pslf/) | Transmission power flow and contingencies | `open_case`, `solve_case`, violation checks | topology or device edits, `run_contingency_analysis` |
| [PSSE](powerskills-tool/skills/psse/) | PSS/E base-case and API-guided studies | `open_case`, `solve_case` | `lookup_psspy_command`, `search_psspy_commands`, `run_psspy_command` |
| [PowerWorld](powerskills-tool/skills/powerworld/) | Steady-state analysis and sensitivities | `open_case`, `run_powerflow`, result queries | contingencies, parameter changes, PTDF or LODF or Jacobian tools |
| [PyPSA](powerskills-tool/skills/pypsa/) | Planning, OPF, and expansion studies | `load_network` or `create_network`, network inspection | `optimize_network`, `optimize_investment`, import or export flows |
| [pandapower](powerskills-tool/skills/pandapower/) | AC analysis and screening studies | `load_network` or `create_empty_network`, `get_network_info`, `run_power_flow` | `run_contingency_analysis` |
| [potpourri](powerskills-tool/skills/potpourri/) | AC/DC and multi-period optimal power flow for pandapower distribution networks, including flexible resources and storage | `scripts/inspect_case.py`, `scripts/solve_opf.py --list-solvers` | `solve_opf.py --formulation dc` then `--formulation ac`, `--horizon N --battery-penetration` |
| [surge](powerskills-tool/skills/surge/) | Transmission analysis, sensitivities, OPF, contingency, ATC, dispatch | `load_builtin_case` or `load_network`, `get_network_info`, `run_ac_power_flow` | `compute_ptdf` / `compute_lodf`, `run_dc_opf` / `run_scopf`, `run_n1_branch_contingency`, `compute_nerc_atc`, `run_scuc` |

## Available mitigation skills (`powerskills-engineering`)

| Skill | Use when | Typical actions |
| --- | --- | --- |
| [voltage-violation-mitigation](powerskills-engineering/skills/voltage-violation-mitigation/) | Low or high voltage, weak reactive support, tap exhaustion | AVR or Volt-VAR checks, shunts, taps, redispatch, transfer reduction |
| [thermal-overload-mitigation](powerskills-engineering/skills/thermal-overload-mitigation/) | Line or transformer overloads | redispatch, topology switching, phase-shifter control, reinforcement screening |
| [contingency-mitigation](powerskills-engineering/skills/contingency-mitigation/) | N-1 or N-2 violations or weak corrective-action plans | pre-contingency fixes, corrective switching, RAS screening, long-term upgrades |
| [dynamic-stability-mitigation](powerskills-engineering/skills/dynamic-stability-mitigation/) | Poor damping, transient instability, slow voltage recovery | model checks, dispatch relief, AVR or PSS or governor tuning, dynamic VAR support |
| [operations-planning-mitigation](powerskills-engineering/skills/operations-planning-mitigation/) | OPF or UC infeasibility, high curtailment, congestion, reserve shortage | data cleanup, simpler screening solves, flexibility additions, constraint review |
| [convergence-failure-mitigation](powerskills-engineering/skills/convergence-failure-mitigation/) | Power flow diverges or fails to solve in any tool | data checks, island/slack review, staged control relaxation, stress reduction |
| [short-circuit-mitigation](powerskills-engineering/skills/short-circuit-mitigation/) | Fault duty above breaker ratings, rising fault levels | study verification, bus splitting, series reactors, breaker upgrades |
| [frequency-response-mitigation](powerskills-engineering/skills/frequency-response-mitigation/) | Low inertia, poor nadir or RoCoF, weak primary response, UFLS risk | governor headroom, fast frequency response, inertia additions, droop/deadband fixes |
| [interconnection-impact-mitigation](powerskills-engineering/skills/interconnection-impact-mitigation/) | New generator, storage, or large-load interconnection screening | N-1 screens at the POI, SCR/weak-grid checks, reactive requirements, upgrade sizing |
| [der-hosting-capacity-mitigation](powerskills-engineering/skills/der-hosting-capacity-mitigation/) | DER-driven voltage rise, reverse flow, protection desensitization | inverter Volt-VAR/export limits, regulator settings, protection re-checks, reinforcement |

## Install

A skill is just a folder with a `SKILL.md`, so the same content works across agents. Pick the path for your tool.

### Claude Code (recommended)

Add this repository as a plugin marketplace, then install one or both plugins:

```text
/plugin marketplace add Power-Agent/PowerSkills
/plugin install powerskills-tool@powerskills
/plugin install powerskills-engineering@powerskills
```

To work from a local clone instead of GitHub, run `/plugin marketplace add ./` from the repository root. Manage everything later with `/plugin`.

### Codex CLI

Codex discovers skills from `.agents/skills/` (scanned from your working directory up to the repo root) and from `~/.codex/skills/` (global). Copy or symlink the skill folders you want — no conversion needed:

```bash
# project-scoped, e.g. the tool skills for the repo you're working in
mkdir -p .agents/skills
cp -R /path/to/PowerSkills/powerskills-tool/skills/* .agents/skills/

# or install globally for every project
mkdir -p ~/.codex/skills
cp -R /path/to/PowerSkills/powerskills-tool/skills/* ~/.codex/skills/
cp -R /path/to/PowerSkills/powerskills-engineering/skills/* ~/.codex/skills/
```

### Claude Desktop / claude.ai

1. Enable **Settings → Capabilities → Code execution** (skills run in the code-execution sandbox).
2. Open **Settings → Capabilities → Skills → Upload skill**.
3. Upload a ZIP of a single skill folder, with the skill folder at the root of the ZIP. Skills are uploaded one at a time. For example:

```bash
cd powerskills-tool/skills
zip -r pandapower.zip pandapower
```

Then toggle the skill on. Repeat for each skill you want.

## Repository layout

```text
PowerSkills/
├── .claude-plugin/
│   └── marketplace.json            # makes the repo an installable marketplace
├── powerskills-tool/               # plugin: software workflow skills
│   ├── .claude-plugin/plugin.json
│   ├── README.md
│   └── skills/
│       ├── andes/ … surge/         # 11 tool skills (pandapower, pypsa, potpourri, surge bundle scripts + cases)
├── powerskills-engineering/        # plugin: mitigation playbooks
│   ├── .claude-plugin/plugin.json
│   ├── README.md
│   └── skills/
│       └── voltage-violation-mitigation/ … der-hosting-capacity-mitigation/  # 10 mitigation skills
└── skill-creator/                  # authoring/validation tooling (not part of either plugin)
```

## Contribution rules

Contributors should use Skill Creator when adding or updating skills.

- Keep `SKILL.md` concise and procedural.
- For software skills, expose tools in this order: load or open → inspect → solve → modify → advanced studies, and end with an **Escalation triggers** table.
- For mitigation skills, start from an observed problem and list corrective actions in the order a senior engineer would actually try them.
- Reference bundled assets with skill-relative paths (`scripts/...`, `references/...`) so each skill stays portable when installed standalone.
- Prefer contributions in two buckets:
  - better progressive disclosure for an existing PowerMCP software surface (`powerskills-tool`)
  - better mitigation playbooks that use one or more of those software tools (`powerskills-engineering`)
- Validate before opening a PR:

  ```bash
  python skill-creator/scripts/quick_validate.py powerskills-tool/skills/<skill>
  python skill-creator/scripts/quick_validate.py powerskills-engineering/skills/<skill>
  ```

## Related projects

- [PowerMCP](https://github.com/Power-Agent/PowerMCP) - MCP servers for power-system software
- [Agent Skills](https://agentskills.io/) - open skill format and ecosystem

### Core Team
- [Qian Zhang](https://www.linkedin.com/in/qian-zhang-75323111b/), [Matheus Duarte](https://www.linkedin.com/in/matheusduarte/), [Muhy Eddin Za’ter](https://scholar.google.com/citations?user=_IFFYFAAAAAJ&hl=en), [Drew Gray](https://www.linkedin.com/in/drew-gray-b09ba426/)

## License

MIT License
