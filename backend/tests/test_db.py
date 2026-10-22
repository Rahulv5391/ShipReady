from collections.abc import Callable

import pytest
from sqlalchemy import Connection, Engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shipready.db import seed as seed_module
from shipready.db.models import RefCountry, RefPort, RefUqc, Rule
from shipready.db.seed import seed
from shipready.db.session import database_url

EXPECTED_COUNTS = {"rules": 39, "ref_uqc": 45, "ref_countries": 249, "ref_ports": 28}


def table_counts(session: Session) -> dict[str, int]:
    models = (Rule, RefUqc, RefCountry, RefPort)
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
        assert {"rules", "ref_uqc", "ref_countries", "ref_ports"} <= set(
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
    with pytest.raises(ValueError, match="no seed rows for ref_uqc"):
        seed_module._upsert(session, RefUqc, [])
