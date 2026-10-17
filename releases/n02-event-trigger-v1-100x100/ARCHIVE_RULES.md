# Archive rules

The public boundary is exactly the files listed in `PUBLIC_ARCHIVE_INVENTORY.json`.
The source, sanitized evidence summaries, labels and model checkpoints are copied
from the reviewed release. Absolute local/server paths are redacted in copied JSON.

Excluded by policy: passwords, private keys, tokens, authorization payloads,
private server/runtime context, SQLite databases, raw operational console logs,
and unrelated legacy data. The previous minimal-closure release is preserved and
is not overwritten.
