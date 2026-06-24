# GitHub Platform Hardening — Full Feature Activation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate every relevant GitHub platform feature for the `hellodk/kri` repo so issues, bugs, PRs, releases, and security are tracked automatically with zero manual chasing.

**Architecture:** Pure GitHub configuration — workflows (YAML), API calls (`gh api`), and files in `.github/`. No application code changes. Each task is independently verifiable via `gh api` or the GitHub UI.

**Tech Stack:** `gh` CLI, GitHub Actions, GitHub Projects v2 GraphQL API, GitHub Pages, Dependabot, shields.io badges.

**Repo:** `hellodk/kri` — fleet management platform (FastAPI + React + SaltStack)

---

## Current State (as of 2026-05-24)

### Already done ✅
- 15 labels (p0–p3, bug, feature, breaking-change, blocked, etc.)
- Issue templates: feature, bug, breaking_change
- PR template with acceptance-criteria checklist
- CI: TypeScript build + unit tests on every PR
- Weekly digest workflow (creates GitHub Issue every Monday)
- Projects v2 board "kri Fleet Platform" linked to repo
- 5 open issues (#4–#8)

### Gaps this plan closes ❌
| # | Gap | Impact |
|---|-----|--------|
| T1 | README stale + no badges | First impression is broken (says "AWS scanner") |
| T2 | No branch protection on `master` | Anyone can push directly; CI not enforced |
| T3 | No milestones | Can't track sprint progress on board |
| T4 | No releases or release workflow | No versioned history despite VERSION file |
| T5 | No Dependabot | Dependency CVEs and drift go unnoticed |
| T6 | Discussions disabled | No space for RFCs or async Q&A |
| T7 | GitHub Pages not set up | Blog post exists but isn't published |
| T8 | No PR auto-labeler | Labels applied manually = forgotten |
| T9 | CI missing: lint, type check, coverage PR comment | Broken style and type errors sneak in |
| T10 | No stale bot | Old issues accumulate silently |
| T11 | No CODEOWNERS | No automatic review routing |
| T12 | Project board cards don't auto-move | Manual kanban = stale board |
| T13 | No Environments defined | No staging/prod separation |

---

## File Map

```
.github/
  dependabot.yml          ← T5: Dependabot config (pip, npm, actions)
  CODEOWNERS              ← T11: Review routing
  labeler.yml             ← T8: Path-based PR label rules
  workflows/
    ci.yml                ← T9: Add lint, type check, coverage comment jobs
    release.yml           ← T4: Auto-create GitHub release on VERSION bump
    stale.yml             ← T10: Mark + close stale issues
    labeler.yml           ← T8: Trigger labeler action on PR open/sync
    board-automation.yml  ← T12: Move project cards on PR events
README.md                 ← T1: Full rewrite + badges
docs/
  index.html              ← T7: Pages landing page
```

---

## Task 1: README Overhaul + Status Badges

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite README.md**

Replace the entire file with:

```markdown
# kri — Fleet Platform

[![CI](https://github.com/hellodk/kri/actions/workflows/ci.yml/badge.svg)](https://github.com/hellodk/kri/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/hellodk/kri?label=release)](https://github.com/hellodk/kri/releases)
[![Issues](https://img.shields.io/github/issues/hellodk/kri)](https://github.com/hellodk/kri/issues)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Kri ("Create" in Sanskrit) — an enterprise-grade fleet management platform for Apple Mac Mini hardware. Manages bootstrapping, drift detection, configuration, Ansible playbook execution, and SaltStack integration across a fleet of Mac Minis.

## Features

| Feature | Status |
|---------|--------|
| Node bootstrapping (SaltStack + SSH) | ✅ |
| Real-time drift detection | ✅ |
| Ansible playbook & role runner | ✅ |
| Bulk group operations | ✅ |
| SBOM pipeline | ✅ |
| Celery task queue + Redis | ✅ |
| JWT authentication | ✅ |
| E2E Playwright test suite | 🚧 |

## Tech Stack

- **Backend:** FastAPI · SQLAlchemy 2.0 async · Celery · PostgreSQL (TimescaleDB) · Redis
- **Frontend:** React 18 · TanStack Query 5 · Tailwind CSS · Vite
- **Automation:** SaltStack · Ansible · ansible-runner
- **Infrastructure:** Docker Compose · Nginx

## Quick Start

```bash
git clone https://github.com/hellodk/kri.git && cd kri
cp deploy/.env.example deploy/.env   # fill in secrets
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.yml up -d
```

App: http://localhost:3000 · API docs: http://localhost:8000/docs

## Development

```bash
uv sync --extra dev          # Python deps
cd frontend && npm ci        # JS deps
pytest tests/unit/ -q        # unit tests (must pass before commit)
pytest tests/integration/ -q # integration tests (needs Docker stack)
cd frontend && npm run build  # TypeScript check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for branching, TDD workflow, and PR requirements.

## Project Board

[kri Fleet Platform — GitHub Projects](https://github.com/users/hellodk/projects/2)

## License

MIT
```

- [ ] **Step 2: Verify file saved and commit**

```bash
git add README.md
git commit -m "docs: overhaul README — fleet platform description, badges, quick start"
```

---

## Task 2: Branch Protection on `master`

**Files:** None (API call only)

- [ ] **Step 1: Enable branch protection via gh API**

```bash
gh api repos/hellodk/kri/branches/master/protection \
  --method PUT \
  --field required_status_checks='{"strict":true,"contexts":["TypeScript build","Unit tests"]}' \
  --field enforce_admins=false \
  --field required_pull_request_reviews='{"required_approving_review_count":0,"dismiss_stale_reviews":false}' \
  --field restrictions=null \
  --field allow_force_pushes=false \
  --field allow_deletions=false \
  --field required_linear_history=true
```

Note: `required_approving_review_count: 0` means CI must pass but solo dev doesn't need a peer review. Change to `1` when team grows.

- [ ] **Step 2: Verify protection is active**

```bash
gh api repos/hellodk/kri/branches/master/protection \
  --jq '{enforce_admins:.enforce_admins.enabled, required_checks:.required_status_checks.contexts, force_push_allowed:.allow_force_pushes.enabled}'
```

Expected output:
```json
{"enforce_admins": false, "required_checks": ["TypeScript build", "Unit tests"], "force_push_allowed": false}
```

---

## Task 3: Milestones — Sprint Tracking

**Files:** None (API calls)

- [ ] **Step 1: Create Sprint 1 milestone (current sprint)**

```bash
gh api repos/hellodk/kri/milestones \
  --method POST \
  --field title="Sprint 1 — 2026-05-26" \
  --field description="First sprint: E2E smoke tests, offline node re-bootstrap, CI improvements" \
  --field due_on="2026-06-01T23:59:59Z"
```

- [ ] **Step 2: Assign open issues #4 and #5 to Sprint 1**

Issue #4 (E2E smoke tests) and #5 (re-bootstrap mm1/mm3) are P1-high — sprint priorities.

```bash
gh api repos/hellodk/kri/issues/4 --method PATCH --field milestone=1
gh api repos/hellodk/kri/issues/5 --method PATCH --field milestone=1
```

- [ ] **Step 3: Create Sprint 2 milestone for backlog**

```bash
gh api repos/hellodk/kri/milestones \
  --method POST \
  --field title="Sprint 2 — 2026-06-02" \
  --field description="Backlog: mutation testing, property-based tests, email digest" \
  --field due_on="2026-06-08T23:59:59Z"
```

- [ ] **Step 4: Assign issues #6, #7, #8 to Sprint 2**

```bash
gh api repos/hellodk/kri/issues/6 --method PATCH --field milestone=2
gh api repos/hellodk/kri/issues/7 --method PATCH --field milestone=2
gh api repos/hellodk/kri/issues/8 --method PATCH --field milestone=2
```

- [ ] **Step 5: Verify**

```bash
gh api repos/hellodk/kri/milestones --jq '.[].title'
```

Expected: `"Sprint 1 — 2026-05-26"` and `"Sprint 2 — 2026-06-02"`

---

## Task 4: Releases + Release Automation Workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create the first release manually (v0.1.56)**

```bash
gh release create v0.1.56 \
  --title "v0.1.56 — Ansible Playbook Runner + CI Hardening" \
  --notes "## What's in this release

### Features
- Ansible Playbook & Role Runner (Plan 12): playbook discovery, variable editor, job queue
- Bulk group deletion
- Salt returner integration + ingest pipeline

### Infrastructure
- CI: unit tests + integration tests + coverage gate (75%)
- Weekly digest as GitHub Issue every Monday
- Animated testing strategy blog post
- Branch protection on master
- Full GitHub platform hardening

### Bug Fixes
- Salt returner test path resolution (absolute path fix)
- Pre-push hook false-positive on OpenSSH placeholder text
" \
  --target master
```

- [ ] **Step 2: Create release automation workflow**

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    branches: [master]

jobs:
  maybe-release:
    name: Create release on VERSION bump
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 2

      - name: Check if VERSION changed
        id: version_check
        run: |
          OLD=$(git show HEAD~1:VERSION 2>/dev/null || echo "0.0.0")
          NEW=$(cat VERSION)
          echo "old=$OLD" >> $GITHUB_OUTPUT
          echo "new=$NEW" >> $GITHUB_OUTPUT
          if [ "$OLD" != "$NEW" ]; then
            echo "changed=true" >> $GITHUB_OUTPUT
          else
            echo "changed=false" >> $GITHUB_OUTPUT
          fi

      - name: Create GitHub release
        if: steps.version_check.outputs.changed == 'true'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          VERSION=$(cat VERSION)
          gh release create "v${VERSION}" \
            --title "v${VERSION}" \
            --generate-notes \
            --target master
```

- [ ] **Step 3: Commit and verify release exists**

```bash
git add .github/workflows/release.yml
git commit -m "chore: add release automation workflow — auto-release on VERSION bump"
gh release list --repo hellodk/kri
```

Expected: `v0.1.56` listed.

---

## Task 5: Dependabot

**Files:**
- Create: `.github/dependabot.yml`

- [ ] **Step 1: Create dependabot config**

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "09:00"
    labels: ["infra", "p3-low"]
    commit-message:
      prefix: "chore(deps)"
    open-pull-requests-limit: 5

  - package-ecosystem: npm
    directory: /frontend
    schedule:
      interval: weekly
      day: monday
      time: "09:00"
    labels: ["infra", "p3-low"]
    commit-message:
      prefix: "chore(deps)"
    open-pull-requests-limit: 5

  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "09:00"
    labels: ["infra", "p3-low"]
    commit-message:
      prefix: "chore(deps)"
```

- [ ] **Step 2: Commit**

```bash
git add .github/dependabot.yml
git commit -m "chore: add Dependabot — weekly updates for pip, npm, GitHub Actions"
```

- [ ] **Step 3: Verify Dependabot is active**

```bash
gh api repos/hellodk/kri/vulnerability-alerts --silent && echo "Security alerts enabled"
```

---

## Task 6: Enable GitHub Discussions

**Files:** None (API call only)

- [ ] **Step 1: Enable Discussions via API**

```bash
gh api repos/hellodk/kri \
  --method PATCH \
  --field has_discussions=true
```

- [ ] **Step 2: Verify**

```bash
gh api repos/hellodk/kri --jq '.has_discussions'
```

Expected: `true`

- [ ] **Step 3: Create starter discussions via GraphQL**

Get the repo's Discussion category IDs first:

```bash
gh api graphql -f query='
{
  repository(owner: "hellodk", name: "kri") {
    discussionCategories(first: 10) {
      nodes { id name }
    }
  }
}'
```

Then create an Announcements post:

```bash
# Use the "Announcements" category ID from above output
REPO_ID=$(gh api repos/hellodk/kri --jq '.node_id')
CATEGORY_ID="<announcements-category-id-from-above>"

gh api graphql -f query="
mutation {
  createDiscussion(input: {
    repositoryId: \"$REPO_ID\"
    categoryId: \"$CATEGORY_ID\"
    title: \"Welcome to kri Fleet Platform discussions\"
    body: \"Use this space for RFCs, feature ideas, Q&A, and announcements. For bugs use Issues.\"
  }) {
    discussion { url }
  }
}"
```

---

## Task 7: GitHub Pages — Publish the Blog

**Files:**
- Create: `docs/index.html`

- [ ] **Step 1: Create a docs landing index.html**

Create `docs/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>kri Fleet Platform — Docs</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif; max-width: 720px; margin: 60px auto; padding: 0 24px; color: #111827; }
    h1 { font-size: 2rem; font-weight: 700; margin-bottom: 8px; }
    p  { color: #4B5563; line-height: 1.6; }
    ul { padding-left: 20px; }
    li { margin: 8px 0; }
    a  { color: #4F46E5; text-decoration: none; font-weight: 500; }
    a:hover { text-decoration: underline; }
    .badge { display: inline-block; background: #F3F4F6; border: 1px solid #E5E7EB; border-radius: 6px; padding: 2px 8px; font-size: 0.8rem; color: #374151; margin-left: 8px; }
  </style>
</head>
<body>
  <h1>kri Fleet Platform</h1>
  <p>Enterprise fleet management — bootstrapping, drift detection, Ansible automation, and SaltStack integration.</p>
  <h2>Articles</h2>
  <ul>
    <li><a href="blog/testing-and-ci-strategy.html">Testing &amp; CI Strategy</a> <span class="badge">Engineering</span></li>
  </ul>
  <h2>Links</h2>
  <ul>
    <li><a href="https://github.com/hellodk/kri">GitHub Repository</a></li>
    <li><a href="https://github.com/hellodk/kri/issues">Issues</a></li>
    <li><a href="https://github.com/hellodk/kri/discussions">Discussions</a></li>
  </ul>
</body>
</html>
```

- [ ] **Step 2: Enable GitHub Pages via API**

```bash
gh api repos/hellodk/kri/pages \
  --method POST \
  --field source='{"branch":"master","path":"/docs"}'
```

- [ ] **Step 3: Commit and verify**

```bash
git add docs/index.html
git commit -m "docs: add GitHub Pages landing index + enable Pages from /docs"
gh api repos/hellodk/kri/pages --jq '{url:.html_url, status:.status}'
```

Expected: `{"url": "https://hellodk.github.io/kri/", "status": "built"}` (may take 1–2 minutes to build)

---

## Task 8: PR Auto-Labeler

**Files:**
- Create: `.github/labeler.yml`
- Create: `.github/workflows/labeler.yml`

- [ ] **Step 1: Create label rules file**

Create `.github/labeler.yml`:

```yaml
frontend:
  - changed-files:
    - any-glob-to-any-file: 'frontend/**'

infra:
  - changed-files:
    - any-glob-to-any-file:
      - '.github/**'
      - 'deploy/**'
      - 'docker-compose*.yml'

test:
  - changed-files:
    - any-glob-to-any-file: 'tests/**'

docs:
  - changed-files:
    - any-glob-to-any-file:
      - 'docs/**'
      - '*.md'

breaking-change:
  - changed-files:
    - any-glob-to-any-file:
      - 'fleet_platform/schemas/**'
      - 'frontend/src/api/**'
      - 'alembic/versions/**'
```

- [ ] **Step 2: Add a `frontend` label (currently missing)**

```bash
gh label create frontend --color "#0EA5E9" --description "Frontend / React changes" --repo hellodk/kri
```

- [ ] **Step 3: Create the labeler workflow**

Create `.github/workflows/labeler.yml`:

```yaml
name: PR Labeler

on:
  pull_request_target:
    types: [opened, synchronize]

jobs:
  label:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/labeler@v5
        with:
          repo-token: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 4: Commit**

```bash
git add .github/labeler.yml .github/workflows/labeler.yml
git commit -m "chore: add PR auto-labeler — frontend, infra, test, docs, breaking-change by path"
```

---

## Task 9: CI Improvements — Lint, Type Check, Coverage PR Comment

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add ruff lint, mypy type check, and coverage PR comment jobs**

Append these jobs to `.github/workflows/ci.yml` (after the existing `unit-tests` job):

```yaml
  lint:
    name: Lint (ruff)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - run: pip install uv
      - run: uv sync --extra dev
      - run: uv run ruff check fleet_platform/ tests/

  type-check:
    name: Type check (mypy)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - run: pip install uv
      - run: uv sync --extra dev
      - run: uv run mypy fleet_platform/ --ignore-missing-imports --no-error-summary

  coverage:
    name: Coverage report
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    services:
      postgres:
        image: timescale/timescaledb:latest-pg17
        env:
          POSTGRES_DB: fleet_demo
          POSTGRES_USER: fleet
          POSTGRES_PASSWORD: fleet
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 5s
          --health-timeout 3s
          --health-retries 15
    env:
      DATABASE_URL: postgresql+psycopg://fleet:fleet@localhost:5432/fleet_demo
      TEST_DATABASE_URL: postgresql+psycopg://fleet:fleet@localhost:5432/fleet_test
      REDIS_URL: redis://localhost:6379/0
      JWT_SECRET: ci-test-secret-minimum-32-chars-long
      FERNET_KEY: dGVzdC1rZXktbm90LWZvci1wcm9kdWN0aW9uLXVzZS1vbmx5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - run: pip install uv
      - run: uv sync --extra dev
      - run: |
          uv run pytest tests/unit/ \
            --cov=fleet_platform/services \
            --cov-report=term-missing \
            --cov-report=json:coverage.json \
            --cov-fail-under=75 -q
      - name: Post coverage comment on PR
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const cov = JSON.parse(fs.readFileSync('coverage.json'));
            const pct = cov.totals.percent_covered.toFixed(1);
            const body = `## Coverage Report\n\n**${pct}%** on \`fleet_platform/services/\` (gate: 75%)\n\n${pct >= 75 ? '✅ Gate passed' : '❌ Gate failed'}`;
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body
            });
```

- [ ] **Step 2: Ensure ruff and mypy are in dev dependencies**

Check `pyproject.toml` dev extras:

```bash
grep -A 20 '\[project.optional-dependencies\]' /home/dk/Documents/git/kri/pyproject.toml
```

If `ruff` or `mypy` are missing, add them:

```bash
# In pyproject.toml, under [project.optional-dependencies] dev = [...]
# Add: "ruff>=0.4", "mypy>=1.10"
# Then:
uv sync --extra dev
```

- [ ] **Step 3: Run lint and type check locally to confirm they pass**

```bash
source .venv/bin/activate
ruff check fleet_platform/ tests/ --statistics
mypy fleet_platform/ --ignore-missing-imports --no-error-summary
```

Fix any errors before committing.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml pyproject.toml
git commit -m "chore: CI — add ruff lint, mypy type check, coverage PR comment"
```

---

## Task 10: Stale Issue Bot

**Files:**
- Create: `.github/workflows/stale.yml`

- [ ] **Step 1: Create stale workflow**

```yaml
# .github/workflows/stale.yml
name: Stale Issues

on:
  schedule:
    - cron: '0 9 * * 1'  # Every Monday 09:00 UTC

jobs:
  stale:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/stale@v9
        with:
          repo-token: ${{ secrets.GITHUB_TOKEN }}
          stale-issue-message: >
            This issue has had no activity for 30 days. It will be closed in 7 days
            unless it is updated or labelled `blocked` or `ready`.
          close-issue-message: >
            Closed due to 37 days of inactivity. Reopen with a comment if still relevant.
          days-before-stale: 30
          days-before-close: 7
          stale-issue-label: stale
          exempt-issue-labels: 'blocked,p0-critical,p1-high,pinned'
          operations-per-run: 30
```

- [ ] **Step 2: Add `stale` label**

```bash
gh label create stale --color "#9CA3AF" --description "No activity for 30+ days" --repo hellodk/kri
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/stale.yml
git commit -m "chore: add stale bot — mark after 30 days, close after 7 more"
```

---

## Task 11: CODEOWNERS

**Files:**
- Create: `.github/CODEOWNERS`

- [ ] **Step 1: Create CODEOWNERS**

```
# .github/CODEOWNERS
# Default owner for everything
*                          @hellodk

# Frontend changes always need frontend review
frontend/                  @hellodk

# Schema and API changes are breaking-change risk
fleet_platform/schemas/    @hellodk
fleet_platform/api/        @hellodk
alembic/versions/          @hellodk

# CI/CD changes need infra review
.github/                   @hellodk
deploy/                    @hellodk
```

- [ ] **Step 2: Commit**

```bash
git add .github/CODEOWNERS
git commit -m "chore: add CODEOWNERS — route schema, API, infra, and frontend changes to owner"
```

---

## Task 12: Project Board Card Automation

**Files:**
- Create: `.github/workflows/board-automation.yml`

- [ ] **Step 1: Get the project and field IDs**

```bash
# Get project ID and status field ID
gh api graphql -f query='
{
  user(login: "hellodk") {
    projectV2(number: 2) {
      id
      fields(first: 20) {
        nodes {
          ... on ProjectV2SingleSelectField {
            id name options { id name }
          }
        }
      }
    }
  }
}'
```

Note the project `id`, the `Status` field `id`, and the option IDs for "In Progress", "In Review", "Done".

- [ ] **Step 2: Create the board automation workflow**

Fill in the IDs from Step 1 into `.github/workflows/board-automation.yml`:

```yaml
name: Project Board Automation

on:
  pull_request:
    types: [opened, ready_for_review, closed]
  issues:
    types: [opened]

env:
  PROJECT_ID: "PVT_kwHOACPj2M4BYn9C"
  STATUS_FIELD_ID: "<status-field-id-from-step-1>"
  IN_PROGRESS_OPTION_ID: "<in-progress-option-id>"
  IN_REVIEW_OPTION_ID: "<in-review-option-id>"
  DONE_OPTION_ID: "<done-option-id>"

jobs:
  move-card:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - name: Get item node ID
        id: get_item
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          NODE_ID: ${{ github.event.pull_request.node_id || github.event.issue.node_id }}
        run: |
          ITEM_ID=$(gh api graphql -f query="
            mutation {
              addProjectV2ItemById(input: {projectId: \"$PROJECT_ID\" contentId: \"$NODE_ID\"}) {
                item { id }
              }
            }" --jq '.data.addProjectV2ItemById.item.id')
          echo "item_id=$ITEM_ID" >> $GITHUB_OUTPUT

      - name: Set status — In Review (PR opened)
        if: github.event_name == 'pull_request' && github.event.action == 'opened'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh api graphql -f query="
            mutation {
              updateProjectV2ItemFieldValue(input: {
                projectId: \"$PROJECT_ID\"
                itemId: \"${{ steps.get_item.outputs.item_id }}\"
                fieldId: \"$STATUS_FIELD_ID\"
                value: { singleSelectOptionId: \"$IN_REVIEW_OPTION_ID\" }
              }) { projectV2Item { id } }
            }"

      - name: Set status — Done (PR merged)
        if: github.event_name == 'pull_request' && github.event.action == 'closed' && github.event.pull_request.merged == true
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh api graphql -f query="
            mutation {
              updateProjectV2ItemFieldValue(input: {
                projectId: \"$PROJECT_ID\"
                itemId: \"${{ steps.get_item.outputs.item_id }}\"
                fieldId: \"$STATUS_FIELD_ID\"
                value: { singleSelectOptionId: \"$DONE_OPTION_ID\" }
              }) { projectV2Item { id } }
            }"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/board-automation.yml
git commit -m "chore: project board automation — auto-move cards on PR open/merge"
```

---

## Task 13: GitHub Environments — Staging and Production

**Files:** None (API calls only)

- [ ] **Step 1: Create staging environment**

```bash
gh api repos/hellodk/kri/environments/staging \
  --method PUT \
  --field wait_timer=0
```

- [ ] **Step 2: Create production environment with protection**

```bash
gh api repos/hellodk/kri/environments/production \
  --method PUT \
  --field wait_timer=5 \
  --field reviewers='[{"type":"User","id":1}]'
```

Get your GitHub user ID first:
```bash
gh api user --jq '.id'
```

Then substitute that ID in the `reviewers` field above.

- [ ] **Step 3: Verify**

```bash
gh api repos/hellodk/kri/environments --jq '.[].name'
```

Expected: `staging` and `production`

- [ ] **Step 4: Add environment references to release.yml**

In `.github/workflows/release.yml`, update the `maybe-release` job:

```yaml
jobs:
  maybe-release:
    name: Create release on VERSION bump
    runs-on: ubuntu-latest
    environment: production    # ← add this line
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "chore: add staging + production environments, gate release on production env"
```

---

## Task 14: Pre-Commit Framework — Code Quality Gates

**Files:**
- Create: `.pre-commit-config.yaml`
- Create: `.github/hooks/check-test-presence.sh`
- Create: `.github/hooks/check-e2e-presence.sh`
- Create: `.github/hooks/check-contract-drift.sh`

- [ ] **Step 1: Install pre-commit framework**

```bash
source .venv/bin/activate
pip install pre-commit  # or: uv add pre-commit --dev
pre-commit --version    # expected: pre-commit 3.x.x
```

- [ ] **Step 2: Create `.pre-commit-config.yaml`**

```yaml
# .pre-commit-config.yaml
repos:
  # Ruff — lint + format (replaces flake8, isort, pyupgrade)
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.7
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
        files: ^(fleet_platform|tests)/
      - id: ruff-format
        files: ^(fleet_platform|tests)/

  # Mypy — type checking on staged fleet_platform files
  - repo: local
    hooks:
      - id: mypy
        name: mypy type check
        entry: bash -c 'source .venv/bin/activate && mypy fleet_platform/ --ignore-missing-imports --no-error-summary'
        language: system
        files: ^fleet_platform/
        pass_filenames: false

  # Vulture — dead code detection
  - repo: local
    hooks:
      - id: vulture
        name: dead code (vulture)
        entry: bash -c 'source .venv/bin/activate && vulture fleet_platform/ --min-confidence 80'
        language: system
        files: ^fleet_platform/
        pass_filenames: false

  # Bandit — security smells
  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.9
    hooks:
      - id: bandit
        args: [-r, fleet_platform/, -ll, --skip, B101]
        pass_filenames: false

  # YAML / TOML syntax validation
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-yaml
      - id: check-toml
      - id: check-json
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: mixed-line-ending

  # TypeScript type check when frontend files staged
  - repo: local
    hooks:
      - id: tsc
        name: TypeScript type check
        entry: bash -c 'cd frontend && npm run build -- --noEmit 2>&1 | tail -20'
        language: system
        files: ^frontend/src/
        pass_filenames: false

  # Missing unit test guard (warning, not block)
  - repo: local
    hooks:
      - id: check-unit-test-presence
        name: unit test presence check
        entry: .github/hooks/check-test-presence.sh
        language: script
        files: ^fleet_platform/services/
        pass_filenames: true

  # Contract drift detector
  - repo: local
    hooks:
      - id: check-contract-drift
        name: contract drift check (schema ↔ TS interface)
        entry: .github/hooks/check-contract-drift.sh
        language: script
        files: ^fleet_platform/schemas/
        pass_filenames: true

  # Migration conflict guard
  - repo: local
    hooks:
      - id: check-migration-conflict
        name: alembic migration conflict guard
        entry: bash -c 'count=$(git diff --cached --name-only | grep "alembic/versions/" | wc -l); if [ "$count" -gt 1 ]; then echo "⚠ WARNING: Multiple migration files staged — verify ordering before pushing"; fi; exit 0'
        language: system
        pass_filenames: false
```

- [ ] **Step 3: Create the missing-unit-test guard script**

Create `.github/hooks/check-test-presence.sh`:

```bash
#!/usr/bin/env bash
# Warn if a services/*.py file has no corresponding test file.
# Exit 0 always — this is a warning, not a block.
set -e
WARNED=0
for f in "$@"; do
  base=$(basename "$f" .py)
  test_file="tests/unit/test_${base}.py"
  if [ ! -f "$test_file" ]; then
    echo "⚠  WARNING: No unit test found for $f — expected $test_file"
    WARNED=1
  fi
done
[ "$WARNED" -eq 1 ] && echo "   Unit tests are required before opening a PR (CLAUDE.md)"
exit 0
```

```bash
chmod +x .github/hooks/check-test-presence.sh
```

- [ ] **Step 4: Create the contract drift detector script**

Create `.github/hooks/check-contract-drift.sh`:

```bash
#!/usr/bin/env bash
# Warn if a Pydantic schema file is staged without a matching TS interface update.
set -e
WARNED=0
for f in "$@"; do
  base=$(basename "$f" .py)
  # Check if any frontend/src/api/ file was also staged
  ts_staged=$(git diff --cached --name-only | grep "frontend/src/api/" || true)
  if [ -z "$ts_staged" ]; then
    echo "⚠  CONTRACT DRIFT RISK: $f modified but no frontend/src/api/*.ts staged"
    echo "   Update the matching TypeScript interface in the same commit (CLAUDE.md)"
    WARNED=1
  fi
done
exit 0
```

```bash
chmod +x .github/hooks/check-contract-drift.sh
```

- [ ] **Step 5: Install hooks into local git**

```bash
source .venv/bin/activate
pre-commit install
pre-commit install --hook-type pre-push
```

- [ ] **Step 6: Dry-run against entire codebase and fix issues**

```bash
source .venv/bin/activate
pre-commit run --all-files 2>&1 | tee /tmp/precommit-first-run.txt
```

Fix any ruff, mypy, bandit, or YAML failures before committing. Vulture and the warning-only hooks exit 0 so they won't block.

- [ ] **Step 7: Add vulture and detect-secrets to pyproject.toml dev deps**

In `pyproject.toml` under `[project.optional-dependencies]` `dev = [...]`, ensure these are present:

```toml
"ruff>=0.4",
"mypy>=1.10",
"vulture>=2.11",
"bandit[toml]>=1.7",
"pre-commit>=3.7",
```

Then:
```bash
uv sync --extra dev
```

- [ ] **Step 8: Commit**

```bash
git add .pre-commit-config.yaml .github/hooks/ pyproject.toml
git commit -m "chore: add pre-commit framework — ruff, mypy, vulture, bandit, contract drift, test presence guards"
```

- [ ] **Step 9: Document in CONTRIBUTING.md**

Add to `CONTRIBUTING.md` after the dev setup section:

```markdown
### Pre-commit hooks

Install once after cloning:

\`\`\`bash
uv sync --extra dev
pre-commit install
\`\`\`

Hooks run automatically on `git commit`. To run manually against all files:

\`\`\`bash
pre-commit run --all-files
\`\`\`

| Hook | What it catches |
|---|---|
| ruff | Lint errors, unused imports — auto-fixed |
| ruff-format | Formatting drift — auto-fixed |
| mypy | Type errors in `fleet_platform/` |
| vulture | Dead code (functions, variables never used) |
| bandit | Security smells (hardcoded secrets, SQL injection risk) |
| tsc | TypeScript type errors in `frontend/src/` |
| check-unit-test-presence | Warns if `services/*.py` has no `tests/unit/test_*.py` |
| check-contract-drift | Warns if Pydantic schema changed without a TS interface update |
| check-migration-conflict | Warns if multiple Alembic migrations staged simultaneously |
```

```bash
git add CONTRIBUTING.md
git commit -m "docs: document pre-commit hooks in CONTRIBUTING.md"
```

---

## Self-Review

### Spec coverage
- ✅ T1: README + badges
- ✅ T2: Branch protection
- ✅ T3: Milestones
- ✅ T4: Releases + automation
- ✅ T5: Dependabot
- ✅ T6: Discussions
- ✅ T7: GitHub Pages
- ✅ T8: PR auto-labeler
- ✅ T9: CI improvements (lint, type check, coverage comment)
- ✅ T10: Stale bot
- ✅ T11: CODEOWNERS
- ✅ T12: Project board automation
- ✅ T13: Environments
- ✅ T14: Pre-commit framework (ruff, mypy, vulture, bandit, contract drift, unit test presence, migration guard)

### Placeholder scan
- T12 Step 2 contains `<status-field-id-from-step-1>` — this is intentional; IDs must be fetched at execution time from the GraphQL query in Step 1. The step documents exactly how to get them.
- T13 Step 2 contains `'[{"type":"User","id":1}]'` — user ID must be fetched at execution time via `gh api user --jq '.id'`. Step documents this.

### Sequencing
- T9 (lint/type check) should run before T2 (branch protection adding those checks) — but branch protection only enforces checks that already exist in CI. Since lint/type check are new jobs, they won't be in the required-checks list until added. Implementation order: run T9 first to add the jobs, then update T2's `contexts` list to include them.

### Notes for executor
- T6 (Discussions) requires the repo to have Discussions enabled; the GraphQL category IDs will differ per repo — fetch them fresh at execution time.
- Dependabot (T5) will start opening PRs the following Monday — this is expected and desired.
- GitHub Pages (T7) may take 1–2 minutes to build after the API call.
