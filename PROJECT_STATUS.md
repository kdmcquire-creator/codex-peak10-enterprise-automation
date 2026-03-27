# Peak 10 Enterprise Automation - Project Status

Last reviewed: 2026-03-21

## Executive Summary

This repository is past the architecture stage and contains real backend implementation across all four pillars. The current state is best described as:

- Architecture complete
- Core domain logic largely implemented
- CI and Azure infrastructure scaffolding present
- Production integrations partially wired, but not tenant-validated
- Tenant-specific deployment and final hardening still pending

The biggest near-term opportunity is to finish the tenant-backed Graph/SharePoint/Plaid integration passes now that the credential-free backend wiring and local persistence scaffolding are in place.

Recent autonomous progress:

- Repo-level status/readiness documentation added
- Pillar 2 runtime settings tightened for OpenAI, Document Intelligence, and Graph secrets
- Pillar 2 document classification can now extract text from uploaded file bytes
- Pillar 1 allocation runs now persist through a repository layer instead of process memory
- Pillar 3 staged documents and corrections now persist through a repository layer instead of process memory
- Pillar 4 transactions and claims now persist through a repository layer instead of process memory
- Pillar 2 Graph and mailbox parsing scaffolding now exists for the upcoming Outlook/SharePoint integration pass
- Pillar 2 now exposes a first mailbox ingestion pipeline that triages unread Graph messages, classifies attachments, and resolves SharePoint/staging targets
- Pillar 2 now includes timer-driven mailbox polling configuration around the ingestion pipeline, disabled by default until tenant setup is complete
- Pillar 2 attachment filing now stages low-confidence documents into `00_STAGING/Inbox` and unsupported files into `00_STAGING/Errors`
- Pillar 2 mailbox polling now degrades attachment fetch/parse and mark-processed failures into per-message warnings instead of aborting a full polling run
- Health/readiness payloads are broader across all four pillars to make remaining credential handoff more explicit

## Pillar Status

### Pillar 1 - AFA Engine

Status: backend prototype with strong domain logic

What is in place:

- Deterministic 4-pass allocation engine
- ACH export generation
- SQLite-backed persistence for allocation runs
- Azure Function endpoints
- OpenAPI contract
- Azure infrastructure template
- CI workflow and unit tests

What still needs work:

- Real approval workflow and audit persistence
- Cross-pillar filing and event integration

### Pillar 2 - Email Intelligence

Status: most advanced backend pillar, but not fully production-wired

What is in place:

- Rule-based email triage
- Azure OpenAI client wrapper
- Cosmos DB persistence layer with in-memory fallback
- Document classification, naming, and correction logging merged from Pillar 3
- Draft reply workflow
- Mailbox ingestion endpoint and Graph-backed unread message parsing
- Timer-trigger mailbox polling path with environment-based enable/schedule controls
- SharePoint upload target resolution with governed filing vs. staging behavior
- Non-fatal warning capture for mailbox ingestion edge cases plus operational summary counts for processed messages, attachments, uploads, and warnings
- Expanded health/readiness reporting for storage and downstream dependencies
- Azure infrastructure template
- CI workflow and unit tests

What still needs work:

- Webhook-driven mailbox notifications instead of scheduled polling
- Live Graph mailbox validation and admin-consented send/read scopes
- Live SharePoint upload validation against tenant folders and metadata
- Live tenant credential validation

### Pillar 3 - Document AI

Status: backend prototype with durable local persistence and governed filing logic

What is in place:

- Document staging and classification flow
- Naming and filing recommendation logic
- SQLite-backed persistence for staged documents and corrections
- SharePoint provisioning script
- OpenAPI contract
- Azure infrastructure template
- CI workflow and unit tests

What still needs work:

- Actual SharePoint/blob-backed file movement
- Real tenant-backed storage integration
- External AI/storage credential validation

### Pillar 4 - Expense Hub

Status: strong rules/security prototype

What is in place:

- Deterministic transaction classification engine
- Chinese Wall enforcement logic
- Expense claim flow and Pillar 1 payload shaping
- SQLite-backed persistence for transactions and claims
- Azure SQL infrastructure template
- CI workflow and unit tests

What still needs work:

- SQL-backed production persistence
- Plaid integration
- Receipt reconciliation with Pillar 2/Pillar 3 artifacts
- Production auth and approval workflow

## Cross-Pillar Status

Designed and partially modeled:

- Pillar 2 -> Pillar 4 receipt routing
- Pillar 4 -> Pillar 1 expense claim handoff
- Pillar 2 -> Pillar 3 document staging
- Pillar 1 -> Pillar 3 payment schedule filing

Still incomplete:

- Live service-to-service calls against deployed pillar endpoints
- Credentialed deployment configuration
- Retry/error handling across pillar boundaries
- Environment-specific secrets and routing

## Current Blockers

These items cannot be fully completed from code alone:

- Azure credentials and deployed resource details
- Microsoft Graph app registration and admin consent
- SharePoint tenant/site details
- Plaid credentials
- Final RBAC and approval-policy decisions

## Tenant Handoff Checklist

When you are ready for the final credentialed pass, this is the current handoff packet needed from you:

### Azure / Deployment

- Azure subscription ID
- Azure tenant ID
- Resource group name(s)
- Function App base URLs and host keys for deployed pillars
- Confirmation that Key Vault references resolve correctly in the target environment

### Microsoft Graph / Outlook

- `graph-client-id`
- `graph-client-secret`
- `graph-tenant-id`
- `graph-mailbox-address`
- Confirmation that admin consent is granted for `Mail.Read`, `Mail.ReadWrite`, `Mail.Send`, `Files.ReadWrite.All`, and `Sites.ReadWrite.All`
- Decision on whether mailbox polling should be enabled immediately after deploy

### SharePoint

- SharePoint site URL
- `graph-sharepoint-site-id`
- `graph-sharepoint-drive-id`
- Confirmation that the governed folder hierarchy has been provisioned
- Confirmation of whether low-confidence staging should remain in `00_STAGING/Inbox`

### Azure AI

- Azure OpenAI endpoint
- Azure OpenAI deployment name
- Confirmation that `azure-openai-key` is stored in Key Vault
- Document Intelligence endpoint
- Confirmation that `cognitive-services-key` is stored in Key Vault

### Plaid / Expense Hub

- `plaid-client-id`
- `plaid-secret`
- `plaid-environment`
- Any sandbox or production institution/account constraints for testing

## Autonomous Work Plan

The current execution order for autonomous work is:

1. Tighten repo-level status and readiness documentation
2. Fix Pillar 2 runtime configuration gaps for OpenAI and Document Intelligence
3. Improve Pillar 2 attachment extraction flow so document classification can use uploaded bytes directly
4. Replace in-memory state in Pillars 1, 3, and 4 with durable persistence
5. Scaffold Graph and SharePoint integration in Pillar 2
6. Add broader operational hardening, validation, and test coverage

Completed so far:

- Steps 1 through 5 for the initial backend scaffolding pass
- Most of step 6 for the first operational hardening pass

Next high-confidence engineering batch:

1. Tighten tenant-ready configuration docs for Graph, SharePoint, and Plaid handoff
2. Add more operational/error-path test coverage for mailbox ingestion and attachment filing
3. Prepare credential validation checklists for Graph, SharePoint, Azure, and Plaid handoff
4. Consider Graph webhook/subscription mode as the post-polling upgrade path

## Definition of "Ready for Your Input"

The target autonomous end state is:

- Backend code is production-shaped
- Environment variables and secrets are clearly defined
- Major persistence gaps are closed
- Integration code is in place where tenant access is not required
- Remaining work is narrowed to credentials, deployment, and business signoff
