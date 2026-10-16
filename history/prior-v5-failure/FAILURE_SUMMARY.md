# Prior v5 Formal-Run Failure (De-identified)

## Event

A prior v5 formal-run submission reached its execution gate without a measured prior resource-cost receipt. The process guardian ran, rejected the request at the prior-cost gate, and did so before launching the research worker.

## Confirmed outcome

- No research worker or formal training run began.
- No world-model training update occurred.
- No PPO update occurred.
- This is a pre-run gate failure, not a completed experiment or an experimental result.

## Identity handling

The request, attempt, authorization, and run identity associated with this failed v5 submission are historical. They must not be reused for a repaired package or a later run. Any future attempt requires new identities and a fresh, reviewed authorization chain.

This summary intentionally omits host names, IP addresses, user names, local/server paths, credentials, raw logs, and authorization contents. It contains no source code or training data.
