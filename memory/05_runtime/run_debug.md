# Run and Debug

## 当前 GUI 启动入口

```bash
uv run python examples/veighna_trader/run.py
```

当前注册内容：

- Gateway: `CtpGateway`
- Apps: `CtaStrategyApp`, `CtaBacktesterApp`, `DataManagerApp`

源码位置：

- `examples/veighna_trader/run.py`

## 依赖状态

`pyproject.toml` 当前设置：

```toml
name = "vnpy"
requires-python = ">=3.11"
```

仓库/产品名是 AlphaAgent，但源码包目录和 Python 发行包名仍然是 `vnpy`，这是为了保持 vn.py 插件兼容性。

原因：

- `uv sync` 解析 `dev` 依赖时，`scipy-stubs>=1.16.3.0` 需要 Python >= 3.11。
- 原项目 `requires-python = ">=3.10"` 会让解析器认为需要支持 Python 3.10，从而产生冲突。

## 调试看数据的优先路径

优先从 vn.py 官方机制调试：

1. `examples/veighna_trader/run.py` 看注册了哪些 Gateway/App。
2. `MainEngine.get_all_gateway_names()` 看运行时有哪些接口。
3. 连接 Gateway 后，用 `get_all_contracts()` 看合约是否进入系统。
4. 订阅行情后，用 `get_tick(vt_symbol)` 或 `get_all_ticks()` 看 Tick 是否进入系统。
5. 配置 Datafeed 后，用 `get_datafeed().query_bar_history()` 看历史数据是否可取。
6. 用 DataManager 看数据库中是否有历史数据。

不优先写临时免费数据脚本，除非用户明确要求做外部数据源适配。
