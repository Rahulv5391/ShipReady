import zipfile
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shipready.db import seed as seed_module
from shipready.db.load_unlocode import load_unlocode
from shipready.db.load_unlocode import main as load_unlocode_main
from shipready.db.models import (
    RefCountry,
    RefExchangeRate,
    RefItcHs,
    RefLocation,
    RefPort,
    RefUqc,
    Rule,
)
from shipready.db.seed import seed
from shipready.db.session import database_url
from shipready.db.upsert import upsert

EXPECTED_COUNTS = {
    "rules": 39,
    "ref_uqc": 45,
    "ref_countries": 249,
    "ref_ports": 28,
    "ref_itc_hs": 21,
    "ref_exchange_rates": 66,
}


def table_counts(session: Session) -> dict[str, int]:
    models = (Rule, RefUqc, RefCountry, RefPort, RefItcHs, RefExchangeRate)
    return {
        m.__tablename__: session.scalar(select(func.count()).select_from(m)) or 0 for m in models
    }


def test_seed_loads_rules_and_reference_data(session: Session) -> None:
    assert seed(session) == EXPECTED_COUNTS
    session.commit()

    assert table_counts(session) == EXPECTED_COUNTS
    weight = session.get_one(Rule, "WT-01")
    assert weight.params == {"gross_weight_tolerance_pct": 0.5}
    assert weight.severity == "major"
    assert session.get_one(Rule, "POL-02").enabled is False
    assert session.get_one(RefPort, "INNSA1").unlocode == "INNSA"
    assert session.get_one(RefUqc, "KGS").description == "KILOGRAMS"
    assert session.get_one(RefItcHs, "17019990").export_policy == "Restricted"
    usd = session.get_one(RefExchangeRate, ("USD", date(2026, 10, 16)))
    assert (usd.unit, usd.rate_inr) == (1, Decimal("94.2000"))


def test_seed_is_idempotent_and_restores_edited_rows(session: Session) -> None:
    seed(session)
    session.commit()
    session.execute(text("UPDATE rules SET severity = 'info' WHERE id = 'QTY-01'"))
    session.commit()

    assert seed(session) == EXPECTED_COUNTS
    session.commit()

    session.expire_all()
    assert table_counts(session) == EXPECTED_COUNTS
    assert session.get_one(Rule, "QTY-01").severity == "blocker"


def test_seed_keeps_rows_added_by_other_loaders(session: Session) -> None:
    seed(session)
    session.add(RefPort(code="INPAV1", name="Pipavav", country="IN", unlocode="INPAV", kind="sea"))
    session.commit()

    seed(session)
    session.commit()
    assert session.get(RefPort, "INPAV1") is not None


def test_constraints_reject_bad_rows(session: Session) -> None:
    seed(session)
    session.commit()
    with pytest.raises(IntegrityError, match="severity_valid"):
        session.execute(text("UPDATE rules SET severity = 'critical' WHERE id = 'QTY-01'"))
    session.rollback()
    with pytest.raises(IntegrityError, match="ref_ports_country_fkey"):
        session.add(
            RefPort(code="XXABC", name="Nowhere", country="XX", unlocode="XXABC", kind="sea")
        )
        session.flush()
    session.rollback()
    with pytest.raises(IntegrityError, match="kind_valid"):
        session.add(
            RefPort(code="INXYZ9", name="Rail yard", country="IN", unlocode="INXYZ", kind="rly")
        )
        session.flush()


def test_migrations_downgrade_to_an_empty_schema(
    engine: Engine, run_migration: Callable[[Connection, str], None]
) -> None:
    with engine.begin() as connection:
        run_migration(connection, "head")
        assert {"rules", "ref_itc_hs", "ref_exchange_rates", "ref_locations"} <= set(
            inspect(connection).get_table_names()
        )
        run_migration(connection, "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}


def test_main_seeds_the_database_from_database_url(
    session: Session,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    seed_module.main()

    assert capsys.readouterr().out.splitlines() == [
        f"{table}: {count} rows" for table, count in EXPECTED_COUNTS.items()
    ]
    assert table_counts(session) == EXPECTED_COUNTS


def test_database_url_must_be_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        database_url()


def test_upsert_rejects_an_empty_source(session: Session) -> None:
    with pytest.raises(ValueError, match="no rows for ref_uqc"):
        upsert(session, RefUqc, [])


def test_load_unlocode_upserts_locations(session: Session, tmp_path: Path) -> None:
    seed(session)
    zip_path = tmp_path / "unlocode-latest.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "release/csv/CodeListPart1.csv",
            ",IN,NSA,Nhava Sheva,Nhava Sheva,MH,1-------,AA,,,,\n"
            ",XZ,ABC,At sea,At sea,,1-------,RL,,,,\n",
        )

    parsed = load_unlocode(session, zip_path)
    load_unlocode(session, zip_path)
    session.commit()

    assert parsed.skipped_countries == {"XZ": 1}
    assert session.scalar(select(func.count()).select_from(RefLocation)) == 1
    assert session.get_one(RefLocation, "INNSA").functions == "1-------"


def test_load_unlocode_needs_seeded_countries(session: Session, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"run `python -m shipready.db.seed` first"):
        load_unlocode(session, tmp_path / "unused.zip")


def test_load_unlocode_command_rejects_a_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        load_unlocode_main([str(tmp_path / "missing.zip")])
    assert exit_info.value.code == 2
    assert "file not found" in capsys.readouterr().err
