# Archive rules

The public boundary is the file set recorded in `PUBLIC_ARCHIVE_INVENTORY.json`;
that inventory file is excluded from its own hash list. The frozen source is
copied from the manifest-identified release, and audit summaries omit local and
server paths. The documented `C:\Windows\System32\OpenSSH\ssh.exe` path is the
public Windows system location required for reproducing native OpenSSH use.

Excluded: passwords, private keys, tokens, authorization payloads, private
endpoints, SQLite databases, raw operational logs, and model checkpoint files.
The prior event-trigger release is retained in its original directory.
