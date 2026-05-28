# Mutation Testing with mutmut

## Overview

Mutation testing finds test suite weaknesses by injecting small code changes (mutations) and checking if the tests catch them. A surviving mutant = a gap in test coverage.

## Quick Start

```bash
# Run against all services/ (slow — 10-30 minutes)
./scripts/run_mutation_tests.sh

# Run against a single service (fast — 1-5 minutes)
source .venv/bin/activate
mutmut run --paths-to-mutate fleet_platform/services/drift_engine.py

# View surviving mutants
mutmut results

# Inspect a specific mutant (e.g., mutant #42)
mutmut show 42

# Apply a mutant to the codebase to see what it does
mutmut apply 42
git diff
mutmut unapply
```

## Interpreting Results

| Status | Meaning |
|--------|---------|
| Killed | Tests caught this mutation ✅ |
| Survived | Tests did NOT catch this mutation ⚠️ |
| Suspicious | Tests ran but gave ambiguous result |
| Timeout | Test suite timed out on this mutation |
| Skipped | Mutation was skipped |

## Target

- Goal: **>80% killed rate** on `fleet_platform/services/`
- Run quarterly or after major service changes
- Document surviving mutants — each one is a potential test to add

## Key Services to Focus On

1. `drift_engine.py` — core business logic, high value target
2. `alert_svc.py` — alert evaluation logic
3. `platform_settings_svc.py` — settings validation

## CI Integration

Mutation testing is intentionally NOT in the main CI pipeline (too slow). Run it locally or as a scheduled job:

```yaml
# .github/workflows/mutation-tests.yml (manual trigger)
name: Mutation Tests
on:
  workflow_dispatch:
    inputs:
      paths:
        description: 'Paths to mutate'
        default: 'fleet_platform/services/'
jobs:
  mutmut:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install mutmut
      - run: ./scripts/run_mutation_tests.sh
      - uses: actions/upload-artifact@v4
        with:
          name: mutation-results
          path: mutmut-results.xml
```
