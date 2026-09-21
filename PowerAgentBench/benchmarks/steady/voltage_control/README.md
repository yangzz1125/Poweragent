# IEEE 33-Bus BESS Voltage-Control Benchmark

This benchmark evaluates whether an LLM agent can correct steady-state voltage violations on the
IEEE 33-bus distribution feeder using only BESS active power. It extends PowerAgentBench without
changing the existing N-1, N-2, or RestoreBench tracks.

## Contract

- The scenario is a frozen pandapower JSON snapshot derived from `case33bw()`.
- Voltage limits are 0.95--1.05 pu.
- Positive benchmark `p_mw` means BESS discharge/injection; negative means charging/withdrawal.
- SOC, energy coupling, converter transients, reactive power and time series are out of scope.
- The evaluator reloads the frozen network, validates bounds and step sizes, applies the submitted
  dispatch, and independently reruns a locked backward/forward-sweep power flow.
- Success requires convergence and no remaining voltage violation. Line loading is recorded as a
  diagnostic but is not part of the verdict because the standard `case33bw()` snapshot does not
  provide study-grade thermal ratings.

## Experimental factors

`config/experiments.json` defines the 2x2x2 design for domain-specific interface, agent-visible
verification and recovery. Independent evaluator verification is always enabled.

## Build and run

```bash
python scripts/build_voltage_cases.py
python scripts/run_voltage_baselines.py

python scripts/run_voltage_agent_eval.py \
  --provider openai --model <model-id> \
  --domain-interface --verification --recovery
```

Outputs are written under `results/voltage_control/` as per-case CSV, summary CSV, tool-log JSONL,
attempt JSONL, sanitized API diagnostics and error JSONL.
