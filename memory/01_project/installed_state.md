# Installed State

本文件记录当前环境中实际检测到的插件状态。

检测方式：

```bash
python - <<'PY'
import importlib.util
mods = [...]
for m in mods:
    print(m, bool(importlib.util.find_spec(m)))
PY
```

## 已安装

- `vnpy`
- `vnpy_ctp`
- `vnpy_ctastrategy`
- `vnpy_ctabacktester`
- `vnpy_datamanager`
- `vnpy_sqlite`

## 未安装但与 A 股/数据密切相关

- `vnpy_xt`
- `vnpy_rqdata`
- `vnpy_tushare`
- `vnpy_xtp`
- `vnpy_tora`
- `vnpy_ost`
- `vnpy_emt`

## 未安装但后续可能有用的应用插件

- `vnpy_scripttrader`
- `vnpy_portfoliostrategy`
- `vnpy_datarecorder`

## 当前影响

- 当前 `examples/veighna_trader/run.py` 只能注册 CTP Gateway，不能直接连接 A 股券商。
- 当前 DataManager 可启动，但如果没有配置 Datafeed 或连接可提供历史数据的 Gateway，就无法下载 A 股历史数据。
- 当前不能通过官方 A 股 Gateway 查看全部 A 股合约/行情，因为相关插件未安装。

## AlphaAgent 服务端数据依赖

- 服务端依赖组已安装 `baostock==0.9.3`，用于低吸证券主表和历史状态的重建审计。
- BaoStock 不是 vn.py Gateway/Datafeed，也不提供本项目已核验的点时发布时间保证；
  当前证据等级固定为 `reconstructed`，不能解除严格历史研究门禁。
