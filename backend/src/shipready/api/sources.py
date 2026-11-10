"""Where ShipReady's knowledge comes from: the regulatory texts the checks cite, and the reference
datasets they compare documents against, each with its publisher and the checks that use it."""

from dataclasses import dataclass
from functools import cache

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from shipready.api.auth import current_principal
from shipready.api.deps import SessionDep
from shipready.api.schemas import DatasetOut, RegulationOut, SourcesOut
from shipready.db.models import (
    Base,
    RefCountry,
    RefCurrency,
    RefExchangeRate,
    RefExportPolicy,
    RefItcHs,
    RefLoad,
    RefLocation,
    RefPort,
    RefUqc,
)
from shipready.knowledge.sources import load_sources
from shipready.rules.catalogue import load_catalogue

router = APIRouter(prefix="/sources", tags=["sources"], dependencies=[Depends(current_principal)])


@dataclass(frozen=True)
class Dataset:
    id: str
    title: str
    publisher: str
    # Downloaded datasets use their download's name (shipready.reference.fetch.FILES), under
    # which the loader records when they were fetched and loaded.
    # A page a person can open. The fetch itself calls DGFT's and ICEGATE's form endpoints
    # (shipready.reference.fetch), which show nothing useful in a browser.
    url: str | None
    table: type[Base]
    used_by: tuple[str, ...]
    note: str


DGFT_ITC_HS = "https://www.dgft.gov.in/CP/?opt=itchs-import-export"

DATASETS = (
    Dataset(
        "itc-hs",
        "ITC(HS) codes",
        "DGFT",
        DGFT_ITC_HS,
        RefItcHs,
        ("HS-01", "HS-03", "POL-01"),
        "Every chapter, heading and 8-digit tariff item with its description.",
    ),
    Dataset(
        "export-policy",
        "Export policy",
        "DGFT",
        DGFT_ITC_HS,
        RefExportPolicy,
        ("POL-01",),
        "The Restricted, Prohibited and STE export lists; any other code is Free.",
    ),
    Dataset(
        "exchange-rates",
        "Customs exchange rates",
        "CBIC, published on ICEGATE",
        "https://foservices.icegate.gov.in/#/services/viewExchangeRate",
        RefExchangeRate,
        ("FX-01",),
        "The export rate of each currency, from every notification since 4 July 2024.",
    ),
    Dataset(
        "ports",
        "Indian customs locations",
        "DGFT, from ICEGATE",
        "https://www.dgft.gov.in/CP/",
        RefPort,
        ("PORT-01",),
        "Ports, airports and inland container depots with their ICEGATE codes.",
    ),
    Dataset(
        "uqc",
        "Unit quantity codes (UQC)",
        "GST, kept in ShipReady's code",
        None,
        RefUqc,
        ("QTY-01", "QTY-02", "QTY-03", "UQC-01"),
        "The units of quantity a shipping bill and GST return accept.",
    ),
    Dataset(
        "currencies",
        "ISO 4217 currencies",
        "SIX, the ISO 4217 maintenance agency",
        "https://www.six-group.com/en/products-services/financial-information/data-standards.html",
        RefCurrency,
        (),
        "The currency codes the exchange rates are kept under.",
    ),
    Dataset(
        "unlocode",
        "UN/LOCODE locations",
        "UNECE",
        "https://unlocode.unece.org/",
        RefLocation,
        (),
        "Ports and places outside India, loaded for destinations.",
    ),
    Dataset(
        "countries",
        "ISO 3166 countries",
        "ISO, kept in ShipReady's code",
        None,
        RefCountry,
        (),
        "Country codes and names; UN/LOCODE entries outside this list are skipped.",
    ),
)


@cache
def _regulations() -> list[RegulationOut]:
    """Each text with the enabled checks it supports. Deferred checks are left out, as the
    rulebook does not list them and a link would lead nowhere."""
    enabled = {rule.id for rule in load_catalogue() if rule.enabled}
    return [
        RegulationOut(
            id=source.id,
            title=source.title,
            issuer=source.issuer,
            version=source.version,
            url=source.url,
            format=source.format,
            used_by=[rule for rule in source.used_by if rule in enabled],
        )
        for source in load_sources()
    ]


@router.get("")
def list_sources(session: SessionDep) -> SourcesOut:
    """The regulatory texts in sources.yaml order, then the reference datasets with how many
    rows are loaded now and when each was fetched and loaded. Exchange rates also give the start
    of the newest rate in force."""
    newest_rate = session.scalar(select(func.max(RefExchangeRate.valid_from)))
    loads = {load.source: load for load in session.scalars(select(RefLoad))}
    datasets = [
        DatasetOut(
            id=dataset.id,
            title=dataset.title,
            publisher=dataset.publisher,
            url=dataset.url,
            used_by=list(dataset.used_by),
            note=dataset.note,
            rows=session.scalar(select(func.count()).select_from(dataset.table)) or 0,
            as_of=newest_rate if dataset.table is RefExchangeRate else None,
            fetched_at=load.fetched_at if (load := loads.get(dataset.id)) else None,
            loaded_at=load.loaded_at if load else None,
        )
        for dataset in DATASETS
    ]
    return SourcesOut(regulations=_regulations(), datasets=datasets)
