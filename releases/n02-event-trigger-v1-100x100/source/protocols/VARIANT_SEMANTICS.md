# Four-method semantics, fixed before formal execution

`Periodic-G` and `Event-G` do not query the world model. Their feasibility-loss
trigger component comes from public execution estimates; uncertainty is explicitly
zero because these variants have no ensemble. `Periodic-G-WM` and `Event-G-WM`
may use the frozen ensemble for degradation/uncertainty in the rule trigger, as
specified in the user's world-model and event-trigger sections. The periodic
decision times remain every4 minutes regardless of ensemble output.

Within the learned neural policy, world-model predictions enter the auxiliary
critic only. They do not enter either actor encoder or actor head and cannot
directly change logits on a fixed observation/catalog. Trigger rules and affected
scope impose separately logged public action masks. A change in a mask is not
misreported as direct actor-logit modification.

The final threshold is calibrated using only the same four training reference
histories and the preregistered weights and q=.75. Preserve the pre-model U=0
diagnostic threshold and the final ensemble-calibrated threshold. Development
results never select either threshold or a variant definition.

`Event-G-WM` versus `Event-G` therefore estimates the combined contribution of
the model-assisted trigger and auxiliary critic in this first-round framework.
It does not isolate the auxiliary critic's causal effect. Fixed-observation
actor invariance and critic gradient tests establish wiring, not an isolated
algorithmic benefit. Report absence of observed gains without changing methods.

Every comparison distinguishes trigger invocations, requested non-NOOP decisions,
effective allocation mutations, operational queue dispatches and explicit command
messages. Scope names and fees alone never establish a different physical outcome.
Local actions must stay in the actual identified task/platform impact domain;
global actions may include a wider set. Identical physical changes are not copied
into both scope labels merely to pad the catalog.
