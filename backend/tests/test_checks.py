import re
from collections.abc import Collection
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from evals.cases import flatten
from shipgen.dataset import build_case
from shipgen.documents import build_documents
from shipgen.generator import generate_shipment
from shipgen.mutations import missing_documents
from shipgen.reference import SnapshotReference
from shipready.checks.engine import CHECKS, Result, deterministic_rules, run_checks
from shipready.checks.fields import Fields, NotVerified, first_problem
from shipready.checks.parties import financial_year
from shipready.checks.reference import DbReference
from shipready.db.models import RefExchangeRate, RefExportPolicy, RefItcHs, RefPort
from shipready.documents.models import ShipmentDocuments

DET_RULES = {rule.id for rule in deterministic_rules()}


REFERENCE = SnapshotReference()


def fields_of(documents: ShipmentDocuments, leave_out: Collection[str] = ()) -> dict[str, object]:
    fields: dict[str, object] = {}
    for name in type(documents).model_fields:
        document = getattr(documents, name)
        if document is not None and name not in leave_out:
            fields.update(flatten(document, name))
    return fields


def outcomes(results: list[Result]) -> dict[str, str]:
    return {result.rule_id: result.outcome for result in results}


def clean_fields(index: int = 0) -> dict[str, object]:
    return fields_of(build_documents(generate_shipment(42, index)))


def result_of(rule_id: str, fields: dict[str, object]) -> Result:
    return next(r for r in run_checks(fields, REFERENCE) if r.rule_id == rule_id)


@pytest.mark.parametrize("index", range(6))
def test_a_clean_shipment_passes_every_check(index: int) -> None:
    assert set(outcomes(run_checks(clean_fields(index), REFERENCE)).values()) == {"pass"}


@settings(max_examples=40, deadline=None)
@given(st.integers(min_value=0, max_value=10_000))
def test_the_checks_find_exactly_the_planted_errors(index: int) -> None:
    case = build_case(7, index)
    results = run_checks(fields_of(case.documents, missing_documents(case.labels)), REFERENCE)
    failed = {r.rule_id for r in results if r.outcome == "fail"}
    assert failed == case.rule_ids & DET_RULES


def test_every_deterministic_rule_has_a_check() -> None:
    assert set(CHECKS) == DET_RULES


def test_a_failure_cites_the_fields_it_read() -> None:
    fields = clean_fields()
    fields["shipping_bill.gstin"] = "27AAAAA0000A1Z5"
    result = result_of("ID-02", fields)
    assert result.outcome == "fail"
    assert result.evidence == ("commercial_invoice.gstin", "shipping_bill.gstin")
    assert result.message.startswith("invoice ")


def test_a_missing_value_is_not_verified_not_failed() -> None:
    fields = clean_fields()
    del fields["shipping_bill.gstin"]
    result = result_of("ID-02", fields)
    assert (result.outcome, result.message) == ("not_verified", "shipping_bill.gstin is missing")
    assert result.evidence == ("commercial_invoice.gstin",)


def test_extracted_text_reads_like_labelled_values() -> None:
    labelled = clean_fields()
    extracted = {
        path: value.isoformat() if isinstance(value, date) else str(value)
        for path, value in labelled.items()
    }
    extracted["commercial_invoice.total"] = (
        f"{Decimal(str(labelled['commercial_invoice.total'])):,}"
    )
    assert outcomes(run_checks(extracted, REFERENCE)) == outcomes(run_checks(labelled, REFERENCE))


def test_an_unreadable_line_does_not_hide_a_wrong_one() -> None:
    fields = clean_fields(1)
    assert fields.get("commercial_invoice.lines[1].quantity") is not None
    fields["commercial_invoice.lines[0].quantity"] = "about ten"
    fields["commercial_invoice.lines[1].quantity"] = Decimal(10**6)
    result = result_of("QTY-01", fields)
    assert result.outcome == "fail" and result.message.startswith("line 2:")


def test_a_different_number_of_lines_fails() -> None:
    fields = clean_fields(1)
    last = Fields(fields).count("packing_list.lines") - 1
    for path in [p for p in fields if p.startswith(f"packing_list.lines[{last}].")]:
        del fields[path]
    assert result_of("QTY-01", fields).message.startswith("commercial_invoice has")


class NoData:
    """A database without the reference tables loaded."""

    def hs_code_known(self, code: str) -> bool | None:
        return None

    def export_policy(self, code: str, on: date) -> str | None:
        return None

    def exchange_rate(self, currency: str, on: date) -> tuple[Decimal, int] | None:
        return None

    def indian_port(self, code: str) -> bool | None:
        return None


def test_without_reference_data_nothing_fails_for_lack_of_it() -> None:
    by_rule = outcomes(run_checks(clean_fields(), NoData()))
    assert {rule for rule, outcome in by_rule.items() if outcome != "pass"} == {
        "HS-01",
        "POL-01",
        "FX-01",
        "PORT-01",
    }
    assert set(by_rule.values()) == {"pass", "not_verified"}


def test_a_code_absent_from_our_schedule_is_not_verified() -> None:
    fields = clean_fields()
    for document in ("commercial_invoice", "shipping_bill", "certificate_of_origin"):
        fields[f"{document}.lines[0].hs_code"] = "99999999"
    assert outcomes(run_checks(fields, REFERENCE))["HS-01"] == "not_verified"
    fields["commercial_invoice.lines[0].hs_code"] = "999999"
    assert result_of("HS-01", fields).outcome == "fail"


def test_hs_codes_printed_with_dots_are_read() -> None:
    fields = clean_fields()
    code = str(fields["commercial_invoice.lines[0].hs_code"])
    fields["shipping_bill.lines[0].hs_code"] = f"{code[:4]}.{code[4:6]}.{code[6:]}"
    assert outcomes(run_checks(fields, REFERENCE))["HS-02"] == "pass"


def test_first_problem() -> None:
    def undecided() -> str | None:
        raise NotVerified("unknown")

    assert first_problem([lambda: None, lambda: "a", undecided, lambda: "b"]) == "a; b"
    assert first_problem([lambda: None]) is None
    with pytest.raises(NotVerified, match="unknown"):
        first_problem([lambda: None, undecided])


def test_fields_read_values_and_count_items() -> None:
    fields = Fields(
        {
            "a.lines[0].x": "1,250.50",
            "a.lines[2].x": " ",
            "a.day": "2026-10-12",
            "a.flag": True,
        }
    )
    assert fields.number("a.lines[0].x") == Decimal("1250.50")
    assert fields.optional("a.lines[2].x") is None
    assert fields.count("a.lines") == 3
    assert fields.count("b.lines") == 0
    assert fields.day("a.day") == date(2026, 10, 12)
    assert fields.flag("a.flag") is True
    with pytest.raises(NotVerified, match="not a date"):
        Fields({"d": "12/10/2026"}).day("d")


def test_financial_year() -> None:
    assert financial_year(date(2026, 3, 31)) == "2025-26"
    assert financial_year(date(2026, 4, 1)) == "2026-27"
    assert financial_year(date(2099, 12, 31)) == "2099-00"


def test_air_shipments_have_no_container_or_marks_checks() -> None:
    air = next(
        fields
        for fields in (clean_fields(i) for i in range(40))
        if any(path.startswith("air_waybill.") for path in fields)
    )
    by_rule = {r.rule_id: r for r in run_checks(air, REFERENCE)}
    for rule in ("CNT-01", "CNT-02", "CNT-03", "MRK-01", "PTY-03"):
        assert (by_rule[rule].outcome, by_rule[rule].evidence) == ("pass", ())


def test_optional_fields_are_not_mandatory() -> None:
    fields = clean_fields()
    for path in [p for p in fields if p.startswith("bill_of_lading.notify_party.")]:
        del fields[path]
    fields.pop("commercial_invoice.gst_declaration", None)
    assert result_of("DOC-02", fields).outcome == "pass"
    del fields["commercial_invoice.bank_name"]
    result = result_of("DOC-02", fields)
    assert (result.outcome, result.message) == ("fail", "missing: commercial_invoice.bank_name")
    assert result.evidence == ()  # a missing field has nothing to point to


def test_database_reference(session: Session) -> None:
    reference = DbReference(session)
    on = date(2026, 10, 20)
    # Nothing loaded: nothing can be decided.
    assert reference.hs_code_known("85044090") is None
    assert reference.indian_port("INNSA1") is None
    assert reference.exchange_rate("USD", on) is None

    session.add_all(
        [
            RefItcHs(code="8504", level=4, description="Transformers"),
            RefItcHs(code="85044090", level=8, description="Other"),
            RefItcHs(code="93011010", level=8, description="Rocket launchers"),
        ]
    )
    session.flush()  # policies refer to the codes
    session.add_all(
        [
            RefExportPolicy(code="93011010", policy="Prohibited", source="dgft"),
            RefExportPolicy(
                code="85044090",
                policy="Restricted",
                effective_from=date(2025, 1, 1),
                effective_to=date(2025, 12, 31),
                source="override",
            ),
            RefPort(code="INNSA1", name="Nhava Sheva", kind="sea", edi=True),
            RefExchangeRate(
                currency="USD",
                valid_from=date(2026, 10, 2),
                unit=1,
                rate_inr=Decimal("88.10"),
                notification="27/2026",
                published_on=date(2026, 10, 1),
            ),
            RefExchangeRate(
                currency="USD",
                valid_from=date(2026, 10, 16),
                unit=1,
                rate_inr=Decimal("88.45"),
                notification="29/2026",
                published_on=date(2026, 10, 15),
            ),
        ]
    )
    session.commit()

    assert reference.hs_code_known("85044090") is True
    assert reference.hs_code_known("85044091") is False
    assert reference.hs_code_known("8504") is False  # a heading, not a tariff item
    assert reference.export_policy("85044090", on) == "Free"  # its restriction has ended
    assert reference.export_policy("85044090", date(2025, 6, 1)) == "Restricted"
    assert reference.export_policy("93011010", on) == "Prohibited"
    assert reference.export_policy("12345678", on) is None
    assert reference.indian_port("INNSA1") is True
    assert reference.indian_port("NLRTM") is False
    assert reference.exchange_rate("USD", date(2026, 10, 10)) == (Decimal("88.10"), 1)
    assert reference.exchange_rate("USD", on) == (Decimal("88.45"), 1)
    assert reference.exchange_rate("EUR", on) is None
    # Beyond the next notification we do not hold, the rate in force is unknown.
    assert reference.exchange_rate("USD", date(2026, 11, 2)) is None


def test_a_port_country_not_printed_is_read_from_its_code() -> None:
    fields = clean_fields()
    transport = "bill_of_lading" if "bill_of_lading.bl_number" in fields else "air_waybill"
    port = "port_of_discharge" if transport == "bill_of_lading" else "airport_of_destination"
    for path in [p for p in fields if re.search(r"\.(airport|port)_of_\w+\.country$", p)]:
        del fields[path]
    by_rule = outcomes(run_checks(fields, REFERENCE))
    assert (by_rule["DST-01"], by_rule["DOC-02"]) == ("pass", "pass")
    fields[f"{transport}.{port}.code"] = "ZZZZZ"  # gives country ZZ, unlike the documents
    assert result_of("DST-01", fields).outcome == "fail"
    fields[f"{transport}.{port}.code"] = "Rotterdam"
    assert result_of("DST-01", fields).outcome == "not_verified"
