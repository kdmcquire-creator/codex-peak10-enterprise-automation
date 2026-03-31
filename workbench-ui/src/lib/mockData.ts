import type { WorkbenchData } from "./types";

export const mockWorkbenchData: WorkbenchData = {
  generatedAt: "Updated 14 seconds ago",
  headline: "Peak 10 Operating Workbench",
  subheadline:
    "One governed surface for queue work, filing confidence, AP execution, and human approvals across the automation pillars.",
  heroStats: [
    { label: "Priority items", value: "14", tone: "attention" },
    { label: "Documents staged", value: "27", tone: "active" },
    { label: "Pending approvals", value: "6", tone: "critical" },
    { label: "Cross-pillar flows", value: "2 live", tone: "stable" }
  ],
  sidebar: [
    {
      id: "inbox",
      label: "Inbox",
      shortLabel: "Mail",
      queueCount: 9,
      tone: "attention",
      summary: "Unread triage, reply drafting, mailbox ingest health"
    },
    {
      id: "documents",
      label: "Documents",
      shortLabel: "Docs",
      queueCount: 27,
      tone: "active",
      summary: "Staging, naming, low-confidence review, filing path"
    },
    {
      id: "ap",
      label: "AP",
      shortLabel: "AP",
      queueCount: 11,
      tone: "active",
      summary: "Allocation runs, expense intake, exports, settlement drift"
    },
    {
      id: "approvals",
      label: "Approvals",
      shortLabel: "Gov",
      queueCount: 6,
      tone: "critical",
      summary: "Database update review, exception handling, audit decisions"
    }
  ],
  details: {
    inbox: {
      id: "inbox",
      headline: "Mailbox triage with governance visible upfront",
      narrative:
        "Operators start where work arrives. Priority mail, draft confidence, attachment routing, and tenant ingest warnings stay in one glanceable lane.",
      queueLabel: "Needs operator review",
      queueValue: "9 threads",
      queueTone: "attention",
      primaryAction: "Review urgent thread",
      secondaryAction: "Run mailbox ingest",
      sections: [
        {
          eyebrow: "Morning brief",
          title: "Unread mail with filing risk surfaced",
          description:
            "Message triage stays dense and utility-first so the inbox feels like a control room, not a CRM.",
          items: [
            { label: "Legal notice", value: "Needs reply", meta: "2 attachments, no destination match", tone: "critical" },
            { label: "Vendor remittance", value: "Auto-drafted", meta: "Draft confidence 0.91", tone: "stable" },
            { label: "Bank alert", value: "Operator only", meta: "Sensitive account language detected", tone: "attention" }
          ]
        },
        {
          eyebrow: "Ingest summary",
          title: "Mailbox polling or webhook ingest can land here later",
          description:
            "The shell is already shaped to accept real Graph summaries once tenant validation is complete.",
          items: [
            { label: "Messages processed", value: "42", meta: "Last 30 minutes", tone: "stable" },
            { label: "Warnings", value: "3", meta: "Attachment parse degraded", tone: "attention" },
            { label: "Uploads staged", value: "7", meta: "00_STAGING/Inbox", tone: "active" }
          ]
        }
      ]
    },
    documents: {
      id: "documents",
      headline: "Document queues treated like active production traffic",
      narrative:
        "Classification, naming, and governed filing should feel tactile and decisive. This view prioritizes what is waiting, what is uncertain, and what is safe to file now.",
      queueLabel: "Ready to file",
      queueValue: "18 documents",
      queueTone: "active",
      primaryAction: "Open staging queue",
      secondaryAction: "Review low-confidence items",
      sections: [
        {
          eyebrow: "Staging lane",
          title: "One glance on confidence and destination",
          description:
            "Documents are grouped by filing readiness rather than file type so action stays obvious.",
          items: [
            { label: "ACH export", value: "Final", meta: "Finance/AP, trust 0.94", tone: "stable" },
            { label: "Lease addendum", value: "Hold", meta: "Missing governed path", tone: "attention" },
            { label: "Insurance cert", value: "Review", meta: "Classification drift detected", tone: "critical" }
          ]
        },
        {
          eyebrow: "Learning",
          title: "Corrections become reusable evidence",
          description:
            "Human review is presented as durable system training, not janitorial clean-up.",
          items: [
            { label: "Corrections logged", value: "12", meta: "Past 7 days", tone: "active" },
            { label: "Pending database updates", value: "6", meta: "2 ready for apply", tone: "attention" },
            { label: "Shadow applies", value: "4", meta: "No duplicate applies", tone: "stable" }
          ]
        }
      ]
    },
    ap: {
      id: "ap",
      headline: "AP operations with live handoffs in view",
      narrative:
        "This workspace ties deterministic allocations, expense intake, ACH export, and downstream filing into one sequence so operators can trust the state of money movement.",
      queueLabel: "Allocation + intake queue",
      queueValue: "11 items",
      queueTone: "active",
      primaryAction: "Start allocation run",
      secondaryAction: "Inspect expense intake",
      sections: [
        {
          eyebrow: "Allocation engine",
          title: "Budget and payment flow at working resolution",
          description:
            "Operators can see what is approved, exported, deferred, and still waiting without digging into separate systems.",
          items: [
            { label: "Approved runs", value: "3", meta: "Latest export 14 min ago", tone: "stable" },
            { label: "Deferred invoices", value: "2", meta: "Budget shortfall flagged", tone: "attention" },
            { label: "Expense claims queued", value: "1", meta: "Pillar 4 handoff live", tone: "active" }
          ]
        },
        {
          eyebrow: "Settlement artifacts",
          title: "Exports and downstream filing remain visible",
          description:
            "The shell leaves room for final ACH artifacts, payment schedules, and filing proofs to sit beside the queue they came from.",
          items: [
            { label: "ACH exports", value: "2", meta: "Standardized and staged", tone: "stable" },
            { label: "Payment schedules", value: "2", meta: "Queued into Pillar 3", tone: "active" },
            { label: "Exceptions", value: "1", meta: "Bank detail mismatch", tone: "critical" }
          ]
        }
      ]
    },
    approvals: {
      id: "approvals",
      headline: "Governed actions should feel deliberate, not hidden",
      narrative:
        "Approvals are where the company learns and where risk gets contained. This view emphasizes audit quality, shadow mode visibility, and what needs a human decision now.",
      queueLabel: "Approval queue",
      queueValue: "6 decisions",
      queueTone: "critical",
      primaryAction: "Review update batch",
      secondaryAction: "Open audit trail",
      sections: [
        {
          eyebrow: "Database updates",
          title: "What is pending, what is shadow-applied, what is blocked",
          description:
            "This should become the calmest but sharpest space in the product because mistakes here change company truth.",
          items: [
            { label: "Pending approval", value: "2", meta: "Finance/AP", tone: "attention" },
            { label: "Shadow applied", value: "3", meta: "Safe no-write proof", tone: "stable" },
            { label: "Blocked reapply", value: "1", meta: "Duplicate apply prevented", tone: "critical" }
          ]
        },
        {
          eyebrow: "Audit signal",
          title: "Operational trust stays visible",
          description:
            "Actor, decision, and confidence are presented as first-order information rather than buried metadata.",
          items: [
            { label: "Average trust score", value: "0.94", meta: "Last 10 reviews", tone: "stable" },
            { label: "Manual edits", value: "4 fields", meta: "Past week", tone: "attention" },
            { label: "Escalations", value: "1", meta: "Low-confidence filing path", tone: "critical" }
          ]
        }
      ]
    }
  },
  pillars: [
    { id: "pillar1", name: "Pillar 1 · AFA Engine", status: "healthy", latencyMs: 184, summary: "Allocation + intake endpoints live" },
    { id: "pillar2", name: "Pillar 2 · Email Intelligence", status: "degraded", latencyMs: 312, summary: "Tenant ingest pending Graph validation" },
    { id: "pillar3", name: "Pillar 3 · Document AI", status: "healthy", latencyMs: 201, summary: "Staging, shadow apply, filing queues" },
    { id: "pillar4", name: "Pillar 4 · Expense Hub", status: "healthy", latencyMs: 166, summary: "Expense -> AP dispatch live" }
  ],
  approvals: [
    { id: "DB-5521", type: "Payment schedule upsert", source: "Pillar 1 -> Pillar 3", status: "shadow applied", owner: "Finance Ops", updatedAt: "3 min ago" },
    { id: "DB-5522", type: "ACH export upsert", source: "Pillar 1 -> Pillar 3", status: "pending", owner: "Controller", updatedAt: "8 min ago" },
    { id: "DB-5526", type: "Insurance metadata update", source: "Pillar 2 -> Pillar 3", status: "needs review", owner: "Records", updatedAt: "16 min ago" }
  ],
  timeline: [
    { time: "07:42", title: "Expense claim dispatched into AP intake", detail: "Pillar 4 pushed Uber claim to Pillar 1 live queue.", tone: "active" },
    { time: "07:36", title: "Payment schedule shadow applied", detail: "Duplicate re-apply guard confirmed on finance_ap_schedule.", tone: "stable" },
    { time: "07:15", title: "Mailbox ingest warning recorded", detail: "Attachment parse failed on one vendor email, queue continued.", tone: "attention" },
    { time: "06:58", title: "SharePoint route unresolved", detail: "Lease addendum staged to 00_STAGING/Inbox.", tone: "critical" }
  ]
};
