const pptxgen = require("pptxgenjs");
const {
  warnIfSlideHasOverlaps,
  warnIfSlideElementsOutOfBounds,
} = require("./pptxgenjs_helpers");

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "OpenAI Codex";
pptx.company = "Peak 10 Energy";
pptx.subject = "Operator architecture brief";
pptx.title = "Peak 10 Operator Architecture Brief";
pptx.lang = "en-US";
pptx.theme = {
  headFontFace: "Aptos Display",
  bodyFontFace: "Aptos",
  lang: "en-US"
};

const C = {
  bg: "0B1013",
  panel: "131A1F",
  panelAlt: "171F25",
  line: "2A333B",
  text: "F3EDE1",
  muted: "A59D91",
  brass: "D4A96A",
  blue: "7FB4FF",
  teal: "63C6B1",
  coral: "F58E73",
  danger: "EF6F70",
  white: "FFFFFF",
  black: "0B1013"
};

const PILLAR = {
  p1: C.brass,
  p2: C.blue,
  p3: C.teal,
  p4: C.coral
};

function addBackground(slide) {
  slide.background = { color: C.bg };
  slide.addShape(pptx.ShapeType.rect, {
    x: 0.18, y: 0.18, w: 12.96, h: 7.14,
    line: { color: "1B2329", pt: 1 },
    fill: { color: C.bg },
    radius: 0.12
  });
  slide.addShape(pptx.ShapeType.rect, {
    x: 0.35, y: 0.35, w: 12.62, h: 6.8,
    line: { color: C.line, pt: 1 },
    fill: { color: C.panel, transparency: 10 },
    radius: 0.12
  });
}

function addSlideHeader(slide, eyebrow, title, subtitle, slideNo) {
  slide.addText(eyebrow.toUpperCase(), {
    x: 0.6, y: 0.45, w: 3.8, h: 0.2,
    fontFace: "Aptos",
    fontSize: 9,
    bold: false,
    color: C.muted,
    charSpace: 2.2
  });
  slide.addText(title, {
    x: 0.6, y: 0.68, w: 7.5, h: 0.8,
    fontFace: "Aptos Display",
    fontSize: 28,
    bold: true,
    color: C.text,
    margin: 0
  });
  slide.addText(subtitle, {
    x: 0.6, y: 1.38, w: 8.5, h: 0.38,
    fontFace: "Aptos",
    fontSize: 11.5,
    color: "C8C1B5",
    margin: 0
  });
  slide.addText(String(slideNo).padStart(2, "0"), {
    x: 12.15, y: 0.52, w: 0.35, h: 0.2,
    align: "right",
    fontFace: "Aptos Display",
    fontSize: 10,
    color: C.muted
  });
}

function addBadge(slide, x, y, label, color, textColor = C.black) {
  const w = Math.max(0.7, 0.18 + label.length * 0.075);
  slide.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h: 0.28,
    rectRadius: 0.08,
    line: { color, pt: 0.5 },
    fill: { color, transparency: 0 }
  });
  slide.addText(label, {
    x: x + 0.08, y: y + 0.06, w: w - 0.16, h: 0.12,
    align: "center",
    fontFace: "Aptos",
    fontSize: 8,
    bold: true,
    color: textColor,
    margin: 0
  });
}

function addCard(slide, opts) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x: opts.x, y: opts.y, w: opts.w, h: opts.h,
    rectRadius: 0.08,
    line: { color: opts.border || C.line, pt: 1 },
    fill: { color: opts.fill || C.panelAlt, transparency: 0 }
  });
  if (opts.accent) {
    slide.addShape(pptx.ShapeType.rect, {
      x: opts.x, y: opts.y, w: 0.06, h: opts.h,
      line: { color: opts.accent, pt: 0 },
      fill: { color: opts.accent }
    });
  }
  if (opts.eyebrow) {
    slide.addText(opts.eyebrow.toUpperCase(), {
      x: opts.x + 0.18, y: opts.y + 0.14, w: opts.w - 0.36, h: 0.14,
      fontFace: "Aptos",
      fontSize: 8,
      color: C.muted,
      charSpace: 1.8,
      margin: 0
    });
  }
  if (opts.title) {
    slide.addText(opts.title, {
      x: opts.x + 0.18, y: opts.y + 0.34, w: opts.w - 0.36, h: 0.34,
      fontFace: "Aptos Display",
      fontSize: opts.titleSize || 15,
      bold: true,
      color: C.text,
      margin: 0
    });
  }
  if (opts.body) {
    slide.addText(opts.body, {
      x: opts.x + 0.18, y: opts.y + 0.72, w: opts.w - 0.36, h: opts.h - 0.88,
      fontFace: "Aptos",
      fontSize: opts.bodySize || 10.5,
      color: "C7C0B4",
      margin: 0
    });
  }
}

function addBulletList(slide, items, x, y, w, h, fontSize = 11) {
  const runs = [];
  items.forEach((item) => {
    runs.push({
      text: item,
      options: {
        bullet: { indent: 12 },
        breakLine: true,
      }
    });
  });
  slide.addText(runs, {
    x, y, w, h,
    fontFace: "Aptos",
    fontSize,
    color: "D8D0C3",
    valign: "top",
    paraSpaceAfterPt: 7,
    breakLine: false,
    margin: 0.02
  });
}

function addArrow(slide, x1, y1, x2, y2, color = C.muted, label) {
  slide.addShape(pptx.ShapeType.line, {
    x: x1, y: y1, w: x2 - x1, h: y2 - y1,
    line: { color, pt: 1.8, endArrowType: "triangle" }
  });
  if (label) {
    const x = Math.min(x1, x2) + Math.abs(x2 - x1) / 2 - 0.65;
    const y = Math.min(y1, y2) + Math.abs(y2 - y1) / 2 - 0.12;
    slide.addText(label, {
      x, y, w: 1.3, h: 0.18,
      align: "center",
      fontFace: "Aptos",
      fontSize: 8,
      bold: true,
      color,
      margin: 0,
      fill: { color: C.bg, transparency: 18 }
    });
  }
}

function addNode(slide, x, y, w, h, title, body, color, badge) {
  addCard(slide, {
    x, y, w, h,
    fill: "12181D",
    border: color,
    accent: color,
    title,
    body,
    titleSize: 13,
    bodySize: 9.5
  });
  if (badge) {
    addBadge(slide, x + w - 0.9, y + 0.12, badge, color, C.black);
  }
}

function addFooter(slide, text) {
  slide.addText(text, {
    x: 0.65, y: 6.85, w: 11.9, h: 0.18,
    fontFace: "Aptos",
    fontSize: 8,
    color: C.muted,
    margin: 0
  });
}

function finalizeSlide(slide) {
  warnIfSlideHasOverlaps(slide, pptx);
  warnIfSlideElementsOutOfBounds(slide, pptx);
}

function slide1() {
  const slide = pptx.addSlide();
  addBackground(slide);
  addSlideHeader(
    slide,
    "Operator architecture brief",
    "Peak 10 Enterprise Automation Platform",
    "A control-room view of what is connected, what is driving the flows, where governance sits, and what is already live versus still tenant-gated.",
    1
  );

  slide.addText("What this brief makes immediately legible", {
    x: 0.7, y: 2.0, w: 3.9, h: 0.25,
    fontFace: "Aptos Display",
    fontSize: 17,
    bold: true,
    color: C.text,
    margin: 0
  });
  addBulletList(slide, [
    "How email, documents, AP logic, and expense workflows behave as one governed system",
    "Why unusual cross-signals exist, including vendor tone, contacts, attachments, and AP priority inputs",
    "Which paths are already live-validated versus still waiting on tenant-specific integrations",
    "Where human review, shadow mode, and audit evidence stop the platform from becoming glue-code chaos"
  ], 0.72, 2.35, 4.55, 2.1, 10.5);

  addCard(slide, {
    x: 0.72, y: 4.8, w: 4.8, h: 1.5,
    eyebrow: "Read this deck as",
    title: "Inbound signals -> decision engines -> governed handoffs -> durable outputs",
    body: "The diagrams are organized around operator reality, not repository folders, so a technical reviewer can track what enters the platform, how it is enriched, and what truth-changing gates it must cross."
  });

  const cards = [
    { x: 5.75, y: 1.95, w: 3.05, h: 1.2, color: PILLAR.p2, title: "Pillar 2 · Email Intelligence", body: "Mail triage, drafting, attachment routing, ingest signals", badge: "PENDING TENANT" },
    { x: 5.75, y: 3.32, w: 3.05, h: 1.2, color: PILLAR.p1, title: "Pillar 1 · AFA Engine", body: "AP intake, deterministic allocations, export artifacts", badge: "LIVE" },
    { x: 5.75, y: 4.69, w: 3.05, h: 1.2, color: PILLAR.p3, title: "Pillar 3 · Document AI", body: "Staging, classification, naming, governed updates", badge: "SHADOW" },
    { x: 9.0, y: 1.95, w: 3.05, h: 1.2, color: PILLAR.p4, title: "Pillar 4 · Expense Hub", body: "Chinese wall, claim approval, AP dispatch", badge: "LIVE" }
  ];
  cards.forEach((card) => addNode(slide, card.x, card.y, card.w, card.h, card.title, card.body, card.color, card.badge));

  addCard(slide, {
    x: 9.0, y: 3.45, w: 3.05, h: 2.42,
    eyebrow: "Legend",
    title: "Status language in this brief",
    body: "Live = exercised against deployed Azure functions\nShadow = real queue/apply path with safe no-write mode\nPending tenant = code exists but Graph, SharePoint, or Plaid still need tenant validation\nHuman review = a person still decides before company truth changes"
  });
  addBadge(slide, 9.2, 4.35, "LIVE", C.teal, C.black);
  addBadge(slide, 10.15, 4.35, "SHADOW", C.brass, C.black);
  addBadge(slide, 11.25, 4.35, "PENDING TENANT", C.blue, C.black);
  addBadge(slide, 10.08, 4.78, "HUMAN REVIEW", C.coral, C.black);

  addFooter(slide, "Purpose: let an infrastructure or software expert understand the platform shape in minutes instead of reverse-engineering it from code and anecdotes.");
  finalizeSlide(slide);
}

function slide2() {
  const slide = pptx.addSlide();
  addBackground(slide);
  addSlideHeader(
    slide,
    "System map",
    "Four pillars, shared controls, external systems",
    "This is the static architecture view: what enters the platform, where it is processed, and which shared systems govern storage, review, and durable state.",
    2
  );

  addNode(slide, 0.7, 1.9, 2.2, 1.0, "Inbound mail + attachments", "Outlook messages, attachments, mailbox events", C.blue);
  addNode(slide, 0.7, 3.1, 2.2, 1.0, "Calendar + deal signals", "Scheduling context and follow-up cues", C.blue);
  addNode(slide, 0.7, 4.3, 2.2, 1.0, "Transactions + expense claims", "Bank/card activity plus approved claims", C.coral);
  addNode(slide, 0.7, 5.5, 2.2, 1.0, "Contacts + vendor comms", "Priority context, tone, escalation signals", C.brass);

  addNode(slide, 3.45, 1.65, 2.45, 1.1, "Pillar 2 · Email Intelligence", "Triage, draft guidance, attachment routing, ingest summaries", PILLAR.p2, "P2");
  addNode(slide, 3.45, 3.15, 2.45, 1.1, "Pillar 4 · Expense Hub", "Classification engine, Chinese wall, claim approval, AP push", PILLAR.p4, "P4");
  addNode(slide, 6.2, 2.35, 2.45, 1.1, "Pillar 1 · AFA Engine", "Invoice intake, deterministic allocation, approval, ACH export", PILLAR.p1, "P1");
  addNode(slide, 8.95, 2.35, 2.45, 1.1, "Pillar 3 · Document AI", "Staging, naming, filing path, governed update queue", PILLAR.p3, "P3");

  addNode(slide, 3.3, 5.35, 2.55, 0.95, "Microsoft Graph", "Mail, calendar, tenant mailbox access", C.blue);
  addNode(slide, 6.1, 5.35, 2.55, 0.95, "SharePoint / File Storage", "Governed filing destinations and staging", C.teal);
  addNode(slide, 8.9, 5.35, 2.55, 0.95, "SQL / Durable Stores", "SQLite fallback, Azure SQL, queue state, audit data", C.brass);

  addNode(slide, 11.65, 2.0, 1.0, 1.0, "Human review", "Approvals, edits, overrides", C.coral);
  addNode(slide, 11.65, 3.25, 1.0, 1.0, "Audit + learning", "Evidence trail and correction capture", C.teal);
  addNode(slide, 11.65, 4.5, 1.0, 1.0, "Health + retries", "Operational control layer", C.brass);

  addArrow(slide, 2.9, 2.35, 3.45, 2.2, C.blue);
  addArrow(slide, 2.9, 3.55, 3.45, 2.25, C.blue);
  addArrow(slide, 2.9, 4.75, 3.45, 3.7, C.coral);
  addArrow(slide, 2.9, 5.95, 6.2, 3.1, C.brass, "priority + tone");

  addArrow(slide, 5.9, 2.2, 8.95, 2.9, C.blue, "attachments -> staging");
  addArrow(slide, 5.9, 3.7, 6.2, 3.25, C.coral, "claim -> intake");
  addArrow(slide, 8.65, 2.9, 8.95, 2.9, C.brass, "export -> docs");
  addArrow(slide, 11.4, 2.9, 11.65, 2.5, C.coral);
  addArrow(slide, 10.2, 3.45, 11.65, 3.75, C.teal);
  addArrow(slide, 10.2, 3.15, 11.65, 4.95, C.brass);

  addFooter(slide, "Solid arrows indicate intended steady-state paths. Technical nuance: Pillar 2 remains the most integration-dependent because Graph and SharePoint tenant consent determine whether its full loop is live.");
  finalizeSlide(slide);
}

function slide3() {
  const slide = pptx.addSlide();
  addBackground(slide);
  addSlideHeader(
    slide,
    "Signal and decision map",
    "Why unusual cross-signals exist without becoming random glue logic",
    "This view answers the most common technical reaction: why are mail, contacts, vendor tone, AP priority, attachments, and expenses all cross-informing each other?",
    3
  );

  addCard(slide, {
    x: 0.72, y: 1.8, w: 2.5, h: 4.95,
    eyebrow: "Signal sources",
    title: "Inputs",
    body: "Mail threads and attachments\nCalendar context\nInternal + external contacts\nVendor language and escalation tone\nBank and card transactions\nEmployee expense claims\nInvoices, schedules, and ACH artifacts"
  });

  addCard(slide, {
    x: 3.55, y: 1.8, w: 2.8, h: 4.95,
    eyebrow: "Enrichment layer",
    title: "Context builders",
    body: "Pillar 2 surfaces urgency, draftability, and attachment routing.\n\nPillar 4 resolves whether money movement belongs to the company or stays behind the Chinese wall.\n\nPillar 3 standardizes document meaning, naming, and filing readiness."
  });

  addCard(slide, {
    x: 6.65, y: 1.8, w: 2.8, h: 4.95,
    eyebrow: "Decision engines",
    title: "Operational decisions",
    body: "Pillar 1 uses queue input plus priority context to determine what gets paid now, deferred, exported, or escalated.\n\nPillar 3 decides whether extracted document facts are safe to queue, require review, or should remain staged."
  });

  addCard(slide, {
    x: 9.75, y: 1.8, w: 2.55, h: 4.95,
    eyebrow: "Outputs",
    title: "What operators actually receive",
    body: "Reply guidance\nFiling recommendations\nExpense claims routed into AP\nPayment schedules and ACH exports\nGoverned database update proposals\nAudit evidence and exception signals"
  });

  addArrow(slide, 3.22, 2.7, 3.55, 2.7, C.blue, "triages");
  addArrow(slide, 3.22, 4.25, 3.55, 4.25, C.coral, "classifies");
  addArrow(slide, 3.22, 5.8, 3.55, 5.8, C.brass, "adds context");
  addArrow(slide, 6.35, 2.7, 6.65, 2.7, C.teal, "standardizes");
  addArrow(slide, 6.35, 4.25, 6.65, 4.25, C.brass, "prioritizes");
  addArrow(slide, 6.35, 5.8, 6.65, 5.8, C.coral, "filters");
  addArrow(slide, 9.45, 2.7, 9.75, 2.7, C.blue, "surfaces");
  addArrow(slide, 9.45, 4.25, 9.75, 4.25, C.teal, "queues");
  addArrow(slide, 9.45, 5.8, 9.75, 5.8, C.brass, "exports");

  addBadge(slide, 4.15, 6.1, "ATTACHMENTS -> DOCUMENTS", C.blue, C.black);
  addBadge(slide, 4.95, 6.42, "VENDOR TONE -> AP GUIDANCE", C.brass, C.black);
  addBadge(slide, 5.1, 6.74, "CLAIMS -> AP INTAKE", C.coral, C.black);

  addFooter(slide, "The platform is intentionally cross-informed, but the signals are bounded: enrichment informs queues and operator guidance; only governed handoffs are allowed to change company state.");
  finalizeSlide(slide);
}

function slide4() {
  const slide = pptx.addSlide();
  addBackground(slide);
  addSlideHeader(
    slide,
    "Runtime flows",
    "Three cross-pillar paths explain most of the platform",
    "This is the sequence view: how live work moves, where the human enters, and which routes are already proven against deployed services.",
    4
  );

  const laneX = 0.75;
  const laneW = 11.8;
  const laneH = 1.6;
  const laneYs = [1.8, 3.55, 5.3];
  laneYs.forEach((y) => {
    slide.addShape(pptx.ShapeType.roundRect, {
      x: laneX, y, w: laneW, h: laneH,
      rectRadius: 0.06,
      line: { color: C.line, pt: 1 },
      fill: { color: "10161B", transparency: 0 }
    });
  });

  slide.addText("Mail / attachment path", { x: 0.95, y: 1.98, w: 1.5, h: 0.2, fontFace: "Aptos Display", fontSize: 15, bold: true, color: C.text, margin: 0 });
  slide.addText("Expense -> AP path", { x: 0.95, y: 3.73, w: 1.5, h: 0.2, fontFace: "Aptos Display", fontSize: 15, bold: true, color: C.text, margin: 0 });
  slide.addText("AP export -> governance path", { x: 0.95, y: 5.48, w: 2.3, h: 0.2, fontFace: "Aptos Display", fontSize: 15, bold: true, color: C.text, margin: 0 });

  const mailNodes = [
    ["Pillar 2 ingests mail", 2.7],
    ["Attachment staged", 4.45],
    ["Pillar 3 classifies", 6.15],
    ["Review if confidence low", 8.0],
    ["File or queue update", 10.1]
  ];
  mailNodes.forEach(([label, x], i) => {
    addNode(slide, x, 1.98, 1.45, 0.84, label, "", i < 2 ? PILLAR.p2 : PILLAR.p3);
  });
  addArrow(slide, 4.15, 2.38, 4.45, 2.38, C.blue);
  addArrow(slide, 5.9, 2.38, 6.15, 2.38, C.blue);
  addArrow(slide, 7.6, 2.38, 8.0, 2.38, C.teal);
  addArrow(slide, 9.45, 2.38, 10.1, 2.38, C.teal);
  addBadge(slide, 10.85, 1.95, "PENDING TENANT VALIDATION", C.blue, C.black);

  const expenseNodes = [
    ["Pillar 4 classifies txn", 2.7],
    ["Claim approved", 4.6],
    ["Dispatch to Pillar 1", 6.4],
    ["AP intake queue", 8.3],
    ["Allocation run can consume it", 10.1]
  ];
  expenseNodes.forEach(([label, x], i) => {
    const color = i < 3 ? PILLAR.p4 : PILLAR.p1;
    addNode(slide, x, 3.73, 1.55, 0.84, label, "", color);
  });
  addArrow(slide, 4.25, 4.13, 4.6, 4.13, C.coral);
  addArrow(slide, 6.15, 4.13, 6.4, 4.13, C.coral);
  addArrow(slide, 7.95, 4.13, 8.3, 4.13, C.brass);
  addArrow(slide, 9.85, 4.13, 10.1, 4.13, C.brass);
  addBadge(slide, 10.95, 3.7, "LIVE VALIDATED", C.teal, C.black);

  const exportNodes = [
    ["Allocation run", 2.7],
    ["Approve + export", 4.35],
    ["ACH + schedule artifacts", 6.1],
    ["Stage into Pillar 3", 8.05],
    ["Review -> shadow / active apply", 10.0]
  ];
  exportNodes.forEach(([label, x], i) => {
    const color = i < 3 ? PILLAR.p1 : PILLAR.p3;
    addNode(slide, x, 5.48, 1.55, 0.84, label, "", color);
  });
  addArrow(slide, 4.05, 5.88, 4.35, 5.88, C.brass);
  addArrow(slide, 5.95, 5.88, 6.1, 5.88, C.brass);
  addArrow(slide, 7.65, 5.88, 8.05, 5.88, C.brass);
  addArrow(slide, 9.6, 5.88, 10.0, 5.88, C.teal);
  addBadge(slide, 10.95, 5.45, "LIVE + SHADOW VALIDATED", C.teal, C.black);

  addFooter(slide, "Two routes are already proven against deployed services: Pillar 4 -> Pillar 1 and Pillar 1 -> Pillar 3. The mail path is structurally ready but still tenant-gated.");
  finalizeSlide(slide);
}

function slide5() {
  const slide = pptx.addSlide();
  addBackground(slide);
  addSlideHeader(
    slide,
    "Trust and control layer",
    "What keeps the platform from becoming opaque automation",
    "This is the operational-control view an infrastructure reviewer usually cares about most: retries, health, queue state, governance gates, and durable evidence.",
    5
  );

  addCard(slide, {
    x: 0.72, y: 1.8, w: 3.55, h: 4.9,
    eyebrow: "Runtime controls",
    title: "What keeps flows healthy",
    body: "Health endpoints across all pillars\nRetry logic on transient cross-pillar failures\nQueue-backed persistence instead of process memory\nService-to-service host keys and environment routing\nSmoke tests for deployed cross-pillar paths"
  });

  addCard(slide, {
    x: 4.88, y: 1.8, w: 3.55, h: 4.9,
    eyebrow: "Governance gates",
    title: "What must be true before company state changes",
    body: "Document version must be final\nPolicy checks sanitize updates\nTrust score must meet threshold\nHuman review can approve, reject, or edit payloads\nApply mode can remain shadow until cutover is intentional"
  });

  addCard(slide, {
    x: 9.05, y: 1.8, w: 3.0, h: 4.9,
    eyebrow: "Evidence layer",
    title: "What gets recorded",
    body: "Learning evidence from reviews and applies\nAudit trail of actor, decision, and timing\nBlocked duplicate re-apply proof\nOperational exceptions and degraded dependency signals"
  });

  addArrow(slide, 4.28, 3.1, 4.88, 3.1, C.brass, "feeds");
  addArrow(slide, 8.43, 3.1, 9.05, 3.1, C.teal, "records");

  addBadge(slide, 5.25, 4.75, "FINAL ONLY", C.brass, C.black);
  addBadge(slide, 6.35, 4.75, "TRUST THRESHOLD", C.blue, C.black);
  addBadge(slide, 5.6, 5.13, "HUMAN REVIEW", C.coral, C.black);
  addBadge(slide, 6.2, 5.51, "SHADOW APPLY", C.teal, C.black);

  addNode(slide, 1.0, 5.45, 2.5, 0.84, "External dependencies", "Graph, SharePoint, Azure Functions, SQL", C.blue);
  addNode(slide, 4.4, 5.45, 2.8, 0.84, "State-changing boundary", "Only governed handoffs can cross it", C.danger);
  addNode(slide, 8.15, 5.45, 3.15, 0.84, "Operator takeaway", "The platform is adaptive, but never unaccountable", C.teal);

  addFooter(slide, "The most important architectural decision is not the AI. It is the placement of the boundaries: what enriches, what queues, what requires review, and what is allowed to write durable truth.");
  finalizeSlide(slide);
}

function slide6() {
  const slide = pptx.addSlide();
  addBackground(slide);
  addSlideHeader(
    slide,
    "Current state",
    "What is already real, what is tenant-gated, and what the next workstream is",
    "This closes the brief with implementation truth so the reviewer understands the maturity profile, not just the design intent.",
    6
  );

  const cards = [
    {
      x: 0.72, y: 1.85, w: 2.85, h: 2.0, color: PILLAR.p1, title: "Pillar 1 · AFA Engine",
      body: "Deterministic allocation engine, intake queue, export flow, live Pillar 1 -> Pillar 3 validation, live Pillar 4 -> Pillar 1 intake validation.",
      badge: "LIVE"
    },
    {
      x: 3.8, y: 1.85, w: 2.85, h: 2.0, color: PILLAR.p2, title: "Pillar 2 · Email Intelligence",
      body: "Mailbox ingest and routing scaffolding exist, but Graph and SharePoint tenant consent still determine whether the full operator loop can go live.",
      badge: "PENDING TENANT"
    },
    {
      x: 6.88, y: 1.85, w: 2.85, h: 2.0, color: PILLAR.p3, title: "Pillar 3 · Document AI",
      body: "Document staging, governed updates, review flow, and shadow apply path are in place. Recent-documents route exists in source and should be deployed next.",
      badge: "SHADOW"
    },
    {
      x: 9.96, y: 1.85, w: 2.35, h: 2.0, color: PILLAR.p4, title: "Pillar 4 · Expense Hub",
      body: "Chinese wall classification and expense claim path are real. SQL/Plaid production backing remains the next major integration pass.",
      badge: "LIVE"
    }
  ];
  cards.forEach((card) => addNode(slide, card.x, card.y, card.w, card.h, card.title, card.body, card.color, card.badge));

  addCard(slide, {
    x: 0.72, y: 4.15, w: 5.6, h: 2.15,
    eyebrow: "Already demonstrated live",
    title: "The two most important cross-pillar proofs are done",
    body: "Pillar 4 -> Pillar 1: approved expense claims dispatch into the AP intake queue.\n\nPillar 1 -> Pillar 3: exported ACH and payment schedule artifacts stage into Document AI, queue governed updates, and respect shadow-apply duplicate protection."
  });
  addBadge(slide, 1.0, 5.58, "P4 -> P1 LIVE", C.teal, C.black);
  addBadge(slide, 2.2, 5.58, "P1 -> P3 LIVE", C.teal, C.black);
  addBadge(slide, 3.45, 5.58, "SHADOW APPLY VERIFIED", C.brass, C.black);

  addCard(slide, {
    x: 6.6, y: 4.15, w: 5.7, h: 2.15,
    eyebrow: "Next technical workstream",
    title: "What the reviewer should expect next",
    body: "Deploy the newer Pillar 3 queue surface for the operator UI.\n\nFinish Pillar 2 tenant validation against Graph + SharePoint.\n\nAdd real operator pages on top of the workbench so verbs like review, run, and file map to true workflows instead of raw service endpoints."
  });

  addFooter(slide, "This platform is already beyond a slideware state. The right framing for a technical reviewer is: live backend organism first, polished operator product next.");
  finalizeSlide(slide);
}

async function main() {
  slide1();
  slide2();
  slide3();
  slide4();
  slide5();
  slide6();

  await pptx.writeFile({
    fileName: "C:\\Users\\kdmcq\\Projects\\Peak10-enterprise-automation\\tools\\operator-architecture-brief\\Peak10_Operator_Architecture_Brief.pptx"
  });
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
