# IST Timestamp Audit

Generated: 2026-06-06

## Summary

`frontend/src/utils/time.ts` provides `formatIST()` and `formatISTDate()` which correctly use
`toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })`. Most absolute timestamp displays in
pages already use these helpers. However, several **non-compliant** usages remain where
`new Date()` or `date-fns/format()` are used without IST conversion.

## Non-Compliant Usages (must fix — absolute timestamps displayed without IST)

| File | Line | Issue |
|------|------|-------|
| `frontend/src/pages/GroupExplorer.tsx` | 211 | `format(new Date(g.created_at), 'PP')` — date-fns format without timezone; uses browser locale |
| `frontend/src/pages/MonitoringPage.tsx` | 388 | `format(new Date(dataUpdatedAt), 'HH:mm:ss')` — time display without IST conversion |
| `frontend/src/utils/dateFormat.ts` | 8–11 | `formatDate()` uses `localStorage kri_timezone` fallback instead of always enforcing `Asia/Kolkata` |

## Acceptable Usages (no fix needed)

| File | Usage | Why acceptable |
|------|-------|----------------|
| `frontend/src/pages/MobileconfigManager.tsx` (L309, L427) | `formatDistanceToNow(new Date(...))` | Relative time only ("2 hours ago") — no timezone needed |
| `frontend/src/pages/PlaybookJobDetail.tsx` (L21, L115, L213) | `intervalToDuration` / `getTime()` / `formatDistanceToNow` | Duration calculation and relative time — no timezone needed |
| `frontend/src/pages/GroupDetail.tsx` (L267) | `formatDistanceToNow` | Relative time — no timezone needed |
| `frontend/src/pages/ExecutionHistory.tsx` (L181, L275) | `formatDistanceToNow` | Relative time — no timezone needed |
| `frontend/src/pages/SBOMExplorer.tsx` (L99) | `formatDistanceToNow` | Relative time — no timezone needed |
| `frontend/src/pages/DashboardPage.tsx` (L205) | `new Date(...).getTime()` for sort | Internal sort comparison — never displayed |
| `frontend/src/pages/AuditPage.tsx` (L30, L95, L128) | `.toISOString()` | API query parameter construction — not displayed to user |
| `frontend/src/pages/DriftComparePage.tsx` (L117) | `new Date().toISOString().slice(0,10)` | Filename generation — not displayed to user |
| `frontend/src/pages/ProvisioningPage.tsx` (L40–41) | `differenceInDays` | Numeric days-remaining calculation — not a display timestamp |
| `frontend/src/pages/FleetDashboard.tsx` (L887) | `differenceInDays` | Numeric days-remaining calculation — not a display timestamp |
| `frontend/src/pages/NodeDetail.tsx` (L305) | `differenceInDays` | Numeric days-remaining calculation — not a display timestamp |
| `frontend/src/pages/MonitoringPage.tsx` (L129, L342) | `number.toLocaleString()` | Number formatting (VRAM/count) — not a timestamp |
| `frontend/src/utils/time.ts` (L31, L45) | `new Date(date)` internal | Used inside `formatIST()` / `formatISTDate()` — output is IST |

## Action Required

Open a ticket for the three non-compliant usages above. Fix is:
- `GroupExplorer.tsx:211` — replace `format(new Date(g.created_at), 'PP')` with `formatISTDate(g.created_at)`
- `MonitoringPage.tsx:388` — replace `format(new Date(dataUpdatedAt), 'HH:mm:ss')` with IST-converted display
- `dateFormat.ts:formatDate()` — either enforce `Asia/Kolkata` unconditionally or deprecate in favour of `formatIST()` from `time.ts`
