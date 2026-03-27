"""
Email triage engine.

Two-tier approach matching the Document AI pattern:
  1. Rule-based pre-triage: sender domain patterns, subject keywords,
     and known sender lists for fast, high-confidence classification.
  2. AI triage: Azure OpenAI for nuanced classification, summary
     generation, deal signal detection, and draft response creation.
"""

from __future__ import annotations

import re
from typing import Optional

from .models import (
    ActionType,
    AttachmentRouting,
    DealSignal,
    DealSignalType,
    DraftResponse,
    EmailCategory,
    EmailMessage,
    TriageResult,
    UrgencyTier,
)


# ---------------------------------------------------------------------------
# Rule-based sender domain patterns
# ---------------------------------------------------------------------------

SENDER_DOMAIN_RULES: list[tuple[str, EmailCategory, UrgencyTier]] = [
    # Regulatory
    (r"(?i)@rrc\.texas\.gov", EmailCategory.REGULATORY, UrgencyTier.CRITICAL),
    (r"(?i)@epa\.gov", EmailCategory.REGULATORY, UrgencyTier.CRITICAL),
    (r"(?i)@occ\.ok\.gov", EmailCategory.REGULATORY, UrgencyTier.HIGH),
    # Legal
    (r"(?i)@.*law(firm|office|group)", EmailCategory.LEGAL, UrgencyTier.HIGH),
    # Newsletters / marketing
    (r"(?i)@(mailchimp|constantcontact|hubspot|marketing)", EmailCategory.NEWSLETTER, UrgencyTier.NOISE),
    (r"(?i)(noreply|no-reply|donotreply)", EmailCategory.NEWSLETTER, UrgencyTier.LOW),
]


# ---------------------------------------------------------------------------
# Subject keyword patterns
# ---------------------------------------------------------------------------

SUBJECT_RULES: list[tuple[str, EmailCategory, UrgencyTier, float]] = [
    # Deals
    (r"(?i)(letter of intent|loi)\b", EmailCategory.DEAL_RELATED, UrgencyTier.HIGH, 0.88),
    (r"(?i)(purchase.*sale|psa)\b", EmailCategory.DEAL_RELATED, UrgencyTier.HIGH, 0.88),
    (r"(?i)(due diligence|title opinion)", EmailCategory.DEAL_RELATED, UrgencyTier.STANDARD, 0.85),
    (r"(?i)(acquisition|divestiture|package)", EmailCategory.DEAL_RELATED, UrgencyTier.STANDARD, 0.80),
    (r"(?i)(closing|wire instructions)", EmailCategory.DEAL_RELATED, UrgencyTier.CRITICAL, 0.90),
    # AP / Vendor
    (r"(?i)(invoice|payment|past due|overdue)", EmailCategory.VENDOR_AP, UrgencyTier.STANDARD, 0.85),
    (r"(?i)(statement of account|remittance)", EmailCategory.VENDOR_AP, UrgencyTier.LOW, 0.82),
    # Operations
    (r"(?i)(well|drilling|completion|workover)", EmailCategory.OPERATIONS, UrgencyTier.STANDARD, 0.80),
    (r"(?i)(spill|blowout|h2s|emergency|shut.?in)", EmailCategory.OPERATIONS, UrgencyTier.CRITICAL, 0.92),
    (r"(?i)(production report|run ticket|afe)", EmailCategory.OPERATIONS, UrgencyTier.STANDARD, 0.85),
    # Calendar
    (r"(?i)(meeting|meet\b|calendar|invite|rsvp|schedule|call\b|zoom|teams)", EmailCategory.CALENDAR, UrgencyTier.STANDARD, 0.80),
    # Receipts
    (r"(?i)(receipt|confirmation|booking|itinerary)", EmailCategory.RECEIPT, UrgencyTier.LOW, 0.85),
    (r"(?i)(uber|lyft|american airlines|delta|united|marriott|hilton)", EmailCategory.RECEIPT, UrgencyTier.LOW, 0.88),
]


# ---------------------------------------------------------------------------
# Deal signal keyword patterns (applied to body text)
# ---------------------------------------------------------------------------

DEAL_SIGNAL_PATTERNS: list[tuple[str, DealSignalType, float]] = [
    (r"(?i)(new package|assets? for sale|would you be interested)", DealSignalType.NEW_OPPORTUNITY, 0.80),
    (r"(?i)(loi|letter of intent|non-binding offer)", DealSignalType.LOI_DISCUSSION, 0.85),
    (r"(?i)(due diligence|data room|title review|reserve report)", DealSignalType.DUE_DILIGENCE, 0.82),
    (r"(?i)(psa|purchase and sale|definitive agreement|redline)", DealSignalType.PSA_NEGOTIATION, 0.85),
    (r"(?i)(wire instructions|closing date|settlement statement|escrow)", DealSignalType.CLOSING_ACTION, 0.90),
    (r"(?i)(transition|post.?closing|transferred|operatorship)", DealSignalType.POST_CLOSE, 0.80),
    (r"(?i)(no longer available|withdrawn|passed|not pursuing)", DealSignalType.DEAL_DEAD, 0.85),
]


# ---------------------------------------------------------------------------
# Attachment routing patterns
# ---------------------------------------------------------------------------

ATTACHMENT_ROUTING_PATTERNS: list[tuple[str, str, str, str]] = [
    # (filename_pattern, detected_type, target_pillar, target_endpoint)
    (r"(?i)invoice", "invoice", "pillar1", "/api/documents/stage"),
    (r"(?i)receipt", "receipt", "pillar4", "/api/expenses/attach-receipt"),
    (r"(?i)(contract|agreement|nda|amendment|psa|loi)", "contract", "pillar3", "/api/documents/stage"),
    (r"(?i)(afe|field.?report|run.?ticket)", "operations_doc", "pillar3", "/api/documents/stage"),
    (r"(?i)\.(pdf|docx|xlsx)$", "document", "pillar3", "/api/documents/stage"),
]


# ---------------------------------------------------------------------------
# Rule-based triage
# ---------------------------------------------------------------------------

def triage_by_rules(email: EmailMessage) -> Optional[TriageResult]:
    """Fast rule-based triage using sender, subject, and attachment patterns."""
    category: Optional[EmailCategory] = None
    urgency = UrgencyTier.STANDARD
    confidence = 0.0
    actions: list[ActionType] = []

    # Check sender domain
    for pattern, cat, urg in SENDER_DOMAIN_RULES:
        if re.search(pattern, email.sender):
            category = cat
            urgency = urg
            confidence = 0.85
            break

    # Check subject patterns (may override or augment sender match)
    best_subject_conf = 0.0
    for pattern, cat, urg, conf in SUBJECT_RULES:
        if re.search(pattern, email.subject) and conf > best_subject_conf:
            best_subject_conf = conf
            if not category or conf > confidence:
                category = cat
                urgency = urg
                confidence = conf

    if not category:
        return None

    # Determine recommended actions
    if category == EmailCategory.DEAL_RELATED:
        actions = [ActionType.FLAG_FOR_REVIEW, ActionType.REPLY]
    elif category == EmailCategory.VENDOR_AP:
        actions = [ActionType.ADD_TO_AP]
        if email.has_attachments:
            actions.append(ActionType.FILE_DOCUMENT)
    elif category == EmailCategory.RECEIPT:
        actions = [ActionType.CREATE_EXPENSE]
    elif category == EmailCategory.NEWSLETTER:
        actions = [ActionType.ARCHIVE]
    elif category == EmailCategory.SPAM:
        actions = [ActionType.DELETE]
    else:
        actions = [ActionType.FLAG_FOR_REVIEW]

    return TriageResult(
        message_id=email.message_id,
        category=category,
        urgency=urgency,
        confidence=confidence,
        recommended_actions=actions,
        reasoning=f"Rule-based: sender/subject pattern match",
    )


# ---------------------------------------------------------------------------
# Deal signal detection
# ---------------------------------------------------------------------------

def detect_deal_signals(text: str) -> list[DealSignal]:
    """Scan email body for deal-stage keywords."""
    signals: list[DealSignal] = []
    seen_types: set[DealSignalType] = set()

    for pattern, signal_type, confidence in DEAL_SIGNAL_PATTERNS:
        if signal_type in seen_types:
            continue
        match = re.search(pattern, text)
        if match:
            seen_types.add(signal_type)
            signals.append(DealSignal(
                signal_type=signal_type,
                confidence=confidence,
                evidence=match.group(0),
            ))

    return signals


# ---------------------------------------------------------------------------
# Attachment routing
# ---------------------------------------------------------------------------

def route_attachments(attachment_names: list[str]) -> list[AttachmentRouting]:
    """Determine where each attachment should be routed."""
    routings: list[AttachmentRouting] = []

    for name in attachment_names:
        for pattern, detected_type, target, endpoint in ATTACHMENT_ROUTING_PATTERNS:
            if re.search(pattern, name):
                routings.append(AttachmentRouting(
                    attachment_name=name,
                    detected_type=detected_type,
                    target_pillar=target,
                    target_endpoint=endpoint,
                    confidence=0.85,
                ))
                break  # first match wins per attachment

    return routings


# ---------------------------------------------------------------------------
# AI triage prompt builder
# ---------------------------------------------------------------------------

def build_triage_prompt(email: EmailMessage) -> str:
    """Build the prompt for Azure OpenAI email triage."""
    categories = ", ".join(c.value for c in EmailCategory)
    urgencies = "1=Critical, 2=High, 3=Standard, 4=Low, 5=Noise"
    deal_signals = ", ".join(s.value for s in DealSignalType)

    return f"""You are an executive email assistant for K. McQuire, CEO of Peak 10 Energy,
a private upstream E&P company in the Permian Basin.

Analyze this email and provide:
1. Category (one of: {categories})
2. Urgency (1-5: {urgencies})
3. A 1-2 sentence summary
4. Any deal signals detected (types: {deal_signals})
5. Recommended actions
6. A professional draft reply if appropriate

From: {email.sender_name} <{email.sender}>
Subject: {email.subject}
Date: {email.received_at.isoformat()}
Attachments: {', '.join(email.attachment_names) if email.attachment_names else 'None'}

Body:
---
{email.body_preview[:2000]}
---

Respond in JSON:
{{
  "category": "<category>",
  "urgency": <1-5>,
  "summary": "<1-2 sentences>",
  "confidence": <0.0-1.0>,
  "deal_signals": [
    {{"signal_type": "<type>", "confidence": <0.0-1.0>, "evidence": "<quote>"}}
  ],
  "recommended_actions": ["<action1>", "<action2>"],
  "draft_reply": {{
    "subject": "<reply subject>",
    "body": "<professional reply>",
    "tone": "professional"
  }},
  "reasoning": "<brief explanation>"
}}"""


def parse_ai_triage(ai_response: dict, message_id: str) -> TriageResult:
    """Parse Azure OpenAI triage response into a TriageResult."""
    try:
        category = EmailCategory(ai_response.get("category", "unknown"))
    except ValueError:
        category = EmailCategory.UNKNOWN

    try:
        urgency = UrgencyTier(ai_response.get("urgency", 3))
    except ValueError:
        urgency = UrgencyTier.STANDARD

    deal_signals = []
    for sig in ai_response.get("deal_signals", []):
        try:
            deal_signals.append(DealSignal(
                signal_type=DealSignalType(sig.get("signal_type", "new_opportunity")),
                confidence=float(sig.get("confidence", 0.0)),
                evidence=sig.get("evidence", ""),
            ))
        except (ValueError, KeyError):
            continue

    actions = []
    for a in ai_response.get("recommended_actions", []):
        try:
            actions.append(ActionType(a))
        except ValueError:
            continue

    return TriageResult(
        message_id=message_id,
        category=category,
        urgency=urgency,
        confidence=float(ai_response.get("confidence", 0.0)),
        summary=ai_response.get("summary", ""),
        deal_signals=deal_signals,
        recommended_actions=actions,
        reasoning=ai_response.get("reasoning", ""),
    )


# ---------------------------------------------------------------------------
# Unified triage pipeline
# ---------------------------------------------------------------------------

def triage_email(
    email: EmailMessage,
    ai_response: Optional[dict] = None,
) -> TriageResult:
    """
    Unified triage pipeline:
      1. Rule-based triage (sender + subject patterns)
      2. Deal signal detection on body text
      3. AI triage if provided (overrides if higher confidence)
      4. Attachment routing

    The AI call is made externally and passed in.
    """
    # Tier 1: Rules
    result = triage_by_rules(email)

    # Tier 2: Deal signals (always run on body)
    signals = detect_deal_signals(email.body_text or email.body_preview)

    # Tier 3: AI triage
    if ai_response:
        ai_result = parse_ai_triage(ai_response, email.message_id)
        if not result or ai_result.confidence > result.confidence:
            result = ai_result
        # Merge deal signals (AI may find additional ones)
        seen = {s.signal_type for s in signals}
        for s in ai_result.deal_signals:
            if s.signal_type not in seen:
                signals.append(s)

    if not result:
        result = TriageResult(
            message_id=email.message_id,
            category=EmailCategory.UNKNOWN,
            urgency=UrgencyTier.STANDARD,
            reasoning="No rules matched, no AI response provided",
        )

    # Attach deal signals
    result.deal_signals = signals

    # Determine inter-pillar routing
    routing: list[str] = []
    if email.has_attachments:
        att_routes = route_attachments(email.attachment_names)
        for r in att_routes:
            routing.append(f"{r.target_pillar}:{r.target_endpoint}")

    if result.category == EmailCategory.VENDOR_AP:
        routing.append("pillar1:/api/allocations/run")
    if result.category == EmailCategory.RECEIPT:
        routing.append("pillar4:/api/expenses/attach-receipt")

    result.routing = routing

    return result
