# Region Contract and C1 Test Result

Scope: v3 region contract, event wrapper generation, deterministic train/development parent count, 2x2 macro-region patch validation, and global public C1 receipt boundary.

Command, run from `package/`:

```text
python -B -m unittest discover -s tests -p "test_v3_*.py" -v
```

Captured result:

```text
test_public_c1_is_global_and_receipts_are_complete (test_v3_c1.RegionC1Tests.test_public_c1_is_global_and_receipts_are_complete) ... ok
test_boundaries_and_diagonal_eight_neighbors (test_v3_regions.RegionContractTests.test_boundaries_and_diagonal_eight_neighbors) ... ok
test_minimum_train_development_parent_counts (test_v3_regions.RegionContractTests.test_minimum_train_development_parent_counts) ... ok
test_spatial_patch_is_a_real_two_by_two_patch_inside_region (test_v3_regions.RegionContractTests.test_spatial_patch_is_a_real_two_by_two_patch_inside_region) ... ok
test_v3_fixed_platform_and_task_allocation (test_v3_regions.RegionContractTests.test_v3_fixed_platform_and_task_allocation) ... ok
test_validator_rejects_wrong_global_helicopter_metadata_or_position (test_v3_regions.RegionContractTests.test_validator_rejects_wrong_global_helicopter_metadata_or_position) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.194s

OK
```

This is module-level contract/C1 evidence only. It does not establish relief environment execution, S0/S1 acceptance, training readiness, or project-wide pass status.
