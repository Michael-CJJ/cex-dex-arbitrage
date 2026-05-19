import asyncio
import sqlite3
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
from typing import Any

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.final import FinalTradeSummary

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "final_trades.sqlite3"
TABLE_NAME = "final_trades"


class Recorder:
    """Subscribe to final_bus and persist each final trade summary to sqlite."""

    def __init__(
        self,
        final_bus: Bus[FinalTradeSummary],
        *,
        db_path: Path = DB_PATH,
    ) -> None:
        self.final_bus = final_bus
        self.db_path = Path(db_path)
        self._lock = asyncio.Lock()

    def start(self) -> None:
        self._ensure_database()
        self.final_bus.subscribe(self._on_final)

    async def _on_final(self, summary: FinalTradeSummary) -> None:
        async with self._lock:
            await asyncio.to_thread(self._insert_summary, summary)

    def _ensure_database(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(_create_table_sql())

    def _insert_summary(self, summary: FinalTradeSummary) -> None:
        column_names = _summary_column_names()
        columns = ", ".join(column_names)
        placeholders = ", ".join("?" for _ in column_names)
        values = [_serialize_value(getattr(summary, name)) for name in column_names]

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT INTO {TABLE_NAME} ({columns}) VALUES ({placeholders})",
                values,
            )


def _create_table_sql() -> str:
    columns = ",\n                ".join(
        f"{name} TEXT" for name in _summary_column_names()
    )
    return f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {columns}
        )
    """


def _summary_column_names() -> list[str]:
    return [field.name for field in fields(FinalTradeSummary)]


def _serialize_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)
