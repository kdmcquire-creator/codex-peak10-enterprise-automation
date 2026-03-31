# Peak10 Workbench UI

First-pass company operations interface for the Peak 10 automation platform.

## Current Shape

- Standalone React + Vite app
- Workspaces for `Inbox`, `Documents`, `AP`, and `Approvals`
- Typed mock data model for design iteration
- Live overlay support for:
  - pillar health checks
  - Pillar 1 intake queue
  - Pillar 3 recent staged documents
  - Pillar 3 database update queue

## Environment Wiring

Copy `.env.example` to `.env` and populate the keys you want to use.

The adapter currently understands:

- `VITE_PILLAR1_URL`
- `VITE_PILLAR1_KEY`
- `VITE_PILLAR2_URL`
- `VITE_PILLAR2_KEY`
- `VITE_PILLAR3_URL`
- `VITE_PILLAR3_KEY`
- `VITE_PILLAR4_URL`
- `VITE_PILLAR4_KEY`

## Local Run

```powershell
cd C:\Users\kdmcq\Projects\Peak10-enterprise-automation\workbench-ui
npm install --ignore-scripts --cache .npm-cache
npm run dev
```

If the machine still raises the same local Node `EPERM` launcher issue seen in Codex, run the same commands from your normal user terminal. The UI source itself does not depend on native modules or postinstall hooks.

## Near-Term UI Work

1. Add richer Documents lane detail cards from live Pillar 3 metadata.
2. Add AP export summaries from Pillar 1 allocation/export history.
3. Add Inbox queue hydration from Pillar 2 mailbox ingest summaries.
4. Add operator action hooks for approve/review/file flows.
