from __future__ import annotations

from msu_anechoic import spec_an
from msu_anechoic import turn_table


def test_spec_an_connection() -> None:
    try:
        sa = spec_an.find()
        serial = sa.get_serial_number()
    except Exception as exc:
        print(f"❌ Unable to connect to Spectrum Analyzer: {exc!r}")
    else:
        print(f"✅ Connected to Spectrum Analyzer. Serial: {serial}, GPIB address: {sa.gpib_address}")


def test_turn_table_connection() -> None:
    try:
        tt = turn_table.find()
        position = tt.wait_for_position()
    except Exception as exc:
        print(f"❌ Unable to connect to Turn Table: {exc!r}")
    else:
        print(f"✅ Connected to Turn Table. Current position: {position}")


if __name__ == "__main__":
    test_spec_an_connection()
    test_turn_table_connection()
