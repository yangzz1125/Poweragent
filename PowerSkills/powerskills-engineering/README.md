# powerskills-engineering

Senior power-engineer mitigation playbooks. Each one starts from an observed problem and lists corrective actions in the order an experienced operator or planner would actually try them — moving past "here is the violation" into corrective action, tradeoffs, and validation. These are software-agnostic and are typically reached from the **Escalation triggers** tables in the [`powerskills-tool`](../powerskills-tool/) skills.

## Skills

| Skill | Use when |
| --- | --- |
| `voltage-violation-mitigation` | Low/high voltage, weak reactive support, tap exhaustion |
| `thermal-overload-mitigation` | Line or transformer loading above ratings |
| `contingency-mitigation` | N-1 / N-2 violations or weak corrective-action plans |
| `dynamic-stability-mitigation` | Poor damping, transient instability, slow voltage recovery |
| `operations-planning-mitigation` | OPF/UC infeasibility, high curtailment, congestion, reserve shortage |
| `convergence-failure-mitigation` | Power flow diverges or fails to solve |
| `short-circuit-mitigation` | Fault duty above breaker ratings |
| `frequency-response-mitigation` | Low inertia, poor nadir/RoCoF, weak primary frequency response |
| `interconnection-impact-mitigation` | Screening a new generator, storage, or large-load interconnection |
| `der-hosting-capacity-mitigation` | DER-driven voltage rise, reverse flow, protection desensitization |

See the [repository README](../README.md) for install instructions (Claude Code, Codex, Claude Desktop).
