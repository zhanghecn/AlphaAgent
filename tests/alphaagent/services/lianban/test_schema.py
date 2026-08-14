from alphaagent.server.db import schema


def test_limit_up_tables_exist():
    assert "limit_up_pool_snapshots" in schema.metadata.tables
    assert "stock_limit_up_daily" in schema.metadata.tables
    t = schema.metadata.tables["limit_up_pool_snapshots"]
    assert {c.name for c in t.primary_key.columns} == {"trade_date", "pool_type", "vt_symbol"}
    d = schema.metadata.tables["stock_limit_up_daily"]
    assert {c.name for c in d.primary_key.columns} == {"trade_date", "vt_symbol"}
