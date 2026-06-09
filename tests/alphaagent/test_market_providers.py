from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.market.providers import RealMarketDataClient


def test_real_market_data_client_is_akshare_backed() -> None:
    client = RealMarketDataClient()

    assert isinstance(client, AkShareAdapter)
    assert RealMarketDataClient.list_stocks is not AkShareAdapter.list_stocks
    assert RealMarketDataClient.sector_stocks is not AkShareAdapter.sector_stocks
    assert not hasattr(client, "_sina_bars")
    assert not hasattr(client, "_eastmoney_bars")
