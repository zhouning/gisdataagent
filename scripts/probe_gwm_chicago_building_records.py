#!/usr/bin/env python3
"""Probe bounded permit histories from Chicago's official building records app."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
from html.parser import HTMLParser
import http.cookiejar
import json
from pathlib import Path
import ssl
import time
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = (
    ROOT
    / "benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel/evidence"
)
DEFAULT_CROSSWALK_INPUT = EVIDENCE_DIR / "historical_cohort_spatial_crosswalk.json"
DEFAULT_OUTPUT = EVIDENCE_DIR / "chicago_building_records_2024_cohort.json"
DEFAULT_RAW_DIR = EVIDENCE_DIR / "chicago_building_records_2024_cohort_html"
BASE_URL = "https://webapps1.chicago.gov/buildingrecords"
PERMIT_COLUMNS = ("PERMIT #", "DATE ISSUED", "DESCRIPTION OF WORK")


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    content_type: str
    server_date: str | None
    body: bytes


class FormAndTableParser(HTMLParser):
    """Extract hidden form values and flat HTML tables without dependencies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: dict[str, str] = {}
        self.title_parts: list[str] = []
        self._in_title = False
        self.tables: dict[str, dict[str, list[Any]]] = {}
        self._table_id: str | None = None
        self._row: list[tuple[str, str]] | None = None
        self._cell_tag: str | None = None
        self._cell_parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "input" and attributes.get("name"):
            self.inputs[attributes["name"]] = attributes.get("value", "")
        elif tag == "table":
            table_id = attributes.get("id")
            if table_id:
                self._table_id = table_id
                self.tables.setdefault(table_id, {"headers": [], "rows": []})
        elif self._table_id and tag == "tr":
            self._row = []
        elif self._table_id and self._row is not None and tag in {"th", "td"}:
            self._cell_tag = tag
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif (
            self._table_id
            and self._row is not None
            and self._cell_tag == tag
            and tag in {"th", "td"}
        ):
            self._row.append((tag, _normalize_text(" ".join(self._cell_parts))))
            self._cell_tag = None
            self._cell_parts = []
        elif self._table_id and tag == "tr" and self._row is not None:
            table = self.tables[self._table_id]
            values = [value for _, value in self._row]
            if values and all(cell_tag == "th" for cell_tag, _ in self._row):
                if not table["headers"]:
                    table["headers"] = values
            elif values and any(cell_tag == "td" for cell_tag, _ in self._row):
                table["rows"].append(values)
            self._row = None
        elif self._table_id and tag == "table":
            self._table_id = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._cell_tag:
            self._cell_parts.append(data)

    @property
    def title(self) -> str:
        return _normalize_text(" ".join(self.title_parts))


class BuildingRecordsClient:
    def __init__(self, *, timeout_seconds: float) -> None:
        cookie_jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(cookie_jar))
        self.timeout_seconds = timeout_seconds
        self.csrf_token: str | None = None

    def accept_public_access_agreement(self) -> tuple[Response, Response]:
        agreement = self._request("/")
        parser = _parse_html(agreement.body)
        csrf_token = parser.inputs.get("_csrf")
        if not csrf_token:
            raise RuntimeError("agreement_csrf_token_missing")
        home = self._request(
            "/agreement",
            data={"agreement": "Y", "_csrf": csrf_token},
            referer=f"{BASE_URL}/",
        )
        home_parser = _parse_html(home.body)
        self.csrf_token = home_parser.inputs.get("_csrf")
        if not self.csrf_token:
            raise RuntimeError("search_csrf_token_missing")
        return agreement, home

    def search_address(self, address: str) -> tuple[Response, Response]:
        if not self.csrf_token:
            raise RuntimeError("agreement_not_accepted")
        validation = self._request(
            "/validateaddress",
            data={"fullAddress": address, "_csrf": self.csrf_token},
            referer=f"{BASE_URL}/home",
        )
        parser = _parse_html(validation.body)
        form_fields = {
            field: parser.inputs.get(field, "")
            for field in (
                "streetNumber",
                "streetDirection",
                "streetName",
                "streetType",
                "fullAddress",
            )
        }
        csrf_token = parser.inputs.get("_csrf") or self.csrf_token
        if not all(form_fields.values()):
            raise RuntimeError("validated_address_components_missing")
        result = self._request(
            "/doSearch",
            data={**form_fields, "_csrf": csrf_token},
            referer=f"{BASE_URL}/validateaddress",
        )
        return validation, result

    def _request(
        self,
        path: str,
        *,
        data: Mapping[str, str] | None = None,
        referer: str | None = None,
    ) -> Response:
        body = urlencode(data).encode("utf-8") if data is not None else None
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; GWM bounded data probe)",
            "Accept": "text/html,application/xhtml+xml",
        }
        if referer:
            headers["Referer"] = referer
        for attempt in range(3):
            request = Request(f"{BASE_URL}{path}", data=body, headers=headers)
            try:
                with self.opener.open(
                    request, timeout=self.timeout_seconds
                ) as response:
                    return Response(
                        url=response.geturl(),
                        status=response.status,
                        content_type=response.headers.get_content_type(),
                        server_date=response.headers.get("Date"),
                        body=response.read(),
                    )
            except HTTPError as error:
                if error.code < 500 or attempt == 2:
                    raise
            except (URLError, TimeoutError, ConnectionError, ssl.SSLError):
                if attempt == 2:
                    raise
            time.sleep(1.0 * (2**attempt))
        raise RuntimeError("unreachable_request_retry_state")


def probe_building_records(
    *,
    crosswalk_path: Path = DEFAULT_CROSSWALK_INPUT,
    output_path: Path = DEFAULT_OUTPUT,
    raw_dir: Path = DEFAULT_RAW_DIR,
    timeout_seconds: float = 60.0,
    delay_seconds: float = 0.25,
    limit: int | None = None,
    observed_on: str | None = None,
) -> dict[str, Any]:
    """Query only preregistered events with a joint official spatial crosswalk."""

    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    events = crosswalk.get("events")
    events = events if isinstance(events, list) else []
    eligible = [
        event
        for event in events
        if isinstance(event, Mapping)
        and isinstance(event.get("spatial_consistency"), Mapping)
        and event["spatial_consistency"].get("ready") is True
    ]
    eligible.sort(key=lambda event: str(event.get("record_number") or ""))
    if limit is not None:
        eligible = eligible[:limit]
    if not eligible:
        raise ValueError("no_joint_spatial_crosswalk_events")

    raw_dir.mkdir(parents=True, exist_ok=True)
    client = BuildingRecordsClient(timeout_seconds=timeout_seconds)
    agreement, home = client.accept_public_access_agreement()
    agreement_path = raw_dir / "agreement.html"
    agreement_path.write_bytes(agreement.body)

    observations: list[dict[str, Any]] = []
    for index, event in enumerate(eligible):
        if index and delay_seconds > 0:
            time.sleep(delay_seconds)
        record_number = str(event.get("record_number") or "")
        address = str(event.get("address") or "")
        validation, result = client.search_address(address)
        result_path = raw_dir / f"{record_number.replace('-', '_')}.html"
        result_path.write_bytes(result.body)
        observations.append(
            _build_observation(
                event=event,
                validation=validation,
                result=result,
                result_path=result_path,
            )
        )

    schema_pass_count = sum(
        observation["validation"]["current_permit_schema_verified"]
        for observation in observations
    )
    exact_address_count = sum(
        observation["validation"]["exact_input_address_returned"]
        for observation in observations
    )
    permit_row_count = sum(
        observation["permit_summary"]["permit_count"]
        for observation in observations
    )
    nonempty_history_count = sum(
        observation["permit_summary"]["permit_count"] > 0
        for observation in observations
    )
    zero_permit_history_count = len(observations) - nonempty_history_count
    post_publication_row_count = sum(
        observation["permit_summary"]["post_publication_permit_count"]
        for observation in observations
    )
    result = {
        "schema": "gwm.chicago_building_records_bounded_cohort_probe.v1",
        "observed_on": observed_on or date.today().isoformat(),
        "source": {
            "publisher": "City of Chicago Department of Buildings",
            "canonical_url": f"{BASE_URL}/",
            "access_mode": "public_html_application_after_user_agreement",
            "access_boundary": "interactive_selection_required",
            "agreement_http_status": agreement.status,
            "agreement_content_type": agreement.content_type,
            "agreement_server_date": agreement.server_date,
            "home_http_status": home.status,
            "current_permit_columns": list(PERMIT_COLUMNS),
            "source_disclaimer": (
                "A permit issue does not confirm that work was performed or that "
                "the work complied with the permit or Municipal Code."
            ),
        },
        "selection": {
            "cohort_id": crosswalk.get("cohort_id"),
            "cohort_digest": crosswalk.get("cohort_digest"),
            "spatial_crosswalk_digest": crosswalk.get("crosswalk_digest"),
            "rule": "spatial_consistency.ready == true",
            "eligible_event_count": sum(
                isinstance(event, Mapping)
                and isinstance(event.get("spatial_consistency"), Mapping)
                and event["spatial_consistency"].get("ready") is True
                for event in events
            ),
            "queried_event_count": len(observations),
            "limit": limit,
        },
        "summary": {
            "successful_http_result_count": sum(
                observation["result_http_status"] == 200
                for observation in observations
            ),
            "exact_input_address_count": exact_address_count,
            "current_permit_schema_verified_count": schema_pass_count,
            "address_history_with_permits_count": sum(
                observation["permit_summary"]["permit_count"] > 0
                for observation in observations
            ),
            "zero_permit_address_history_count": zero_permit_history_count,
            "permit_row_count": permit_row_count,
            "post_publication_permit_row_count": post_publication_row_count,
            "address_history_with_post_publication_permits_count": sum(
                observation["permit_summary"]["post_publication_permit_count"]
                > 0
                for observation in observations
            ),
        },
        "observations": observations,
        "artifacts": {
            "agreement": _artifact(agreement_path),
            "crosswalk": _artifact(crosswalk_path),
            **{
                str(observation["record_number"]): observation["raw_artifact"]
                for observation in observations
            },
        },
        "readiness": {
            "official_current_address_level_schema_verified": (
                nonempty_history_count > 0
                and schema_pass_count == nonempty_history_count
            ),
            "official_bounded_address_level_rows_verified": (
                exact_address_count == len(observations) and permit_row_count > 0
            ),
            "official_zero_permit_address_results_verified": (
                zero_permit_history_count > 0
                and all(
                    observation["result_http_status"] == 200
                    and observation["validation"]["exact_input_address_returned"]
                    for observation in observations
                    if observation["permit_summary"]["permit_count"] == 0
                )
            ),
            "full_cohort_address_history_probe_complete": (
                limit is None and len(observations) == len(eligible)
            ),
            "tract_month_outcome_panel_ready": False,
            "untreated_control_outcomes_ready": False,
            "causal_estimation_ready": False,
        },
        "claim_boundary": {
            "address_history_not_complete_tract_outcome": True,
            "treated_addresses_not_untreated_controls": True,
            "permit_issue_not_construction_start": True,
            "permit_issue_not_work_completion": True,
            "candidate_publication_date_not_verified_effective_onset": True,
            "bounded_html_probe_not_bulk_socrata_export": True,
            "bounded_outcome_rows_not_causal_identification": True,
        },
    }
    result["probe_digest"] = _canonical_digest(result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _build_observation(
    *,
    event: Mapping[str, Any],
    validation: Response,
    result: Response,
    result_path: Path,
) -> dict[str, Any]:
    validation_parser = _parse_html(validation.body)
    parser = _parse_html(result.body)
    permit_table = parser.tables.get("resultstable_permits", {})
    headers = permit_table.get("headers")
    headers = headers if isinstance(headers, list) else []
    raw_rows = permit_table.get("rows")
    raw_rows = raw_rows if isinstance(raw_rows, list) else []
    permits = []
    for row in raw_rows:
        if not isinstance(row, list) or len(row) != 3:
            continue
        issued_on = _parse_issued_date(str(row[1]))
        permits.append(
            {
                "permit_number": str(row[0]),
                "issued_on": issued_on,
                "description_of_work": str(row[2]),
            }
        )
    publication = str(event.get("last_publication_date") or "")[:10]
    post_publication = [
        permit
        for permit in permits
        if permit["issued_on"] and publication and permit["issued_on"] > publication
    ]
    normalized_requested_address = _normalize_address(
        str(event.get("address") or "")
    )
    normalized_validated_address = _normalize_address(
        validation_parser.inputs.get("fullAddress", "")
    )
    result_text = _normalize_text(result.body.decode("utf-8", errors="replace"))
    exact_result_address = normalized_requested_address in _normalize_address(
        result_text
    )
    return {
        "record_number": event.get("record_number"),
        "requested_address": event.get("address"),
        "validated_address": validation_parser.inputs.get("fullAddress"),
        "tract_geoid": (
            event.get("tract_crosswalk", {}).get("tract_geoid")
            if isinstance(event.get("tract_crosswalk"), Mapping)
            else None
        ),
        "candidate_publication_date": publication or None,
        "validation_http_status": validation.status,
        "result_http_status": result.status,
        "result_content_type": result.content_type,
        "result_server_date": result.server_date,
        "page_title": parser.title,
        "permit_columns": headers,
        "permits": permits,
        "permit_summary": {
            "permit_count": len(permits),
            "post_publication_permit_count": len(post_publication),
            "post_publication_permit_numbers": [
                permit["permit_number"] for permit in post_publication
            ],
        },
        "raw_artifact": _artifact(result_path),
        "validation": {
            "validation_http_200": validation.status == 200,
            "result_http_200": result.status == 200,
            "official_html_content_type": result.content_type == "text/html",
            "official_page_title": parser.title
            == "Building Permit and Inspection Records",
            "exact_validated_address": (
                normalized_requested_address == normalized_validated_address
            ),
            "exact_input_address_returned": exact_result_address,
            "current_permit_schema_verified": tuple(headers) == PERMIT_COLUMNS,
            "permit_rows_have_stable_id_and_date": all(
                permit["permit_number"]
                and permit["permit_number"].replace("-", "").isalnum()
                and permit["issued_on"] is not None
                for permit in permits
            ),
            "source_disclaimer_present": (
                "the fact that a permit was issued does not confirm that work was performed"
                in result_text.lower()
            ),
        },
    }


def _parse_html(payload: bytes) -> FormAndTableParser:
    parser = FormAndTableParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    parser.close()
    return parser


def _parse_issued_date(value: str) -> str | None:
    tokens = _normalize_text(value).split()
    for token in reversed(tokens):
        try:
            return datetime.strptime(token, "%m/%d/%Y").date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _normalize_address(value: str) -> str:
    return " ".join(value.upper().replace(",", " ").split())


def _artifact(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    try:
        artifact_path = path.relative_to(ROOT)
    except ValueError:
        artifact_path = path
    return {
        "path": str(artifact_path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--observed-on")
    args = parser.parse_args()
    result = probe_building_records(
        crosswalk_path=args.crosswalk,
        output_path=args.output,
        raw_dir=args.raw_dir,
        timeout_seconds=args.timeout_seconds,
        delay_seconds=args.delay_seconds,
        limit=args.limit,
        observed_on=args.observed_on,
    )
    print(json.dumps(result["summary"], sort_keys=True))
    print(result["probe_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
