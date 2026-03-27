"""
Tests for the document classification engine.

Covers:
  - Filename-based classification for all major document types
  - Content-based keyword classification
  - AI response parsing
  - Unified pipeline (filename + content boosting, AI fallback)
  - Edge cases: unknown files, empty inputs
"""

from __future__ import annotations

import pytest

from document_ai.classifier import (
    classify_by_content,
    classify_by_filename,
    classify_document,
    infer_document_version_state,
    parse_ai_classification,
)
from document_ai.models import (
    ClassificationConfidence,
    DocumentType,
)


# ---------------------------------------------------------------------------
# Filename classification
# ---------------------------------------------------------------------------

class TestFilenameClassification:
    @pytest.mark.parametrize("filename,expected_type", [
        ("Invoice_Halliburton_2026-03.pdf", DocumentType.INVOICE),
        ("payment_schedule_march_2026.xlsx", DocumentType.PAYMENT_SCHEDULE),
        ("ACH_Export_Run123.txt", DocumentType.ACH_EXPORT),
        ("Uber_Receipt_20260314.pdf", DocumentType.RECEIPT),
        ("expense_report_Q1_2026.pdf", DocumentType.EXPENSE_REPORT),
        ("W-9_AcmeServices.pdf", DocumentType.TAX_FORM),
        ("1099_2025.pdf", DocumentType.TAX_FORM),
        ("MSA_Contract_DrillCo.pdf", DocumentType.CONTRACT),
        ("Amendment_3_DrillCo_MSA.pdf", DocumentType.AMENDMENT),
        ("NDA_AcmeResources.pdf", DocumentType.NDA),
        ("Non_Disclosure_Agreement_Peak10.pdf", DocumentType.NDA),
        ("Insurance_Policy_Cert_2026.pdf", DocumentType.INSURANCE_POLICY),
        ("Daily_Report_Well7_20260314.pdf", DocumentType.FIELD_REPORT),
        ("Field_Report_March14.pdf", DocumentType.FIELD_REPORT),
        ("AFE_2026-042_Well_Recompletion.pdf", DocumentType.AFE),
        ("Run_Ticket_WT_20260314.pdf", DocumentType.RUN_TICKET),
        ("Decline_Curve_Analysis_Well7.pdf", DocumentType.DECLINE_CURVE),
        ("RRC_Filing_P4_2026.pdf", DocumentType.REGULATORY_FILING),
        ("Safety_Report_Incident_20260310.pdf", DocumentType.SAFETY_REPORT),
        ("JSA_Workover_Rig5.pdf", DocumentType.SAFETY_REPORT),
        ("LOI_AcmeResources_LovinCounty.pdf", DocumentType.LOI),
        ("Letter_of_Intent_Peak10_2026.pdf", DocumentType.LOI),
        ("PSA_AcmeResources.pdf", DocumentType.PSA),
        ("Purchase_Sale_Agreement_Block42.pdf", DocumentType.PSA),
        ("Title_Opinion_LovinCounty.pdf", DocumentType.TITLE_OPINION),
        ("Due_Diligence_Checklist_AcmeBlock.pdf", DocumentType.DUE_DILIGENCE),
        ("Board_Minutes_20260301.pdf", DocumentType.BOARD_MINUTES),
        ("Meeting_Minutes_Board_Q1.pdf", DocumentType.BOARD_MINUTES),
        ("Operating_Agreement_Peak10_LLC.pdf", DocumentType.OPERATING_AGREEMENT),
        ("Resolution_2026-03_Dividend.pdf", DocumentType.RESOLUTION),
        ("Audit_Report_FY2025.pdf", DocumentType.AUDIT_REPORT),
    ])
    def test_known_filenames(self, filename: str, expected_type: DocumentType):
        result = classify_by_filename(filename)
        assert result is not None
        assert result.document_type == expected_type
        assert result.confidence >= 0.85

    def test_unknown_filename_returns_none(self):
        result = classify_by_filename("random_document_xyz.pdf")
        assert result is None


# ---------------------------------------------------------------------------
# Content classification
# ---------------------------------------------------------------------------

class TestContentClassification:
    def test_invoice_content(self):
        text = "Invoice Number: INV-2026-0412\nTotal Due: $15,000.00"
        result = classify_by_content(text)
        assert result is not None
        assert result.document_type == DocumentType.INVOICE

    def test_afe_content(self):
        text = "Authorization for Expenditure\nWell: Peak 10 #7\nEstimated Cost: $450,000"
        result = classify_by_content(text)
        assert result is not None
        assert result.document_type == DocumentType.AFE

    def test_psa_content(self):
        text = "This Purchase and Sale Agreement is entered into between..."
        result = classify_by_content(text)
        assert result is not None
        assert result.document_type == DocumentType.PSA

    def test_no_match_returns_none(self):
        result = classify_by_content("Hello world, nothing here.")
        assert result is None


# ---------------------------------------------------------------------------
# AI response parsing
# ---------------------------------------------------------------------------

class TestAIResponseParsing:
    def test_valid_response(self):
        ai_resp = {
            "document_type": "contract",
            "confidence": 0.92,
            "reasoning": "MSA with drill contractor",
            "metadata": {
                "vendor_name": "DrillCo Services",
                "counterparty": "Peak 10 Energy",
                "effective_date": "2026-01-01",
                "amount": "$250,000",
            }
        }
        result = parse_ai_classification(ai_resp)
        assert result.document_type == DocumentType.CONTRACT
        assert result.confidence == 0.92
        assert result.metadata.vendor_name == "DrillCo Services"

    def test_unknown_type_fallback(self):
        result = parse_ai_classification({"document_type": "alien_document"})
        assert result.document_type == DocumentType.UNKNOWN

    def test_empty_response(self):
        result = parse_ai_classification({})
        assert result.document_type == DocumentType.UNKNOWN
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Unified pipeline
# ---------------------------------------------------------------------------

class TestUnifiedPipeline:
    def test_high_confidence_filename_wins(self):
        result = classify_document(
            filename="ACH_Export_Run123.txt",
            content_text="some random text",
        )
        assert result.document_type == DocumentType.ACH_EXPORT
        assert result.confidence >= 0.90

    def test_content_overrides_filename_when_types_conflict(self):
        result = classify_document(
            filename="Invoice_123.pdf",
            content_text="This Purchase and Sale Agreement is entered into by the parties",
        )
        assert result.document_type == DocumentType.PSA
        assert result.reasoning.startswith("Content matched pattern")

    def test_content_boosts_filename(self):
        result = classify_document(
            filename="invoice_misc.pdf",
            content_text="Invoice Number: 12345\nTotal Due: $500",
        )
        assert result.document_type == DocumentType.INVOICE
        # Should be boosted above either individual score
        assert result.confidence >= 0.88

    def test_ai_fallback_for_unknown_filename(self):
        ai_resp = {
            "document_type": "title_opinion",
            "confidence": 0.88,
            "reasoning": "Legal title analysis document",
            "metadata": {"county": "Loving"},
        }
        result = classify_document(
            filename="doc_12345.pdf",
            ai_response=ai_resp,
        )
        assert result.document_type == DocumentType.TITLE_OPINION
        assert result.confidence == 0.88

    def test_completely_unknown(self):
        result = classify_document(filename="asdf.bin")
        assert result.document_type == DocumentType.UNKNOWN
        assert result.confidence == 0.0

    def test_ai_overrides_low_confidence_rules(self):
        ai_resp = {
            "document_type": "nda",
            "confidence": 0.95,
            "reasoning": "Clearly an NDA",
            "metadata": {},
        }
        result = classify_document(
            filename="document.pdf",
            content_text="random text",
            ai_response=ai_resp,
        )
        assert result.document_type == DocumentType.NDA
        assert result.confidence == 0.95


class TestVersionInference:
    def test_detects_final_version_from_filename(self):
        status, signal = infer_document_version_state("MSA_DrillCo_Executed.pdf")
        assert status == "final"
        assert signal

    def test_detects_wip_version_from_filename(self):
        status, signal = infer_document_version_state("MSA_DrillCo_v03.docx")
        assert status == "wip"
        assert signal

    def test_detects_unknown_version_when_no_markers(self):
        status, signal = infer_document_version_state("MSA_DrillCo.docx")
        assert status == "unknown"
        assert signal == ""
