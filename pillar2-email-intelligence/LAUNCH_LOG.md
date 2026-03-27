# Pillar 2 Launch Log

## Purpose

This log captures the working deployment workflow, live validation history, issues we encountered in the lab tenant, and the fixes or mitigations we applied before moving Pillar 2 into the Peak 10 environment.

It is not a claim of "bug free." It is a de-risking record and launch reference.

## Current Lab Status

As of 2026-03-26, the lab environment has successfully demonstrated:

- Graph mailbox read
- Email triage with AI
- Attachment classification
- Document Intelligence extraction
- SharePoint filing and staging
- Cosmos persistence
- Draft reply generation
- Draft send in `dry_run`
- Calendar assist
- Morning Brief generation
- Carry-over state for Follow-Ups and Watchlist items
- Brief item resolve, dismiss, and reopen actions
- Brief item list API
- Brief review HTML surface
- Direct brief-item operator actions:
  - archive
  - mark read
  - draft reply from context
  - draft event from scheduling context
  - operator notes on resolve/dismiss flows
  - safer archive fallback when the mailbox source message is already gone

## Working Azure Deploy Workflow

Because the repo contains locked `pytest-cache-files-*` folders, direct publish from the source tree is unreliable.

Use a clean staging copy under `.deploy`, then publish from there:

1. Copy `email_intel/`
2. Copy:
   - `function_app.py`
   - `host.json`
   - `requirements.txt`
   - `pyproject.toml`
   - `.funcignore`
3. Remove copied `__pycache__` folders if present
4. Publish from the staging folder:

```powershell
func azure functionapp publish func-codexpeak10dev --python --build remote
```

## Critical Deployment Lessons

### 1. Remote build must actually run Oryx

Symptoms:

- App deployed, but `cosmos_connected`, `openai_available`, and `document_intelligence_available` were `false`
- Graph features still worked
- Publish output showed file sync only, not dependency install

Root cause:

- Azure deployment performed `parallel_rsync.sh` without running Oryx/pip install

Fix:

- Ensure:
  - `SCM_DO_BUILD_DURING_DEPLOYMENT = true`
  - `ENABLE_ORYX_BUILD = true`
- Republish until output explicitly shows:
  - `Running oryx build...`
  - `Running pip install...`

### 2. Key Vault references can look healthy before the runtime fully picks them up

Symptoms:

- App settings showed green Key Vault references
- Health still reported missing Cosmos/OpenAI/DI

Fix pattern:

- Pull reference values
- Apply environment variables
- Restart app
- Recheck `/api/health`

### 3. Portal file views can be misleading

Observed:

- Route code and HTML/UI code did not always appear to update together
- In at least one deploy, `function_app.py` changes landed while `email_intel/brief_review.py` appeared stale at runtime

Mitigation:

- Validate by hitting live routes directly, not only by inspecting portal file views
- Confirm expected route behavior through API responses and HTML markers

## Live Validation Milestones

### Mailbox + Filing

Validated live:

- Invoices classified and filed to governed SharePoint paths
- Low-confidence PDFs staged to review folders
- Unsupported attachments routed to error folders
- File renaming and governed naming conventions worked

### Morning Brief

Validated live:

- Morning Brief route returns `Watchlist` and `Follow-Ups`
- Carry-over items can be resolved
- Resolved items stay suppressed on subsequent brief runs
- Reopened items reappear

### Review Workflow

Validated live:

- `GET /api/email/brief/items`
- `POST /api/email/brief/items/{item_id}/state`
- `GET /api/email/brief/items/{item_id}/context`
- Review actions:
  - resolve
  - dismiss
  - reopen
  - mark read
  - draft reply from context

### Brief Item Quick Actions

Observed on 2026-03-26:

- `mark_read` and `generate_reply_draft` worked on a real mailbox-backed brief item
- `archive` initially failed with a Graph `404`

Root cause:

- the app posted `destinationId = "archive"` directly to Graph
- in this tenant, the archive move path needed the actual folder ID resolved first

Fix:

- Graph client now resolves mailbox folder IDs before calling message move
- it first tries the well-known folder lookup, then falls back to top-level folder listing by `displayName` / `wellKnownName`
- brief-item archive actions now degrade safely to `mark read + resolve` if Graph move still fails
- mailbox action responses now include parsed Graph error details for easier tenant-specific diagnosis

## Feature Notes

### Morning Brief Review

Current operator surface now supports:

- `Draft reply` from brief-item context
- `Draft event` from scheduling-related brief items
- event-draft preview directly in the context panel after the quick action runs
- inline operator notes that travel with resolve/dismiss actions
- resilient archive fallback:
  - if Graph says the source message no longer exists, the brief item resolves with a clear `source_missing` reason instead of failing hard

### Calendar Intent + Event Drafting

Recent hardening on 2026-03-26:

- softer scheduling language like "connect next week," "find a time," and "jump on a call" is more reliably treated as calendar intent
- extracted time phrases are cleaned before they feed summaries and draft copy
- when a brief item is already promoted as calendar-related, the event-draft path now uses that hint instead of falling back to `unknown`

### Ongoing Projects

Recent improvement:

- ongoing projects are grouped more by contact + subject family, not just exact subject matches
- this reduces duplicate project rows for closely related threads like diligence/timing/next-step variations

### Outbound Email

Current safe operating mode:

- `OUTBOUND_EMAIL_MODE = dry_run`

Recommendation:

- Keep `dry_run` until Peak 10-specific recipient/domain controls are validated

### Mailbox Polling

Current safe operating mode:

- `MAILBOX_POLL_ENABLED = false`
- `MAILBOX_MARK_PROCESSED = false`

Recommendation:

- Do not enable automatic polling/processing in Peak 10 until manual validation is complete

## Recent Hardening

### Event Draft Workflow

What changed:

- added persisted event-draft records tied to source messages
- added message-scoped event-draft listing and event-draft update/delete routes
- brief-item `Draft event` actions now persist generated event drafts instead of returning throwaway payloads only
- brief-item context now surfaces saved event drafts back into the review experience
- approved event drafts can now be promoted into real Microsoft 365 calendar events through an explicit create-event route

Why it matters:

- event suggestions can now become a real tracked workflow instead of a one-shot response
- operators can review, approve, and revisit event drafts across Morning Brief sessions
- calendar creation remains explicitly human-approved instead of silently automating scheduling

### Morning Brief Quality

What changed:

- ongoing projects now include `latest_direction`, `next_decision`, `days_active`, and contact-memory context
- the brief overview now reports `relationship_memory_count`
- relationship memory highlights recurring contacts that may deserve attention even outside a single thread
- project clustering now merges same-sender / same-subject-family threads more aggressively so duplicate-looking rows do not crowd the brief
- relationship memory now filters low-signal internal/unknown contacts more aggressively and ranks watch-worthy relationships above inbox noise
- ongoing-project surfacing now suppresses low-value attachment/test/internal threads unless they show stronger urgency or repeated motion

Why it matters:

- Morning Brief is shifting from simple queue presentation toward a more relational operator view
- this should reduce “I know this person matters, but why is this here?” friction during live use
- the operator view should feel more curated and less like raw mailbox telemetry

## Known Risk Areas For Peak 10 Rollout

These are the areas most likely to produce environment-specific issues even if the lab stays green:

- Graph app permissions and admin consent
- mailbox policy differences
- external forwarding restrictions
- SharePoint path and drive differences
- tenant-specific DLP/security controls
- deployment consistency between SCM/runtime package contents
- Key Vault reference propagation timing

## Peak 10 Launch Checklist

### Before first live validation

- Confirm Graph app registration and admin consent
- Confirm mailbox address and access scope
- Confirm SharePoint site and drive IDs
- Confirm Key Vault secrets resolve in app settings
- Confirm remote build is using Oryx
- Confirm `/api/health` is fully green

### First controlled production-shaped validation

- Keep polling disabled
- Keep mark-processed disabled
- Run manual mailbox ingest on a curated test set
- Validate SharePoint routing and naming
- Validate draft generation in `dry_run`
- Validate Morning Brief and review flows

### Only after that

- Test `mark_processed=true` on throwaway messages
- Consider enabling polling
- Consider enabling non-dry-run outbound sending

## Open/Watch Items

These are the main areas to keep watching as the project continues:

- review page/runtime consistency after deploy
- richer brief item context coverage for previously stored records
- launch UI polish and operator ergonomics
- stronger rollout/runbook discipline for repeatable Azure deploys

## Practical Interpretation

This log is meant to answer:

- What worked?
- What broke?
- How did we fix it?
- What still needs explicit validation when we move to Peak 10?

It should be updated after each meaningful live validation or deployment issue.
