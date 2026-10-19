# Public Correction: Episode Count

The included `FIRST_ZERO_DIAGNOSIS.json` preserves its source field `paired_development_episode_count: 6` and its source hash mapping. That field is misleadingly named: the value counts all six reviewed episodes across splits, not six development episodes. The final review contains 2 development episodes and 4 training episodes. The development gate means are computed over the 2 development episodes only. This correction clarifies the field without changing the source artifact or its mapping.
