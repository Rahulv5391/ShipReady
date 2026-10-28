import json
import shutil
import zipfile
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session

from shipready.db import load as load_module
from shipready.db import seed as seed_module
from shipready.db.load import LOADERS, LoadReport
from shipready.db.models import (
    RefCountry,
    RefCurrency,
    RefExchangeRate,
    RefExportPolicy,
    RefItcHs,
    RefLocation,
    RefPort,
    RefUqc,
    Rule,
)
from shipready.db.rows import replace, upsert
from shipready.db.seed import seed
from shipready.db.session import database_url
from shipready.reference.fetch import FILES

SEED_COUNTS = {"rules": 39, "ref_uqc": 45, "ref_countries": 249, "organizations": 1}
LOAD_COUNTS = {
    "ref_itc_hs": 31,
    "ref_export_policy": 11,  # 5 from DGFT's lists + 6 sugar override periods
    "ref_ports": 9,
    "ref_currencies": 9,
    "ref_exchange_rates": 6,
    "ref_locations": 2,
}


def count(session: Session, model: type[DeclarativeBase]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
def downloads(tmp_path: Path, reference_dir: Path) -> Path:
    """A download directory: the fixture excerpts plus a two-location UN/LOCODE release."""
    directory = tmp_path / "reference"
    shutil.copytree(reference_dir, directory)
    with zipfile.ZipFile(directory / FILES["unlocode"], "w") as archive:
        archive.writestr(
            "release/csv/CodeListPart1.csv",
            ",IN,NSA,Nhava Sheva,Nhava Sheva,MH,1-------,AA,,,,\n"
            ",NL,RTM,Rotterdam,Rotterdam,ZH,12345---,AF,,,,\n"
            ",XZ,ABC,At sea,At sea,,1-------,RL,,,,\n",
        )
    return directory


def load_all(session: Session, directory: Path) -> LoadReport:
    report = LoadReport()
    for loader in LOADERS.values():
        loader(session, directory, report)
    return report


# --- seed -------------------------------------------------------------------------------------


def test_seed_loads_the_packaged_data(session: Session) -> None:
    assert seed(session) == SEED_COUNTS
    session.commit()

    weight = session.get_one(Rule, "WT-01")
    assert weight.params == {"gross_weight_tolerance_pct": 0.5}
    assert session.get_one(Rule, "POL-02").enabled is False
    assert session.get_one(RefUqc, "KGS").description == "KILOGRAMS"
    assert session.get_one(RefCountry, "IN").name == "India"


def test_seed_is_idempotent_and_restores_edited_rows(session: Session) -> None:
    seed(session)
    session.commit()
    session.execute(text("UPDATE rules SET severity = 'info' WHERE id = 'QTY-01'"))
    session.commit()

    assert seed(session) == SEED_COUNTS
    session.commit()
    session.expire_all()
    assert session.get_one(Rule, "QTY-01").severity == "blocker"
    assert count(session, Rule) == 39


def test_main_seeds_the_database_from_database_url(
    session: Session,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    seed_module.main()
    assert capsys.readouterr().out.splitlines() == [
        f"{table}: {rows} rows" for table, rows in SEED_COUNTS.items()
    ]
    assert count(session, RefCountry) == 249


def test_database_url_must_be_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        database_url()


# --- writing rows -----------------------------------------------------------------------------


def test_writes_reject_an_empty_source(session: Session) -> None:
    with pytest.raises(ValueError, match="no rows for ref_uqc"):
        upsert(session, RefUqc, [])
    with pytest.raises(ValueError, match="no rows for ref_currencies"):
        replace(session, RefCurrency, [])


def test_replace_removes_rows_no_longer_published(session: Session) -> None:
    replace(
        session,
        RefCurrency,
        [
            {"code": "USD", "name": "US Dollar", "minor_units": 2},
            {"code": "XYZ", "name": "Withdrawn", "minor_units": 2},
        ],
    )
    replace(session, RefCurrency, [{"code": "USD", "name": "US Dollar", "minor_units": 2}])
    session.commit()
    assert list(session.scalars(select(RefCurrency.code))) == ["USD"]


# --- loading official downloads ---------------------------------------------------------------


@pytest.mark.usefixtures("small_minimums")
def test_load_fills_every_reference_table(session: Session, downloads: Path) -> None:
    seed(session)
    report = load_all(session, downloads)
    session.commit()

    assert report.counts == LOAD_COUNTS
    assert "dropped 1 Restricted entries for codes no longer in ITC(HS)" in report.notes
    assert "skipped 1 UN/LOCODE entries for XZ (not ISO 3166)" in report.notes
    assert session.get_one(RefItcHs, "61091000").description == "Of cotton"
    assert session.get_one(RefPort, "INNSA1").kind == "sea"
    usd = session.get_one(RefExchangeRate, ("USD", date(2026, 10, 16)))
    assert (usd.rate_inr, usd.notification, usd.published_on) == (
        Decimal("94.2000"),
        "29/2026",
        date(2026, 10, 15),
    )
    sugar = session.scalars(
        select(RefExportPolicy)
        .where(RefExportPolicy.code == "17019990")
        .order_by(RefExportPolicy.effective_from)
    ).all()
    assert [(p.policy, p.effective_to) for p in sugar] == [
        ("Restricted", date(2026, 5, 12)),
        ("Prohibited", date(2026, 9, 30)),
        ("Restricted", None),
    ]


@pytest.mark.usefixtures("small_minimums")
def test_reloading_replaces_the_previous_data(session: Session, downloads: Path) -> None:
    seed(session)
    load_all(session, downloads)
    session.commit()

    ports_file = downloads / FILES["ports"]
    ports = [
        p for p in json.loads(ports_file.read_text("utf-8")) if not p["value"].startswith("INALF1")
    ]
    ports_file.write_text(json.dumps(ports), "utf-8")
    load_module.load_ports(session, downloads, LoadReport())
    load_module.load_itc_hs(session, downloads, LoadReport())
    session.commit()

    assert session.get(RefPort, "INALF1") is None
    assert count(session, RefPort) == 8
    assert count(session, RefExportPolicy) == 11  # reloading codes reloads their policy too


@pytest.mark.usefixtures("small_minimums")
def test_a_bad_download_leaves_the_previous_data(
    engine: Engine, session: Session, downloads: Path
) -> None:
    seed(session)
    load_all(session, downloads)
    session.commit()

    (downloads / FILES["itc-hs"]).write_text('[{"itcCode": "61", "itcDescription": ""}]', "utf-8")
    with (
        pytest.raises(ValueError, match="code 61 has no description"),
        Session(engine) as other,
        other.begin(),
    ):
        load_module.load_itc_hs(other, downloads, LoadReport())

    assert count(session, RefItcHs) == 31
    assert count(session, RefExportPolicy) == 11


@pytest.mark.usefixtures("small_minimums")
def test_load_order_and_missing_files_are_explained(session: Session, downloads: Path) -> None:
    report = LoadReport()
    with pytest.raises(
        RuntimeError, match=r"ref_countries is empty; run `python -m shipready\.db\.seed`"
    ):
        load_module.load_unlocode(session, downloads, report)
    with pytest.raises(RuntimeError, match="ref_currencies is empty; load currencies first"):
        load_module.load_exchange_rates(session, downloads, report)
    with pytest.raises(
        FileNotFoundError, match=r"run `python -m shipready\.reference\.fetch ports`"
    ):
        load_module.load_ports(session, downloads / "missing", report)


@pytest.mark.usefixtures("small_minimums")
def test_load_command_reports_counts_and_notes(
    session: Session,
    downloads: Path,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(session)
    session.commit()
    monkeypatch.setenv("DATABASE_URL", test_database_url)

    load_module.main(["all", "--dir", str(downloads)])

    out = capsys.readouterr().out.splitlines()
    assert out[: len(LOAD_COUNTS)] == [
        f"{table}: {rows} rows" for table, rows in LOAD_COUNTS.items()
    ]
    assert "skipped administrative entries: DEEMED, INICED, INXXX0" in out
    assert count(session, RefLocation) == 2


# --- schema -----------------------------------------------------------------------------------


def test_constraints_reject_bad_rows(session: Session) -> None:
    seed(session)
    session.commit()
    with pytest.raises(IntegrityError, match="severity_valid"):
        session.execute(text("UPDATE rules SET severity = 'critical' WHERE id = 'QTY-01'"))
    session.rollback()
    with pytest.raises(IntegrityError, match="kind_valid"):
        session.add(RefPort(code="INXYZ9", name="Rail yard", kind="ship", edi=True))
        session.flush()
    session.rollback()
    with pytest.raises(IntegrityError, match="ref_export_policy_code_fkey"):
        session.add(RefExportPolicy(code="99999999", policy="Prohibited", source="dgft"))
        session.flush()
    session.rollback()
    with pytest.raises(IntegrityError, match="level_valid"):
        session.add(RefItcHs(code="123", level=3, description="x"))
        session.flush()


def test_migrations_downgrade_to_an_empty_schema(
    engine: Engine, run_migration: Callable[[Connection, str], None]
) -> None:
    with engine.begin() as connection:
        run_migration(connection, "head")
        assert {
            "rules",
            "ref_itc_hs",
            "ref_export_policy",
            "ref_ports",
            "ref_currencies",
            "ref_exchange_rates",
            "ref_locations",
        } <= set(inspect(connection).get_table_names())
        run_migration(connection, "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
