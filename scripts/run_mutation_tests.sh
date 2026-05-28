#!/usr/bin/env bash
# run_mutation_tests.sh — run mutmut against fleet_platform/services/ and report results
# Usage: ./scripts/run_mutation_tests.sh [--paths "services/drift_engine.py services/alert_svc.py"]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_DIR/.venv/bin/activate"

# shellcheck source=/dev/null
source "$VENV"

PATHS="${1:-fleet_platform/services/}"

echo "Running mutmut on: $PATHS"
echo "This may take 10-30 minutes depending on corpus size."
echo ""

cd "$REPO_DIR"

# Run mutmut
mutmut run \
    --paths-to-mutate "$PATHS" \
    --tests-dir tests/unit/ \
    --runner "python -m pytest tests/unit/ -x -q --tb=no" \
    --no-progress 2>&1 | tee mutmut-run.log

echo ""
echo "=== Results ==="
mutmut results 2>&1 | tee mutmut-results.log

echo ""
echo "=== Summary ==="
mutmut junitxml > mutmut-results.xml 2>&1 || true
mutmut results | tail -5
