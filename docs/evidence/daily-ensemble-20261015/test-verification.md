# Verification of forward daily ensemble diagnostics

Source checkpoint: `afa9a5fa4212ec7290d7e22f9e808d2fd0e808b9`.

- Ruff whole repository: PASS; mypy: PASS, 60 modules.
- Added tests: 24 PASS. Independent direct constrained optimization agrees with the block solution, including collinear and constant inputs. Unconverged fits are rejected.
- Forward windows are disjoint, purged by endpoint/receipt and embargoed. Changing a future outcome or an unreceived same-date peer's outcome leaves earlier models/calibrations/predictions unchanged.
- Isotonic interpolation agrees with sklearn; quantile correction and rank-to-return units replay. Original-candidate and ensemble metrics share the same cohort. Input timestamp, key, target and duplicate-campaign violations are rejected.
- Full regression suite: 650 PASS; coverage 86.580618%, ensemble module 93.229167%.
- The first targeted attempt had 19 PASS / 1 FAIL because the synthetic 20d history was too short after purge. The required minimum was preserved and the fixture extended; an incorrect initial coverage source argument was also corrected. Both logs remain in `.demo-artifacts/`.
- No original source data, candidate artifacts or existing user changes were overwritten. No real order was placed.

Exact log and coverage hashes are in `test-verification.json`. Fixture tests do not establish investment returns or real-market execution capabilities.
