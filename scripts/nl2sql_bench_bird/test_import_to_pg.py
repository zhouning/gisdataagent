"""Tests for BIRD import FK extraction."""
import sqlite3
import pytest


def test_extract_sqlite_fks_returns_fk_list():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from import_to_pg import extract_sqlite_fks

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, "
                 "FOREIGN KEY (customer_id) REFERENCES customers(id))")

    fks = extract_sqlite_fks(conn, "orders")
    assert len(fks) == 1
    assert fks[0]["from_col"] == "customer_id"
    assert fks[0]["ref_table"] == "customers"
    assert fks[0]["ref_col"] == "id"
    conn.close()


def test_extract_sqlite_fks_empty_for_no_fks():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from import_to_pg import extract_sqlite_fks

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE simple (id INTEGER PRIMARY KEY, val TEXT)")

    fks = extract_sqlite_fks(conn, "simple")
    assert fks == []
    conn.close()
