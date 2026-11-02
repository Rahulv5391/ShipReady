"""The critic: a second look at each failed blocker or major check, against the page images of
the fields it read (PLAN.md Phase 15).

Most false alarms come from reading, not from the rules: OCR turns a GSTIN's "1Z6" into "126",
and a check then fails on a value the document does not show. The critic sees the values as read
and a crop of the page around each, and says whether the problem is on the documents. A failure
it finds to be a misreading, with enough confidence, becomes "not verified": the true value is
still unknown, so a person looks, but the shipment is not held for an error it does not have.
A failure with nothing to look at (a missing document or field) is kept as it is.
"""

import io
from dataclasses import replace
from functools import cache
from typing import Protocol

from PIL import Image

from shipready.ai import Critic, Crop, Suspect
from shipready.checks.engine import Result
from shipready.rules.catalogue import load_catalogue

REVIEWED_SEVERITIES = ("blocker", "major")
# How sure the critic must be that a failure is a misreading before it is set aside.
MIN_CONFIDENCE = 0.8
# Around a field's box: the rest of its line, and a line above and below, so the critic sees
# the label and the value together.
MARGIN_X, MARGIN_Y = 0.25, 0.02
MAX_CROP_PX = 1200


class Evidence(Protocol):
    def read(self, path: str) -> tuple[str, str] | None:
        """The field's value and quote as extracted; None when it was not."""

    def crop(self, path: str) -> bytes | None:
        """A PNG of the page around the field; None without a page image or a box."""


@cache
def _titles() -> dict[str, tuple[str, str]]:
    return {rule.id: (rule.title, rule.severity) for rule in load_catalogue()}


def crop_png(page: Image.Image, box: tuple[float, float, float, float]) -> bytes:
    """The part of `page` around `box` (fractions of the page from the top left), as PNG."""
    x0, y0, x1, y1 = box
    width, height = page.size
    area = (
        int(max(0.0, x0 - MARGIN_X) * width),
        int(max(0.0, y0 - MARGIN_Y) * height),
        int(min(1.0, x1 + MARGIN_X) * width),
        int(min(1.0, y1 + MARGIN_Y) * height),
    )
    piece = page.crop(area)
    piece.thumbnail((MAX_CROP_PX, MAX_CROP_PX))
    buffer = io.BytesIO()
    piece.save(buffer, format="PNG")
    return buffer.getvalue()


def review(results: list[Result], evidence: Evidence, critic: Critic) -> list[Result]:
    """`results` with each failed blocker or major check reviewed by the critic: kept, or set
    aside as not verified when it is a misreading. One request for the whole shipment."""
    suspects = {}
    for result in results:
        title, severity = _titles()[result.rule_id]
        if result.outcome != "fail" or severity not in REVIEWED_SEVERITIES:
            continue
        crops = tuple(
            Crop(path, png) for path in result.evidence if (png := evidence.crop(path)) is not None
        )
        if not crops:
            continue
        fields = tuple(
            (path, *read) for path in result.evidence if (read := evidence.read(path)) is not None
        )
        suspects[result.rule_id] = Suspect(result.rule_id, title, result.message, fields, crops)
    if not suspects:
        return results
    reviews = {r.id: r for r in critic.review(list(suspects.values()))}
    reviewed = []
    for result in results:
        found = reviews.get(result.rule_id)
        if found is None:
            reviewed.append(result)
        elif found.real or found.confidence < MIN_CONFIDENCE:
            reviewed.append(replace(result, verification="kept", critic_reason=found.reason))
        else:
            reviewed.append(
                replace(
                    result,
                    outcome="not_verified",
                    message=f"likely misread, check by eye: {result.message}",
                    verification="misread",
                    critic_reason=found.reason,
                )
            )
    return reviewed
