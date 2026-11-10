"""The rulebook: what each check looks for, how serious a failure is, and the public basis for it,
so a person can read what a rule id on a report means."""

from functools import cache

from fastapi import APIRouter, Depends

from shipready.api.auth import current_principal
from shipready.api.schemas import RuleOut
from shipready.rules.catalogue import load_catalogue

# Signed-in callers only, though the rulebook is the same for every organisation.
router = APIRouter(prefix="/rules", tags=["rules"], dependencies=[Depends(current_principal)])


@router.get("")
@cache
def list_rules() -> list[RuleOut]:
    """The rules ShipReady checks, in catalogue order. Rules deferred to a later phase are left
    out, as no report shows them."""
    return [
        RuleOut.model_validate(rule, from_attributes=True)
        for rule in load_catalogue()
        if rule.enabled
    ]
