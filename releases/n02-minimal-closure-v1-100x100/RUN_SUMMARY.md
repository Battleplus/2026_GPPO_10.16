# Repair-2 Run Summary

Repair-2 completed all seven stages with exit status 0. The final independent review passed 66 scoped checks with no must-fix findings (source review SHA-256 `a9c03df92dcdef3a99d51f11ee8649957adfcdea218d8a45c548199224f55c87`). The selected export contained 8 training windows, 32 training branches, 4 development windows, and 12 development branches. The independent oracle replay covered 32 training branches and 944 environment steps; those steps are not a qualifying-step count.

The world model made 2 updates and passed strict fresh-process restore. G and G-WM each made 8 policy updates from matched initialization and minibatch indices. G-WM made 8 adapter updates with finite positive gradients (1.93431-2.53078); the world model remained frozen. The development comparison used one episode per variant on one development scenario. All reported paired differences were zero, so the result is diagnostic and supports no superiority claim.

Repair-1's formal attempt failed during final settlement/export after the SQLite ledger had been closed before the final snapshot read. Its separate systemd cost was 76.486798 wall seconds and 65.432701 CPU seconds; guardian scope was 75.971253 wall and 64.953627 CPU seconds. This failure remains part of the history.

Repair-2 guardian scope was 60.530864 wall seconds and 49.768777 CPU seconds. Its systemd scope was 60.920859 wall seconds and 50.098576 CPU seconds. The authoritative final live ledger, including the prior B diagnostic exactly once, was 62.922489 wall seconds and 50.131256 CPU seconds. These measurement boundaries differ and are not interchangeable.

Across six distinct systemd units, the non-overlapping recorded sum was 140.634744 wall seconds and 116.712983 CPU seconds. This includes the prior B unit once, the failed first formal attempt, and repair-2's systemd invocation. The repair-2 live ledger is an alternate overlapping boundary and is not added again.

The exported scenarios and trajectories are synthetic simulator output. Raw logs, SQLite, authorization files, private runtime evidence, and measured cost receipts are excluded. Full paper experiments were outside this engineering closure.
