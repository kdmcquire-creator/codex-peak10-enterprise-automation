"""Smoke-test deployed Peak10 pillar integrations.

This script is intentionally dependency-free so it can run anywhere the repo
can run Python. It supports:

- safe health-only checks across any configured pillars
- a live Pillar 1 -> Pillar 3 allocation/export flow
- a live Pillar 4 -> Pillar 1 payload handoff validation flow
- a live Pillar 2 mailbox-ingest trigger once tenant Graph settings are ready
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class EndpointConfig:
    label: str
    base_url: str
    function_key: str

    def url_for(self, route: str) -> str:
        route = route.lstrip("/")
        query = urllib.parse.urlencode({"code": self.function_key})
        return f"{self.base_url.rstrip('/')}/{route}?{query}"


def _load_optional(arg_value: str | None, env_name: str) -> str:
    value = (arg_value or "").strip()
    if value:
        return value
    return (os.environ.get(env_name) or "").strip()


def _load_required_endpoint(
    *,
    label: str,
    url_arg: str | None,
    key_arg: str | None,
    url_env: str,
    key_env: str,
) -> EndpointConfig:
    base_url = _load_optional(url_arg, url_env)
    function_key = _load_optional(key_arg, key_env)
    if not base_url:
        raise SystemExit(f"Missing required value for {url_env}")
    if not function_key:
        raise SystemExit(f"Missing required value for {key_env}")
    return EndpointConfig(label=label, base_url=base_url, function_key=function_key)


def _load_optional_endpoint(
    *,
    label: str,
    url_arg: str | None,
    key_arg: str | None,
    url_env: str,
    key_env: str,
) -> EndpointConfig | None:
    base_url = _load_optional(url_arg, url_env)
    function_key = _load_optional(key_arg, key_env)
    if not base_url:
        return None
    if not function_key:
        raise SystemExit(f"Missing required value for {key_env}")
    return EndpointConfig(label=label, base_url=base_url, function_key=function_key)


def _request_json(
    *,
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {exc.code} calling {url}: {details or exc.reason}"
        ) from exc

    if not payload:
        return {}
    return json.loads(payload)


def run_health_checks(endpoints: list[EndpointConfig]) -> dict[str, Any]:
    if not endpoints:
        raise SystemExit("At least one pillar endpoint must be configured for health mode.")
    return {
        f"{endpoint.label}_health": _request_json(
            method="GET",
            url=endpoint.url_for("api/health"),
        )
        for endpoint in endpoints
    }


def run_pillar1_pillar3_flow(
    pillar1: EndpointConfig,
    pillar3: EndpointConfig,
    *,
    review_and_apply: bool,
) -> dict[str, Any]:
    invoice_id = f"smoke-inv-{uuid.uuid4().hex[:8]}"
    vendor_id = f"smoke-v-{uuid.uuid4().hex[:8]}"
    run_body = {
        "budget": {
            "total_budget": "1000.00",
            "reserved_amount": "100.00",
        },
        "invoices": [
            {
                "invoice_id": invoice_id,
                "vendor_id": vendor_id,
                "vendor_name": "Smoke Test Vendor",
                "vendor_priority": 2,
                "amount_due": "500.00",
                "due_date": "2026-04-15",
                "description": "Automated smoke test invoice",
                "status": "pending",
                "source": "smoke-test",
            }
        ],
    }
    run_response = _request_json(
        method="POST",
        url=pillar1.url_for("api/allocations/run"),
        body=run_body,
    )
    run_id = run_response["allocation"]["run_id"]

    approve_response = _request_json(
        method="POST",
        url=pillar1.url_for("api/allocations/approve"),
        body={"run_id": run_id},
    )

    export_response = _request_json(
        method="POST",
        url=pillar1.url_for("api/allocations/export"),
        body={
            "run_id": run_id,
            "vendors": [
                {
                    "vendor_id": vendor_id,
                    "name": "Smoke Test Vendor",
                    "priority": 2,
                    "ach_routing_number": "111000025",
                    "ach_account_number": "1234567890",
                }
            ],
        },
    )

    updates_response = _request_json(
        method="GET",
        url=pillar3.url_for("api/database-updates"),
    )

    matching_updates = [
        update
        for update in updates_response.get("database_updates", [])
        if update.get("effective_field_updates", {}).get("run_id") == run_id
    ]

    result: dict[str, Any] = {
        "run": run_response,
        "approve": approve_response,
        "export": export_response,
        "matching_database_updates": matching_updates,
    }

    if review_and_apply and matching_updates:
        update_id = matching_updates[0]["update_id"]
        review_response = _request_json(
            method="POST",
            url=pillar3.url_for("api/database-updates/review"),
            body={
                "update_id": update_id,
                "decision": "approve",
                "reviewed_by": "smoke-test",
                "review_notes": "Automated cross-pillar smoke test",
            },
        )
        apply_response = _request_json(
            method="POST",
            url=pillar3.url_for("api/database-updates/apply"),
            body={
                "update_id": update_id,
                "applied_by": "smoke-test",
            },
        )
        result["review"] = review_response
        result["apply"] = apply_response

    return result


def run_pillar4_pillar1_payload_flow(
    pillar4: EndpointConfig,
    pillar1: EndpointConfig | None,
) -> dict[str, Any]:
    classify_response = _request_json(
        method="POST",
        url=pillar4.url_for("api/transactions/classify"),
        body={
            "transactions": [
                {
                    "merchant_name": "Uber",
                    "amount": "35.00",
                    "date": "2026-03-29",
                    "category": ["Travel"],
                }
            ]
        },
    )
    transaction = classify_response["classified"][0]
    transaction_id = transaction["transaction_id"]

    claim_response = _request_json(
        method="POST",
        url=pillar4.url_for("api/expenses/claim"),
        body={
            "transaction_id": transaction_id,
            "employee_name": "Smoke Test User",
            "description": "Automated smoke test expense claim",
        },
    )
    claim_id = claim_response["claim"]["claim_id"]

    approve_response = _request_json(
        method="POST",
        url=pillar4.url_for("api/expenses/approve"),
        body={"claim_id": claim_id},
    )

    push_response = _request_json(
        method="POST",
        url=pillar4.url_for("api/expenses/push-to-ap"),
        body={"claim_id": claim_id},
    )

    result = {
        "classify": classify_response,
        "claim": claim_response,
        "approve": approve_response,
        "push_to_ap": push_response,
    }
    if pillar1 is not None and push_response.get("dispatch", {}).get("dispatched"):
        intake_list = _request_json(
            method="GET",
            url=pillar1.url_for("api/invoices/intake"),
        )
        matching = [
            invoice
            for invoice in intake_list.get("invoices", [])
            if invoice.get("invoice_id") == claim_id
        ]
        result["pillar1_intake_queue_matches"] = matching
    return result


def run_pillar2_mailbox_ingest(
    pillar2: EndpointConfig,
    *,
    top: int,
    mark_processed: bool,
) -> dict[str, Any]:
    ingest_response = _request_json(
        method="POST",
        url=pillar2.url_for("api/mailbox/ingest"),
        body={
            "top": top,
            "mark_processed": mark_processed,
        },
        timeout_seconds=90.0,
    )
    return {"mailbox_ingest": ingest_response}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("health", "pillar1-pillar3", "pillar2-mailbox-ingest", "pillar4-pillar1"),
        default="health",
        help="Safe health checks or a targeted live pillar integration flow.",
    )
    parser.add_argument("--pillar1-url")
    parser.add_argument("--pillar1-key")
    parser.add_argument("--pillar2-url")
    parser.add_argument("--pillar2-key")
    parser.add_argument("--pillar3-url")
    parser.add_argument("--pillar3-key")
    parser.add_argument("--pillar4-url")
    parser.add_argument("--pillar4-key")
    parser.add_argument(
        "--review-and-apply",
        action="store_true",
        help="For pillar1-pillar3 mode, also approve and apply the first matching Pillar 3 database update.",
    )
    parser.add_argument(
        "--mailbox-top",
        type=int,
        default=1,
        help="For pillar2-mailbox-ingest mode, number of unread messages to request.",
    )
    parser.add_argument(
        "--mark-processed",
        action="store_true",
        help="For pillar2-mailbox-ingest mode, ask Pillar 2 to mark processed messages as read/handled.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    pillar1_optional = _load_optional_endpoint(
        label="pillar1",
        url_arg=args.pillar1_url,
        key_arg=args.pillar1_key,
        url_env="PEAK10_PILLAR1_URL",
        key_env="PEAK10_PILLAR1_KEY",
    )
    pillar2_optional = _load_optional_endpoint(
        label="pillar2",
        url_arg=args.pillar2_url,
        key_arg=args.pillar2_key,
        url_env="PEAK10_PILLAR2_URL",
        key_env="PEAK10_PILLAR2_KEY",
    )
    pillar3_optional = _load_optional_endpoint(
        label="pillar3",
        url_arg=args.pillar3_url,
        key_arg=args.pillar3_key,
        url_env="PEAK10_PILLAR3_URL",
        key_env="PEAK10_PILLAR3_KEY",
    )
    pillar4_optional = _load_optional_endpoint(
        label="pillar4",
        url_arg=args.pillar4_url,
        key_arg=args.pillar4_key,
        url_env="PEAK10_PILLAR4_URL",
        key_env="PEAK10_PILLAR4_KEY",
    )

    if args.mode == "health":
        output = run_health_checks(
            [
                endpoint
                for endpoint in (
                    pillar1_optional,
                    pillar2_optional,
                    pillar3_optional,
                    pillar4_optional,
                )
                if endpoint is not None
            ]
        )
    elif args.mode == "pillar1-pillar3":
        pillar1 = pillar1_optional or _load_required_endpoint(
            label="pillar1",
            url_arg=args.pillar1_url,
            key_arg=args.pillar1_key,
            url_env="PEAK10_PILLAR1_URL",
            key_env="PEAK10_PILLAR1_KEY",
        )
        pillar3 = pillar3_optional or _load_required_endpoint(
            label="pillar3",
            url_arg=args.pillar3_url,
            key_arg=args.pillar3_key,
            url_env="PEAK10_PILLAR3_URL",
            key_env="PEAK10_PILLAR3_KEY",
        )
        output = run_health_checks([pillar1, pillar3])
        output["pillar1_pillar3"] = run_pillar1_pillar3_flow(
            pillar1,
            pillar3,
            review_and_apply=args.review_and_apply,
        )
    elif args.mode == "pillar2-mailbox-ingest":
        pillar2 = pillar2_optional or _load_required_endpoint(
            label="pillar2",
            url_arg=args.pillar2_url,
            key_arg=args.pillar2_key,
            url_env="PEAK10_PILLAR2_URL",
            key_env="PEAK10_PILLAR2_KEY",
        )
        output = run_health_checks([pillar2])
        output["pillar2_mailbox_ingest"] = run_pillar2_mailbox_ingest(
            pillar2,
            top=args.mailbox_top,
            mark_processed=args.mark_processed,
        )
    else:
        pillar4 = pillar4_optional or _load_required_endpoint(
            label="pillar4",
            url_arg=args.pillar4_url,
            key_arg=args.pillar4_key,
            url_env="PEAK10_PILLAR4_URL",
            key_env="PEAK10_PILLAR4_KEY",
        )
        endpoints = [pillar4]
        if pillar1_optional is not None:
            endpoints.append(pillar1_optional)
        output = run_health_checks(endpoints)
        output["pillar4_pillar1"] = run_pillar4_pillar1_payload_flow(pillar4, pillar1_optional)

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
