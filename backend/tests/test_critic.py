import io

from PIL import Image

from shipready.ai import Review, Suspect
from shipready.checks.critic import MIN_CONFIDENCE, crop_png, review
from shipready.checks.engine import Result

GSTIN_FAILURE = Result(
    "ID-01",
    "fail",
    "lut GSTIN 09CDOFS2603T126 is not valid",
    ("commercial_invoice.iec", "lut.gstin"),
)


class Pages:
    """Evidence with a page image for the fields named, and none for the others."""

    def __init__(self, *imaged: str) -> None:
        self.imaged = imaged

    def read(self, path: str) -> tuple[str, str] | None:
        return ("09CDOFS2603T126", "09CDOFS2603T1Z6") if path == "lut.gstin" else ("X", "X")

    def crop(self, path: str) -> bytes | None:
        return b"png" if path in self.imaged else None


class ScriptedCritic:
    model = "scripted"

    def __init__(self, real: bool, confidence: float = 0.95) -> None:
        self.real, self.confidence = real, confidence
        self.seen: list[Suspect] = []

    def review(self, suspects: list[Suspect]) -> list[Review]:
        self.seen += suspects
        return [Review(s.id, self.real, self.confidence, "the image shows 1Z6") for s in suspects]


def test_a_misreading_is_set_aside_as_not_verified() -> None:
    critic = ScriptedCritic(real=False)
    (result,) = review([GSTIN_FAILURE], Pages("lut.gstin"), critic)
    assert (result.outcome, result.verification) == ("not_verified", "misread")
    assert result.message.startswith("likely misread, check by eye: lut GSTIN")
    assert result.critic_reason == "the image shows 1Z6"
    (suspect,) = critic.seen
    assert suspect.check == "Exporter identifiers valid"
    assert [c.path for c in suspect.crops] == ["lut.gstin"]
    assert ("lut.gstin", "09CDOFS2603T126", "09CDOFS2603T1Z6") in suspect.fields


def test_a_real_problem_is_kept() -> None:
    (result,) = review([GSTIN_FAILURE], Pages("lut.gstin"), ScriptedCritic(real=True))
    assert (result.outcome, result.verification) == ("fail", "kept")


def test_an_unsure_critic_keeps_the_failure() -> None:
    critic = ScriptedCritic(real=False, confidence=MIN_CONFIDENCE - 0.1)
    (result,) = review([GSTIN_FAILURE], Pages("lut.gstin"), critic)
    assert (result.outcome, result.verification) == ("fail", "kept")


def test_only_failed_blocker_and_major_checks_with_images_are_reviewed() -> None:
    results = [
        GSTIN_FAILURE,
        Result("UQC-01", "fail", "units differ", ("lut.gstin",)),  # minor
        Result("ID-02", "pass", "", ("lut.gstin",)),
        Result("DOC-01", "fail", "missing: shipping bill", ()),  # nothing to look at
        Result("INV-01", "fail", "numbers differ", ("commercial_invoice.iec",)),  # no image
    ]
    critic = ScriptedCritic(real=False)
    reviewed = review(results, Pages("lut.gstin"), critic)
    assert [s.id for s in critic.seen] == ["ID-01"]
    assert [r.outcome for r in reviewed] == ["not_verified", "fail", "pass", "fail", "fail"]


def test_nothing_to_review_asks_nothing() -> None:
    critic = ScriptedCritic(real=False)
    results = [Result("ID-02", "pass", "", ())]
    assert review(results, Pages(), critic) == results
    assert critic.seen == []


def test_a_crop_shows_the_field_with_its_line() -> None:
    page = Image.new("RGB", (1000, 1400), "white")
    png = crop_png(page, (0.4, 0.5, 0.5, 0.51))
    crop = Image.open(io.BytesIO(png))
    assert crop.format == "PNG"
    assert crop.size == (600, 70)  # 0.25 of the width each side, 0.02 of the height
    edge = crop_png(page, (0.9, 0.0, 1.0, 0.01))
    assert Image.open(io.BytesIO(edge)).size == (350, 42)  # clamped to the page
