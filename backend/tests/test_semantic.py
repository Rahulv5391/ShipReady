from collections.abc import Callable

import pytest

from evals.cases import flatten
from shipgen.documents import build_documents
from shipgen.generator import generate_shipment
from shipgen.reference import SnapshotReference
from shipready.ai import Question, Verdict
from shipready.checks.engine import Citation, Result
from shipready.checks.semantic import plain, run_semantic_checks, semantic_rules

REFERENCE = SnapshotReference()
RULE_CITATION = Citation("cgst-rule-96a", None, "Export of goods under bond or LUT")


class ScriptedJudge:
    """Agrees unless `answer` says otherwise for a question; remembers what it was asked."""

    model = "scripted"

    def __init__(self, answer: Callable[[Question], tuple[bool, float]] | None = None) -> None:
        self.answer = answer or (lambda question: (True, 1.0))
        self.asked: list[Question] = []

    def judge(self, questions: list[Question]) -> list[Verdict]:
        self.asked += questions
        return [Verdict(q.id, *self.answer(q), "the judge's reason") for q in questions]


class Library:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def cite(self, rule_id: str) -> Citation | None:
        self.asked.append(rule_id)
        return RULE_CITATION if rule_id == "GST-01" else None


def clean_fields(index: int = 0) -> dict[str, object]:
    documents = build_documents(generate_shipment(42, index))
    fields: dict[str, object] = {}
    for name in type(documents).model_fields:
        document = getattr(documents, name)
        if document is not None:
            fields.update(flatten(document, name))
    return fields


def results(
    fields: dict[str, object], judge: ScriptedJudge | None = None, library: Library | None = None
) -> dict[str, Result]:
    found = run_semantic_checks(fields, REFERENCE, judge or ScriptedJudge(), library or Library())
    return {r.rule_id: r for r in found}


def test_the_rules_covered_are_the_enabled_judgement_rules() -> None:
    assert {r.id for r in semantic_rules()} == {
        "HS-03",
        "DESC-01",
        "PTY-01",
        "PTY-02",
        "GST-01",
        "DOC-01",
    }


def test_a_clean_shipment_passes_with_one_request() -> None:
    judge = ScriptedJudge()
    by_rule = results(clean_fields(), judge)
    assert {r.outcome for r in by_rule.values()} == {"pass"}
    # Only what code cannot settle is asked: each line's classification and the transport
    # document's summary of the goods.
    assert {q.id.split("/")[0] for q in judge.asked} == {"HS-03", "DESC-01"}


def test_a_different_number_in_an_address_fails_without_asking() -> None:
    fields = clean_fields()
    line = str(fields["packing_list.exporter.address.lines[0]"])
    fields["packing_list.exporter.address.lines[0]"] = line.replace(
        next(c for c in line if c.isdigit()), "9" if "9" not in line else "8", 1
    )
    judge = ScriptedJudge()
    result = results(fields, judge)["PTY-01"]
    assert result.outcome == "fail" and result.message.startswith("packing list gives")
    assert not [q for q in judge.asked if q.id.startswith("PTY-01")]
    assert "packing_list.exporter.address.lines[0]" in result.evidence


def test_capitals_and_a_company_suffix_are_not_differences() -> None:
    fields = clean_fields()
    name = str(fields["certificate_of_origin.exporter.name"])
    fields["certificate_of_origin.exporter.name"] = name.upper().replace(
        "PVT LTD", "PRIVATE LIMITED"
    )
    city = str(fields["purchase_order.buyer.address.city"])
    fields["purchase_order.buyer.address.city"] = city.upper()
    judge = ScriptedJudge(lambda q: (False, 1.0))  # would fail anything it were asked
    by_rule = results(fields, judge)
    assert (by_rule["PTY-01"].outcome, by_rule["PTY-02"].outcome) == ("pass", "pass")
    assert plain("Borah Impex Private Limited.") == plain("BORAH IMPEX PVT LTD")


def test_a_wording_difference_is_judged() -> None:
    fields = clean_fields()
    fields["packing_list.consignee.name"] = "Another Buyer GmbH"

    def judged(question: Question) -> tuple[bool, float]:
        return ("Another Buyer" not in question.text, 0.95)

    result = results(fields, ScriptedJudge(judged))["PTY-02"]
    assert result.outcome == "fail"
    assert result.message.endswith("(the judge's reason)")


def test_an_unsure_conflict_is_not_verified() -> None:
    fields = clean_fields()
    transport = "bill_of_lading" if "bill_of_lading.bl_number" in fields else "air_waybill"
    fields[f"{transport}.goods_description"] = "Assorted goods"
    judge = ScriptedJudge(lambda q: (not q.id.startswith("DESC-01/transport"), 0.4))
    result = results(fields, judge)["DESC-01"]
    assert result.outcome == "not_verified"
    assert result.message.startswith("possibly the ")


def test_an_implausible_classification_fails() -> None:
    fields = clean_fields()
    judge = ScriptedJudge(lambda q: (not q.id.startswith("HS-03/line-1"), 0.9))
    result = results(fields, judge)["HS-03"]
    assert result.outcome == "fail" and result.message.startswith("line 1:")
    question = next(q for q in judge.asked if q.id == "HS-03/line-1")
    assert "Code " in question.text and "Goods: " in question.text


def test_a_code_outside_our_schedule_cannot_be_judged() -> None:
    fields = clean_fields()
    fields["commercial_invoice.lines[0].hs_code"] = "99999999"
    judge = ScriptedJudge()
    result = results(fields, judge)["HS-03"]
    assert result.outcome == "not_verified" and "99999999" in result.message
    assert "HS-03/line-1" not in {q.id for q in judge.asked}


def test_a_missing_lut_statement_fails_and_cites_the_rule() -> None:
    fields = clean_fields()
    del fields["commercial_invoice.gst_declaration"]
    library = Library()
    result = results(fields, library=library)["GST-01"]
    assert (result.outcome, result.citations) == ("fail", (RULE_CITATION,))
    assert library.asked == ["GST-01"]


@pytest.mark.parametrize(
    ("statement", "asked"),
    [
        ("Supply meant for export under LUT without payment of integrated tax", False),
        ("SUPPLY MEANT FOR EXPORT ON PAYMENT OF IGST", False),
        ("Export under ARN AD270326000123X", True),
    ],
)
def test_a_lut_statement_in_other_words_is_judged(statement: str, asked: bool) -> None:
    fields = clean_fields()
    fields["commercial_invoice.gst_declaration"] = statement
    judge = ScriptedJudge()
    assert results(fields, judge)["GST-01"].outcome == "pass"
    assert any(q.id.startswith("GST-01") for q in judge.asked) is asked


def test_missing_documents_fail_and_nothing_is_guessed_about_them() -> None:
    fields = {p: v for p, v in clean_fields().items() if not p.startswith("shipping_bill.")}
    by_rule = results(fields)
    assert by_rule["DOC-01"].outcome == "fail"
    assert by_rule["DOC-01"].message == "missing: shipping bill"
    assert by_rule["DOC-01"].evidence == ()
    no_invoice = {p: v for p, v in clean_fields().items() if not p.startswith("commercial_")}
    assert results(no_invoice)["GST-01"].outcome == "not_verified"


def test_nothing_to_ask_asks_nothing() -> None:
    judge = ScriptedJudge()
    by_rule = results({}, judge)
    assert judge.asked == []
    assert by_rule["DOC-01"].outcome == "fail"
    assert {r.outcome for k, r in by_rule.items() if k != "DOC-01"} == {"not_verified"}


def test_a_to_order_bill_names_no_consignee_to_compare() -> None:
    fields = clean_fields()
    if "bill_of_lading.to_order" not in fields:
        fields = next(
            f for f in (clean_fields(i) for i in range(1, 40)) if "bill_of_lading.to_order" in f
        )
    fields["bill_of_lading.to_order"] = True
    for path in [p for p in fields if p.startswith("bill_of_lading.consignee.")]:
        del fields[path]
    fields["bill_of_lading.consignee.name"] = "TO ORDER"  # as extraction reads it
    assert results(fields)["PTY-02"].outcome == "pass"


def test_an_incomplete_party_does_not_hide_a_conflict() -> None:
    fields = clean_fields()
    del fields["certificate_of_origin.consignee.address.city"]
    assert results(fields)["PTY-02"].outcome == "not_verified"
    line = str(fields["packing_list.consignee.address.lines[0]"])
    fields["packing_list.consignee.address.lines[0]"] = line + " 77"
    assert results(fields)["PTY-02"].outcome == "fail"
