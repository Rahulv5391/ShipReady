"""The checks that need judgement (check types DEC, DET+DEC, LLM+DET): descriptions and parties
that must agree across documents, a description that must fit its HS code, the LUT statement and
the required documents.

Code decides what it can: texts equal once case, spacing and punctuation are set aside agree, a
different number in an address conflicts, a missing statement or document fails. Only the rest
goes to the judge, all of a shipment's questions in one request. A conflict the judge is less
sure of than the rule's `judge_min_confidence` is reported as not verified, never as a failure.
A failure of a rule the regulatory texts support cites the passage it relies on.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import Protocol

from sqlalchemy.orm import Session

from shipready.ai import Embedder, Judge, Question, Verdict
from shipready.checks.engine import Citation, Result
from shipready.checks.fields import (
    Fields,
    LineCountDiffers,
    NotVerified,
    line_count,
    transport_document,
)
from shipready.checks.reference import Reference
from shipready.knowledge.index import search
from shipready.knowledge.sources import load_sources
from shipready.rules.catalogue import RuleSpec, load_catalogue

DOCUMENT_NAMES = {
    "commercial_invoice": "Invoice",
    "packing_list": "Packing list",
    "purchase_order": "Purchase order",
    "shipping_bill": "Shipping bill",
    "bill_of_lading": "Bill of lading",
    "air_waybill": "Airway bill",
    "certificate_of_origin": "Certificate of origin",
    "lut": "LUT",
}
LINE_DOCUMENTS = ("commercial_invoice", "packing_list", "shipping_bill", "certificate_of_origin")
# The documents every export needs (Foreign Trade Policy 2023, paragraph 2.68): the transport
# document is either of the last two.
BASE_DOCUMENTS = ("commercial_invoice", "packing_list", "shipping_bill")
TRANSPORT_DOCUMENTS = ("bill_of_lading", "air_waybill")
# The invoice endorsement for an export without IGST, or on payment of IGST (CGST Rule 46).
_WITHOUT_IGST = re.compile(r"(letter of undertaking|\blut\b|\bbond\b).*without payment", re.I)
_WITH_IGST = re.compile(r"on payment of (integrated tax|igst)", re.I)
# What the citation search asks for each rule the regulatory texts support.
CITATION_TOPICS = {
    "GST-01": "export invoice endorsement: supply meant for export under bond or letter of "
    "undertaking without payment of integrated tax, or on payment of integrated tax",
    "DOC-01": "mandatory documents for export of goods: bill of lading or airway bill, "
    "commercial invoice cum packing list, shipping bill",
}


class Knowledge(Protocol):
    def cite(self, rule_id: str) -> Citation | None:
        """The passage of the texts that support `rule_id` it relies on; None without one."""


class DbKnowledge:
    """The indexed regulatory texts (shipready.knowledge.index), searched once per rule."""

    def __init__(self, session: Session, embedder: Embedder) -> None:
        self.session = session
        self.embedder = embedder
        self.found: dict[str, Citation | None] = {}

    def cite(self, rule_id: str) -> Citation | None:
        if rule_id not in self.found:
            sources = tuple(s.id for s in load_sources() if rule_id in s.used_by)
            hits = search(self.session, self.embedder, CITATION_TOPICS[rule_id], 1, sources)
            self.found[rule_id] = (
                Citation(hits[0][0].source_id, hits[0][0].page, hits[0][0].text) if hits else None
            )
        return self.found[rule_id]


@dataclass
class Prepared:
    """What code found, and the questions left for the judge."""

    problems: list[str] = field(default_factory=list)
    questions: list[tuple[Question, str]] = field(default_factory=list)  # with the problem
    undecided: str = ""  # why part of the rule could not be decided


Prepare = Callable[[Fields, Reference], Prepared]


def plain(text: str) -> str:
    """A text with what does not change its meaning set aside: case, punctuation, spacing, and
    the spelling of a company's suffix."""
    text = text.casefold().replace("private limited", "pvt ltd")
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def _digits(text: str) -> str:
    return "".join(re.findall(r"\d", text))


def _ask(prepared: Prepared, key: str, text: str, problem: str) -> None:
    prepared.questions.append((Question(key, text), problem))


def _descriptions(fields: Fields, reference: Reference) -> Prepared:
    prepared = Prepared()
    try:
        count = line_count(fields, *LINE_DOCUMENTS)
    except LineCountDiffers as error:
        raise NotVerified(f"lines cannot be paired: {error}") from error
    for i in range(count):
        texts = {d: fields.text(f"{d}.lines[{i}].description") for d in LINE_DOCUMENTS}
        if len({plain(t) for t in texts.values()}) > 1:
            listed = "\n".join(f"{DOCUMENT_NAMES[d]}: {t}" for d, t in texts.items())
            _ask(
                prepared,
                f"line-{i + 1}",
                f"Do these documents describe the same goods?\n{listed}",
                f"line {i + 1} is described differently: {'; '.join(texts.values())}",
            )
    transport = transport_document(fields)
    carried = fields.text(f"{transport}.goods_description")
    invoiced = [fields.text(f"commercial_invoice.lines[{i}].description") for i in range(count)]
    if plain(carried) not in {plain(text) for text in invoiced}:
        _ask(
            prepared,
            "transport",
            "Does the transport document describe the invoiced goods? It may summarise them.\n"
            f"{DOCUMENT_NAMES[transport]}: {carried}\nInvoice lines: {'; '.join(invoiced)}",
            f"the {DOCUMENT_NAMES[transport].lower()} describes {carried!r}",
        )
    return prepared


def _party(fields: Fields, prefix: str) -> str | None:
    """A party as one line of text: name, address lines, city, country; None when absent."""
    name = fields.optional(f"{prefix}.name")
    if name is None:
        return None
    lines = [
        fields.text(f"{prefix}.address.lines[{i}]")
        for i in range(fields.count(f"{prefix}.address.lines"))
    ]
    parts = [
        name,
        *lines,
        fields.text(f"{prefix}.address.city"),
        fields.text(f"{prefix}.address.country"),
    ]
    return ", ".join(parts)


def _parties_agree(
    fields: Fields, parties: dict[str, str], names: dict[str, str], role: str
) -> Prepared:
    """Each party (document -> field prefix) and name (document -> field) against the
    invoice's: numbers in an address must be equal; other differences go to the judge."""
    prepared = Prepared()
    reference = _party(fields, parties["commercial_invoice"])
    if reference is None:
        raise NotVerified(f"the invoice's {role} was not found")
    for document, prefix in parties.items():
        try:
            other = _party(fields, prefix) if document != "commercial_invoice" else None
        except NotVerified as error:
            prepared.undecided = str(error)  # this party only; the others are still compared
            continue
        if other is None or plain(other) == plain(reference):
            continue
        if _digits(other) != _digits(reference):
            prepared.problems.append(
                f"{DOCUMENT_NAMES[document].lower()} gives {other}; the invoice {reference}"
            )
            continue
        _ask(
            prepared,
            document,
            "Is this the same party and address?\n"
            f"Invoice: {reference}\n{DOCUMENT_NAMES[document]}: {other}",
            f"{DOCUMENT_NAMES[document].lower()} gives {other}; the invoice {reference}",
        )
    invoice_name = fields.text(f"{parties['commercial_invoice']}.name")
    for document, path in names.items():
        name = fields.optional(path)
        if name is None or plain(name) == plain(invoice_name):
            continue
        _ask(
            prepared,
            f"{document}-name",
            f"Is this the same {role}?\n"
            f"Invoice: {invoice_name}\n{DOCUMENT_NAMES[document]}: {name}",
            f"{DOCUMENT_NAMES[document].lower()} names {name!r}; the invoice {invoice_name!r}",
        )
    return prepared


def _exporter(fields: Fields, reference: Reference) -> Prepared:
    parties = {
        "commercial_invoice": "commercial_invoice.exporter",
        "packing_list": "packing_list.exporter",
        "purchase_order": "purchase_order.seller",
        "certificate_of_origin": "certificate_of_origin.exporter",
    }
    transport = transport_document(fields)
    parties[transport] = f"{transport}.shipper"
    names = {"shipping_bill": "shipping_bill.exporter_name", "lut": "lut.legal_name"}
    return _parties_agree(fields, parties, names, "exporter")


def _consignee(fields: Fields, reference: Reference) -> Prepared:
    parties = {
        "commercial_invoice": "commercial_invoice.consignee",
        "packing_list": "packing_list.consignee",
        "purchase_order": "purchase_order.buyer",
        "certificate_of_origin": "certificate_of_origin.consignee",
    }
    transport = transport_document(fields)
    # A bill of lading made out "to order" names no consignee.
    to_order = (fields.optional("bill_of_lading.to_order") or "").casefold() == "true"
    if not (transport == "bill_of_lading" and to_order):
        parties[transport] = f"{transport}.consignee"
    prepared = _parties_agree(
        fields, parties, {"shipping_bill": "shipping_bill.consignee_name"}, "consignee"
    )
    country = fields.optional("shipping_bill.consignee_country")
    invoice_country = fields.text("commercial_invoice.consignee.address.country")
    if country is not None and country.upper() != invoice_country.upper():
        prepared.problems.append(
            f"shipping bill gives the consignee's country as {country}; "
            f"the invoice {invoice_country}"
        )
    return prepared


def _classification(fields: Fields, reference: Reference) -> Prepared:
    prepared = Prepared()
    count = fields.count("commercial_invoice.lines")
    if count == 0:
        raise NotVerified("no invoice lines found")
    for i in range(count):
        description = fields.text(f"commercial_invoice.lines[{i}].description")
        code = re.sub(r"[\s.]", "", fields.text(f"commercial_invoice.lines[{i}].hs_code"))
        covers = reference.hs_description(code)
        if covers is None:
            prepared.undecided = f"{code} is not in our copy of the ITC(HS) schedule"
            continue
        _ask(
            prepared,
            f"line-{i + 1}",
            "Can these goods be classified under this ITC(HS) code?\n"
            f"Goods: {description}\nCode {code}: {covers}",
            f"line {i + 1}: {description!r} does not fit {code} ({covers})",
        )
    return prepared


def _lut_statement(fields: Fields, reference: Reference) -> Prepared:
    if not fields.has("commercial_invoice"):
        raise NotVerified("no invoice was found")  # DOC-01 reports it
    prepared = Prepared()
    statement = fields.optional("commercial_invoice.gst_declaration")
    if statement is None:
        prepared.problems.append("the invoice states neither export under LUT nor payment of IGST")
    elif not (_WITHOUT_IGST.search(statement) or _WITH_IGST.search(statement)):
        _ask(
            prepared,
            "statement",
            "Does this invoice statement declare export under a bond or letter of undertaking "
            f"without payment of IGST, or export on payment of IGST?\nStatement: {statement}",
            f"the invoice's statement {statement!r} declares neither",
        )
    return prepared


def _required_documents(fields: Fields, reference: Reference) -> Prepared:
    missing = [DOCUMENT_NAMES[d].lower() for d in BASE_DOCUMENTS if not fields.has(d)]
    if not any(fields.has(d) for d in TRANSPORT_DOCUMENTS):
        missing.append("bill of lading or airway bill")
    return Prepared(problems=[f"missing: {', '.join(missing)}"] if missing else [])


PREPARE: dict[str, Prepare] = {
    "DESC-01": _descriptions,
    "PTY-01": _exporter,
    "PTY-02": _consignee,
    "HS-03": _classification,
    "GST-01": _lut_statement,
    "DOC-01": _required_documents,
}


@cache
def semantic_rules() -> tuple[RuleSpec, ...]:
    """The enabled rules that are not decided by code alone; each must be prepared here."""
    rules = tuple(rule for rule in load_catalogue() if rule.enabled and rule.check_type != "DET")
    unchecked = [rule.id for rule in rules if rule.id not in PREPARE]
    if unchecked:
        raise RuntimeError(f"no check for catalogue rules {unchecked}")
    return rules


def run_semantic_checks(
    values: Mapping[str, object], reference: Reference, judge: Judge, knowledge: Knowledge
) -> list[Result]:
    prepared: dict[str, tuple[Prepared | NotVerified, Fields]] = {}
    for rule in semantic_rules():
        fields = Fields(values)
        try:
            prepared[rule.id] = (PREPARE[rule.id](fields, reference), fields)
        except NotVerified as error:
            prepared[rule.id] = (error, fields)
    questions = [
        Question(f"{rule_id}/{question.id}", question.text)
        for rule_id, (found, _) in prepared.items()
        if isinstance(found, Prepared)
        for question, _ in found.questions
    ]
    verdicts = {v.id: v for v in judge.judge(questions)} if questions else {}
    return [_conclude(rule, *prepared[rule.id], verdicts, knowledge) for rule in semantic_rules()]


def _conclude(
    rule: RuleSpec,
    found: Prepared | NotVerified,
    fields: Fields,
    verdicts: dict[str, Verdict],
    knowledge: Knowledge,
) -> Result:
    evidence = tuple(dict.fromkeys(p for p in fields.read if fields.present(p)))
    if isinstance(found, NotVerified):
        return Result(rule.id, "not_verified", str(found), evidence)
    problems, unsure = list(found.problems), [found.undecided] if found.undecided else []
    threshold = float(rule.params.get("judge_min_confidence", 1))
    for question, problem in found.questions:
        verdict = verdicts[f"{rule.id}/{question.id}"]
        if verdict.agrees:
            continue
        if verdict.confidence >= threshold:
            problems.append(f"{problem} ({verdict.reason})")
        else:
            unsure.append(f"possibly {problem} ({verdict.reason})")
    if problems:
        citation = knowledge.cite(rule.id) if rule.id in CITATION_TOPICS else None
        return Result(
            rule.id, "fail", "; ".join(problems), evidence, (citation,) if citation else ()
        )
    if unsure:
        return Result(rule.id, "not_verified", "; ".join(unsure), evidence)
    return Result(rule.id, "pass", "", evidence)
