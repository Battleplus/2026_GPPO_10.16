# Privacy Report

The copied runtime code and `runtime-spec.json` use `/opt/n02-runtime` and `public-target-placeholder` instead of the private server's runtime paths and hostname. Runtime roots can be configured with `N02_RUNTIME_ROOT`, `N02_RUNS_ROOT`, `N02_DIAGNOSTICS_ROOT`, `N02_AUTHORIZATIONS_ROOT`, and `N02_TARGET_HOST`; the target interpreter contract is a public placeholder that must be configured locally before formal use.

The archive contains no raw operational logs, SQLite databases, authorization documents, target-host identity, or private runtime paths. The four original release-2 identity sidecars are retained byte-for-byte under `provenance/original_release02/`; they record the original release identity and do not authenticate this sanitized tree.

All scenario-derived data are synthetic simulator output. The selected training/development windows, branches, paired rollouts, and checkpoints are inventoried and hashed. Model checkpoint metadata was scanned for the private target paths and host identity. The portable `PRIOR_RESOURCE_COST.json` is the existing no-measurement placeholder; it contains no measured costs or evidence paths and cannot authorize execution.

The first formal attempt's failure and resource costs are disclosed in `RUN_SUMMARY.md`. Private invocation identifiers, authorization details, unit names, operational evidence paths, and raw ledgers are excluded. The final review derivative retains the 66 check outcomes and source review digest while omitting private invocation and evidence identifiers.
