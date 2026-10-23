"""Fixed choices ShipGen draws from: exporter states, destination countries, terms."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IndianState:
    gst_code: str
    name: str
    cities: tuple[str, ...]
    pin_prefix: str  # first digit of the state's PIN codes


@dataclass(frozen=True)
class Destination:
    faker_locale: str  # Latin-script locale used for company names and streets
    cities: tuple[str, ...]
    currency: str


EXPORTER_STATES = (
    IndianState("27", "Maharashtra", ("Mumbai", "Pune", "Nashik"), "4"),
    IndianState("24", "Gujarat", ("Ahmedabad", "Surat", "Rajkot", "Morbi"), "3"),
    IndianState("33", "Tamil Nadu", ("Chennai", "Coimbatore", "Tiruppur"), "6"),
    IndianState("29", "Karnataka", ("Bengaluru", "Mysuru"), "5"),
    IndianState("07", "Delhi", ("New Delhi",), "1"),
    IndianState("09", "Uttar Pradesh", ("Noida", "Kanpur", "Moradabad"), "2"),
    IndianState("19", "West Bengal", ("Kolkata", "Howrah"), "7"),
    IndianState("32", "Kerala", ("Kochi", "Kollam"), "6"),
    IndianState("08", "Rajasthan", ("Jaipur", "Jodhpur"), "3"),
    IndianState("06", "Haryana", ("Gurugram", "Panipat"), "1"),
)

# Keys must be countries that have a foreign port in reference/data/ports.csv.
DESTINATIONS = {
    "AE": Destination("en_GB", ("Dubai", "Sharjah"), "AED"),
    "SA": Destination("en_GB", ("Jeddah", "Riyadh"), "SAR"),
    "LK": Destination("en_GB", ("Colombo",), "USD"),
    "SG": Destination("en_GB", ("Singapore",), "USD"),
    "HK": Destination("en_GB", ("Hong Kong",), "USD"),
    "CN": Destination("en_GB", ("Shanghai",), "USD"),
    "NL": Destination("nl_NL", ("Rotterdam", "Amsterdam"), "EUR"),
    "BE": Destination("nl_BE", ("Antwerp", "Brussels"), "EUR"),
    "DE": Destination("de_DE", ("Hamburg", "Frankfurt"), "EUR"),
    "GB": Destination("en_GB", ("London", "Manchester"), "GBP"),
    "US": Destination("en_US", ("New York", "Los Angeles"), "USD"),
    "AU": Destination("en_AU", ("Sydney", "Melbourne"), "AUD"),
    "KE": Destination("en_GB", ("Nairobi", "Mombasa"), "USD"),
}

# Fictional names, so generated documents never imitate a real bank or certifying body.
BANKS = ("Sahyadri Bank", "Coromandel Bank", "Narmada Bank", "Deccan Commercial Bank")
COO_ISSUER = "ShipGen Chamber of Commerce"
COMPANY_SUFFIXES = ("Exports Pvt Ltd", "Overseas", "International", "Impex Pvt Ltd", "Industries")

SEA_INCOTERMS = ("FOB", "CFR", "CIF")
AIR_INCOTERMS = ("FCA", "CPT", "CIP")
# Under C-terms the seller pays the main carriage, so freight is prepaid.
PREPAID_INCOTERMS = {"CFR", "CIF", "CPT", "CIP"}
INSURED_INCOTERMS = {"CIF", "CIP"}

# (payment terms, bill of lading consigned "to order"): documentary collections keep title
# with the bank, so the bill of lading is made out to order.
PAYMENT_TERMS = (
    ("Advance payment by T/T", False),
    ("30% advance, balance against copy of B/L", False),
    ("D/P at sight", True),
    ("D/A 60 days from B/L date", True),
)
