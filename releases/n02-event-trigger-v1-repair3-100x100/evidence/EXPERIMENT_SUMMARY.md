# Repair3 evidence summary

GPT-6.1 Sol High reviewed source release
`n02-event-trigger-v1-18f0ed76de7f433380d231b1dd28bb61` and formal attempt
`n02-event-v1-d0e59d2f21264863990169fe0874e764`. The review returned PASS with
143/143 evidence hashes matching and no review issues. Engineering status is
`ENGINEERING_PASS`; scientific claims remain `UNVERIFIED`.

The run followed the 100x100 grid and 2x2 perturbation contract. M1 recorded
720 rows. Event mode triggered 42 times, all with global scope, and selected 25
effective non-NOOP global actions. Periodic mode triggered 90 times, including
13 local and 77 global triggers; 13 local and 17 global actions had effective
changes. The observed local reconstruction result belongs to periodic
diagnostics only.

M2 included explicit NOOP candidates in each planned window. An independent
oracle recomputed 24 windows over 253 branches without reading producer labels;
all comparisons matched within tolerance. The 16 training and 24 total planned
windows each met the distinct-outcome criterion. M3 trained three world-model
members for 80 optimizer updates each and restored them in a fresh process.
M4 trained four policy variants on three seeds for 1,344 total PPO updates and
restored 12 checkpoints in fresh processes. G-WM auxiliary gradients were
nonzero and the world-model weights remained frozen.

The run recorded 21,602 environment steps and 1,584 combined world-model and
policy optimizer updates, with no first error or run reuse. Development results
cover two held-out parents and are descriptive. Event-G-WM combines changes to
the trigger policy and critic input, so this comparison does not isolate the
critic's causal effect.
