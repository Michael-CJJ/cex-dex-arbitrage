import sqlite3
from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.components.recorder import Recorder
from cex_dex_arbitrage.models.final import FinalTradeSummary


def _summary(total_fee: Decimal | None = Decimal("0.5605")) -> FinalTradeSummary:
    return FinalTradeSummary(
        signal_activate_time="2026-05-13 12:00:00.001",
        bps=Decimal("12.34"),
        direction="c-d",
        quantity=Decimal("10"),
        cex_expected_price=Decimal("100.0000"),
        cex_price=Decimal("100.1000"),
        cex_fee=Decimal("0.5005"),
        cex_receive_time="2026-05-13 12:00:00.010",
        dex_expected_price=Decimal("101.0000"),
        dex_price=Decimal("100.9000"),
        dex_gas_usd=Decimal("0.0600"),
        dex_receive_time="2026-05-13 12:00:00.020",
        realized_bps=Decimal("79.92007992007992007992007992"),
        total_fee=total_fee,
    )


async def test_recorder_persists_final_summary_to_sqlite(tmp_path) -> None:
    db_path = tmp_path / "data" / "final_trades.sqlite3"
    final_bus: Bus[FinalTradeSummary] = Bus("final-test")
    Recorder(final_bus=final_bus, db_path=db_path).start()

    summary = _summary()
    await final_bus.publish(summary)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM final_trades").fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == 1
    assert row["signal_activate_time"] == "2026-05-13 12:00:00.001"
    assert row["bps"] == "12.34"
    assert row["direction"] == "c-d"
    assert row["quantity"] == "10"
    assert row["cex_expected_price"] == "100.0000"
    assert row["cex_price"] == "100.1000"
    assert row["cex_fee"] == "0.5005"
    assert row["cex_receive_time"] == "2026-05-13 12:00:00.010"
    assert row["dex_expected_price"] == "101.0000"
    assert row["dex_price"] == "100.9000"
    assert row["dex_gas_usd"] == "0.0600"
    assert row["dex_receive_time"] == "2026-05-13 12:00:00.020"
    assert row["realized_bps"] == "79.92007992007992007992007992"
    assert row["total_fee"] == "0.5605"


async def test_recorder_records_each_final_bus_message(tmp_path) -> None:
    db_path = tmp_path / "final_trades.sqlite3"
    final_bus: Bus[FinalTradeSummary] = Bus("final-test")
    Recorder(final_bus=final_bus, db_path=db_path).start()

    await final_bus.publish(_summary(Decimal("0.5605")))
    await final_bus.publish(_summary(None))

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, total_fee FROM final_trades ORDER BY id").fetchall()

    assert [(row["id"], row["total_fee"]) for row in rows] == [
        (1, "0.5605"),
        (2, None),
    ]
