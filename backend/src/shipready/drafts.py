"""Who is asked to fix what: each failed check goes to the party that issued the document it
found wrong, and the drafter words one message per party (Decision.md D-33).

The commercial invoice is the exporter's own master document, so when it disagrees with
another document, the other document's issuer is asked to correct it. A problem only on the
exporter's own documents (invoice, packing list, LUT), or with nothing to point to (a missing
document), goes to the exporter's team.
"""

from collections import defaultdict
from collections.abc import Iterable
from functools import cache

from shipready.ai import Problem
from shipready.checks.engine import Result
from shipready.rules.catalogue import load_catalogue

ISSUER = {
    "commercial_invoice": "exporter",
    "packing_list": "exporter",
    "lut": "exporter",
    "bill_of_lading": "forwarder",
    "air_waybill": "forwarder",
    "shipping_bill": "customs_broker",
    "purchase_order": "buyer",
    "certificate_of_origin": "certifier",
}


@cache
def _titles() -> dict[str, str]:
    return {rule.id: rule.title for rule in load_catalogue()}


def recipients(result: Result) -> set[str]:
    """The parties asked to fix `result`: the issuers of the documents it read, other than the
    exporter's own, or the exporter's team when there are none."""
    issuers = {ISSUER[path.split(".")[0]] for path in result.evidence}
    return issuers - {"exporter"} or {"exporter"}


def requests(results: Iterable[Result]) -> dict[str, list[Problem]]:
    """Each party's problems to ask about, from the checks that failed (a check not verified
    is for a person to look at, not to ask about)."""
    asked: dict[str, list[Problem]] = defaultdict(list)
    for result in results:
        if result.outcome != "fail":
            continue
        for recipient in sorted(recipients(result)):
            asked[recipient].append(
                Problem(result.rule_id, _titles()[result.rule_id], result.message)
            )
    return dict(asked)
