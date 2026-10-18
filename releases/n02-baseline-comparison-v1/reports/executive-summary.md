# Final Executive Summary

## Decision

The formal evaluation completed with 54/54 evaluations and 3,240 environment
ticks. The observed results do not meet the predeclared research criterion:
`RESEARCH_CRITERIA_FAILED`. This is a measured negative result, not an
unexecuted experiment. Engineering integrity remains under Sol Gate3 review, so
the run is not declared an engineering PASS and the final archive is not yet
complete.

The evaluation covered six learning methods across three seeds, producing 18
policy runs, 2,304 optimizer updates, and 288 training episodes. Three world
models completed 240 CUDA updates. Fresh-process restoration receipts were
verified for all three world models and all 18 policies.

## Formal Results

| Method | Utility | Completion | Planning ticks | Effective reconstructions |
| --- | ---: | ---: | ---: | ---: |
| Greedy / Auction / CBBA-lite | 9.8452209 | 0.9583333 | 60 | 4.5 |
| PPO | 5.2765333 | 0.8194444 | 60 | 5.0 |
| GPPO | 6.7811935 | 0.9027778 | 60 | 5.8333 |
| Periodic-GPPO | 5.0028563 | 0.8055556 | 15 | 2.5 |
| Event-GPPO | 5.6404020 | 0.8750000 | 6.6667 | 4.0 |
| Event-GPPO-WM | 5.6404020 | 0.8750000 | 6.5 | 4.0 |
| Periodic-GPPO-WM | 5.6176764 | 0.8750000 | 15 | 4.0 |

The candidate-constrained rules baseline is stronger on utility and completion
than the learning methods in this evaluation. GPPO exceeds PPO descriptively;
the comparison is not parameter-matched and does not establish a causal method
advantage.

Against Periodic-GPPO, Event-GPPO has +0.6375457 utility, +0.0694444 completion,
and 8.3333 fewer planning ticks. It also has 1.5 more reconstructions, 3 more
communications, and 1.5 more task-owner changes in reconstruction size. Thus the planning reduction
does not satisfy the predeclared resource/reconstruction criterion. In the WM
pair, Event-GPPO-WM has +0.0227255 utility and 8.5 fewer planning ticks while
completion is equal; communication, reconstruction, and reconstruction size are
also equal. That pair likewise fails the fixed research criterion.

Both event methods produced nine actual local witnesses each, with zero empty
global witnesses. Each event method recorded 40 and 39 planning events,
respectively, of which 24 per method were non-NOOP: 9 local and 15 global.
NOOP counts were 16 and 15. Although the configured candidate maximum was 16,
the observed legal candidate counts were 1 through 7, with means 3.175 and
3.23077. The experiment did not demonstrate use of 16 candidates.

## What the Evidence Supports

- The stated formal workload completed, and the collected receipts are
  consistent with 54 evaluations, 3,240 ticks, 2,304 policy optimizer updates,
  288 training episodes, and 240 CUDA world-model updates.
- Fresh-process restoration evidence exists for three world models and 18
  policies.
- Event-GPPO reduced planning ticks relative to Periodic-GPPO in these runs,
  with higher utility and completion, alongside worse reconstruction,
  communication, and reconstruction-size measurements.
- Event-GPPO-WM and Periodic-GPPO-WM had nearly equal utility and equal
  completion; the event variant used fewer planning ticks without changes in
  communication, reconstruction, or reconstruction size.
- The fixed research gate failed. Preserve that result without changing the
  criterion after observing the measurements.

## What the Evidence Does Not Support

- It does not establish statistical significance: the study used three seeds
  and two development scenarios, with no independent confirmation set.
- It does not establish that WM provides a meaningful practical benefit.
  WM training is critic-only; it does not make the policy an actor-planner.
- It does not establish that GPPO is generally superior to PPO because the
  comparison is descriptive and not parameter-matched.
- The candidate-constrained method is CBBA-lite, not full CBBA, and the rules
  result is not an independent three-seed comparison.
- A configured maximum candidate count of 16 is not evidence that 16 candidates
  were used in these evaluations.
- It does not establish engineering completeness or final release acceptance;
  Sol Gate3 review remains pending.

## Next Study Design

For a follow-up, retain the failed criterion and design a study that can test
the missing resource/reconstruction outcome directly. Use parameter-matched
PPO/GPPO controls, more seeds, and an independent confirmation set. Add a
candidate-count condition that records and reaches the intended range, and
predefine separate analyses for planning, communication, reconstruction, and
candidate-size costs. These are recommendations only; none were executed in
this run.
