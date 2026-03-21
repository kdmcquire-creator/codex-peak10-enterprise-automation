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

Current reality: the repo contains strong backend prototypes and deployment scaffolding, but not every planned production integration is finished yet. Start with `PROJECT_STATUS.md` for the clearest picture of what is coded, what is deployable, and what still depends on tenant-specific setup.

Notable current runtime surfaces:

- `pillar2-email-intelligence` now includes `POST /api/mailbox/ingest` to fetch unread Graph messages, triage them, classify attachments, and resolve governed SharePoint targets with safe staging behavior when confidence is low.
- `pillar2-email-intelligence` also includes timer-driven mailbox polling configuration, disabled by default until Graph/SharePoint tenant settings are ready.
- Each pillar exposes `GET /api/health`, and the health payloads now include readiness-oriented dependency and persistence details to narrow the remaining tenant handoff.
