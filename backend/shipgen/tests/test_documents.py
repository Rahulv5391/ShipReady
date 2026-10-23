import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from shipgen import __main__ as cli
from shipgen.documents import LUT_DECLARATION, build_documents, chargeable_weight
from shipgen.generator import generate_shipment
from shipgen.models import Shipment


def first(predicate: Callable[[Shipment], bool]) -> Shipment:
    for index in range(500):
        shipment = generate_shipment(9, index)
        if predicate(shipment):
            return shipment
    raise AssertionError("no generated shipment matched")


def test_documents_agree_with_the_golden_shipment() -> None:
    s = first(lambda s: s.transport.mode == "sea" and not s.to_order)
    d = build_documents(s)
    ci, sb, bl = d.commercial_invoice, d.shipping_bill, d.bill_of_lading
    assert bl is not None and d.air_waybill is None

    assert (sb.invoice_number, sb.invoice_date) == (ci.invoice_number, ci.invoice_date)
    assert sb.gstin == ci.gstin == s.exporter.gstin
    assert [line.quantity for line in sb.lines] == [line.quantity for line in s.lines]
    assert [line.hs_code for line in d.certificate_of_origin.lines] == [
        line.hs_code for line in s.lines
    ]
    assert sb.fob_value == ci.goods_value == d.purchase_order.total
    assert sb.port_code == bl.port_of_loading.code == s.transport.port_of_loading.code
    assert bl.consignee == s.consignee and bl.notify_party is None
    assert d.packing_list.total_packages == bl.total_packages == sb.total_packages
    assert d.packing_list.containers == bl.containers == sb.containers
    assert ci.incoterm == f"{s.incoterm} {s.incoterm_place}"
    assert ci.gst_declaration == LUT_DECLARATION and ci.lut_arn == d.lut.arn == s.lut.arn
    assert d.lut.gstin == s.exporter.gstin


def test_to_order_bill_of_lading_names_no_consignee() -> None:
    s = first(lambda s: s.to_order)
    bl = build_documents(s).bill_of_lading
    assert bl is not None
    assert bl.to_order and bl.consignee is None and bl.notify_party == s.consignee


def test_air_shipment_gets_an_airway_bill() -> None:
    s = first(lambda s: s.transport.mode == "air")
    d = build_documents(s)
    assert d.bill_of_lading is None and d.air_waybill is not None
    assert d.air_waybill.awb_number == s.transport.carrier_reference
    assert d.air_waybill.chargeable_weight_kg >= s.gross_weight_kg
    assert d.certificate_of_origin.transport.startswith("By air, SG ")


def test_chargeable_weight_uses_volume_when_cargo_is_light() -> None:
    assert chargeable_weight(Decimal("100"), Decimal("1")) == Decimal("167.000")
    assert chargeable_weight(Decimal("500"), Decimal("1")) == Decimal("500")


def test_cli_writes_identical_json_for_the_same_seed(tmp_path: Path) -> None:
    first_run = cli.write_shipments(3, 11, tmp_path / "a")
    second_run = cli.write_shipments(3, 11, tmp_path / "b")
    assert [path.name for path in first_run] == [
        "SG11-0000.json",
        "SG11-0001.json",
        "SG11-0002.json",
    ]
    for a, b in zip(first_run, second_run, strict=True):
        assert a.read_bytes() == b.read_bytes()
    record = json.loads(first_run[0].read_text(encoding="utf-8"))
    assert set(record) == {"shipment", "documents"}
    assert (
        record["documents"]["commercial_invoice"]["invoice_number"]
        == record["shipment"]["invoice_number"]
    )


def test_cli_refuses_an_inconsistent_shipment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "check_shipment", lambda shipment: ["broken on purpose"])
    with pytest.raises(RuntimeError, match="SG1-0000 is inconsistent: broken on purpose"):
        cli.write_shipments(1, 1, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cli_rejects_a_zero_count(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--count", "0", "--seed", "1", "--out", str(tmp_path)])
    assert exit_info.value.code == 2
    assert "--count must be at least 1" in capsys.readouterr().err
