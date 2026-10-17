# Post-run analysis reproduction

These byte-preserving tools are post-run analysis utilities outside `source/`; they do not change the formal 76-file GPU source identity. Their hashes are in `ANALYSIS_TOOLS_INVENTORY.json`. They do not train or simulate.

Use your own complete private simulation evidence. Compute trace-derived consequences without producer labels, then compare in a separate process:

```text
python analysis/audit_event_consequences.py compute --input <private-evidence> --output <private-computed-output> [--config <private-config>] [--expected-windows N] [--expected-branches N]
python analysis/audit_event_consequences.py compare --computed <private-computed-output> --labels <private-consequence-labels> --output <private-comparison-output>
python analysis/audit_event_consequences.py raw-mutations --input <private-evidence> --output <private-mutation-output>
python analysis/audit_event_consequences.py self-test
python analysis/summarize_run.py --input <private-run-output> --output <private-summary> [--example-label <label>]
```

The compute phase does not open `CONSEQUENCE_LABELS`; comparison is separate. This recomputes trace-derived consequences, not an independent simulation replay or proof of unrecorded internal tape/state. Missing measurements remain `MISSING`. Keep evidence and outputs private. The referenced run passed evidence integrity verification; independent final review remains pending.
