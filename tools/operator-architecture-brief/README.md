# Peak 10 Operator Architecture Brief

Editable PowerPoint deck source for explaining the Peak 10 automation platform to technical infrastructure and software reviewers.

## Files

- `build_deck.js`: PptxGenJS source
- `Peak10_Operator_Architecture_Brief.html`: browser-ready slide-style deck
- `Peak10_Operator_Architecture_Brief.pptx`: generated deck when built locally
- `rendered/`: optional slide renders for review

## Open First

If you want the brief immediately, open:

`C:\Users\kdmcq\Projects\Peak10-enterprise-automation\tools\operator-architecture-brief\Peak10_Operator_Architecture_Brief.html`

The PowerPoint source is included, but the current Codex shell on this machine hits a local Node entrypoint permission bug when trying to execute the PptxGenJS build. The HTML deck is the ready-to-use artifact from this session.

## Build

```powershell
cd C:\Users\kdmcq\Projects\Peak10-enterprise-automation\tools\operator-architecture-brief
npm install --cache .npm-cache
npm run build
```

## Render For Review

```powershell
python C:\Users\kdmcq\.codex\skills\slides\scripts\render_slides.py `
  C:\Users\kdmcq\Projects\Peak10-enterprise-automation\tools\operator-architecture-brief\Peak10_Operator_Architecture_Brief.pptx `
  --output_dir C:\Users\kdmcq\Projects\Peak10-enterprise-automation\tools\operator-architecture-brief\rendered
```
