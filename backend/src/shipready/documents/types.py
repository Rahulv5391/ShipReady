"""The document types ShipReady recognises: one per ShipmentDocuments field, plus "other" for
anything else in a bundle (a certificate, a letter, a page that belongs to nothing)."""

from shipready.documents.models import ShipmentDocuments

DOCUMENT_TYPES: tuple[str, ...] = (*ShipmentDocuments.model_fields, "other")
