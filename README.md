# Peak10-enterprise-automation

Peak 10 Energy enterprise automation platform, organized into four backend pillars:

- `pillar1-afa-engine`: deterministic AP allocation and ACH export
- `pillar2-email-intelligence`: email triage, drafting, document routing, and persistence
- `pillar3-document-ai`: document staging, classification, naming, and filing recommendations
- `pillar4-expense-hub`: expense classification, Chinese Wall enforcement, and AP handoff

The architecture and operator handoff docs live at the repo root:

- `Peak 10 Energy — Enterprise Automation Architecture.md`
- `DEPLOYMENT_GUIDE.md`
- `PILLAR2_PRODUCTION_GUIDE.md`
- `PROJECT_STATUS.md`

Operator tooling:

- `tools/smoke_test_cross_pillar.py` runs deployed health checks plus targeted live flows for Pillar 1 -> Pillar 3, Pillar 4 -> Pillar 1 payload handoff, and Pillar 2 mailbox ingestion once tenant Graph access is ready.

Current reality: the repo contains strong backend prototypes and deployment scaffolding, but not every planned production integration is finished yet. Start with `PROJECT_STATUS.md` for the clearest picture of what is coded, what is deployable, and what still depends on tenant-specific setup.

UI workbench:

- `workbench-ui` is the first-pass operations interface for the company-facing shell. It is organized around Inbox, Documents, AP, and Approvals instead of pillar-specific admin screens.
- The UI starts mock-first through a typed adapter layer and can overlay live pillar health when `VITE_PILLAR*_URL` and `VITE_PILLAR*_KEY` environment variables are supplied.
- `workbench-ui/.env.example` shows the expected endpoint variables for wiring the workbench to deployed pillar health, AP intake, and approval queues.
- Run it locally with `npm install` then `npm run dev` inside `workbench-ui`.

Notable current runtime surfaces:

- `pillar2-email-intelligence` now includes `POST /api/mailbox/ingest` to fetch unread Graph messages, triage them, classify attachments, and resolve governed SharePoint targets with safe staging behavior when confidence is low.
- Mailbox ingestion and polling now preserve per-message warnings for attachment fetch/parse and mark-processed failures so one bad item is less likely to abort a whole batch.
- `pillar2-email-intelligence` also includes timer-driven mailbox polling configuration, disabled by default until Graph/SharePoint tenant settings are ready.
- The mailbox ingest surface now returns summary counts for processed messages, warnings, attachments, and upload outcomes to make operations easier to read quickly.
- Each pillar exposes `GET /api/health`, and the health payloads now include readiness-oriented dependency and persistence details to narrow the remaining tenant handoff.
