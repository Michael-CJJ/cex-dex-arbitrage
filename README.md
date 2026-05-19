# CEX/DEX Arbitrage Prototype

一个基于 Python `asyncio` 的 CEX/DEX 套利原型项目，用于演示 Binance Futures 与 BSC 上 PancakeSwap V3 池子之间的行情采集、价差计算、交易决策、双腿执行和结果汇总流程。

本项目定位是工程样例和研究原型，不是金融建议，也不是可直接用于生产环境的交易系统。

## 项目能力

- 通过 Binance Futures `bookTicker` WebSocket 采集合约最优买卖盘。
- 通过 Binance Spot BNB/USDT `bookTicker` 获取 BNB 价格，用于 `POOL_BNB=true` 时的 DEX 价格换算。
- 通过 BSC `eth_subscribe` 订阅 PancakeSwap V3 `Swap` 日志。
- 解码 PancakeSwap V3 Swap 日志，生成 DEX 行情 tick。
- 当 Swap 日志发送方匹配 `CONTRACT_ADDRESS` 时，将其识别为本项目执行合约产生的 DEX 成交结果。
- 使用 typed async bus 串联行情、信号、交易决策、执行结果和最终汇总。
- 使用 `Decimal` 计算 CEX/DEX 价差，避免交易逻辑中的浮点误差。
- 策略层支持同方向冷却、CEX 数量/价格精度处理、简单 DEX token0 库存约束和可接受价格边界。
- CEX 执行层通过 Binance Futures WebSocket API 发送签名的 FOK 限价单请求。
- DEX 执行层调用执行合约 `swap(...)`，并生成 PancakeSwap V3/Uniswap V3 风格的 `sqrtPriceLimitX96` 价格边界。
- 汇总层将 CEX 与 DEX 成交结果组合为最终交易摘要。
- 支持将最终交易摘要写入 SQLite，并通过带签名的 webhook 发送通知。

## 架构流程

```text
BinanceOrderbookSource -> market_bus -> TickCache -> valid_market_bus -> ArbCalculator -> signal_bus -> StrategyEngine -> trade_bus -> Trader
BinanceBNBPriceSource  -> market_bus -> TickCache -> valid_market_bus -> ArbCalculator
BinanceBNBPriceSource  -> market_bus -> BNBPriceCache
PancakeSwapLogsSource  -> market_bus -> TickCache -> valid_market_bus -> ArbCalculator

Trader -> cex_trade -> BinanceOrderFillSource -> result_bus -> Summary
Trader -> dex_trade -> PancakeSwapLogsSource own-contract fill -> result_bus -> Summary
trade_bus + result_bus -> Summary -> final_bus -> Recorder
trade_bus + result_bus -> Summary -> final_bus -> Notifier
```

当前策略和汇总逻辑适合小规模、顺序化的原型验证。真实生产系统还需要稳定 trade id、完整成交对账、链上重组处理、限频处理、风控模块和 dry-run/live 模式隔离。

## 目录结构

```text
src/
  main.py            运行时组装入口
  buses/             typed async pub/sub bus
  components/        缓存、计算器、策略、交易调度、汇总、记录、通知
  config/            环境变量配置加载
  models/            dataclass 消息模型
  sources/           Binance 与 PancakeSwap 数据源
  trading/           CEX 与 DEX 执行封装
  utils/             日志与 WebSocket 客户端
contracts/
  PancakeV3SwapExecutor.sol  DEX 直连 PancakeSwap V3 池子的执行合约示例
scripts/
  offline_replay.py  离线回放示例
tests/               离线单元测试
docs/                架构说明
```

## 环境要求

- Python 3.11+
- 可访问 Binance WebSocket API
- 可访问 BSC WebSocket/HTTP RPC
- 如果运行真实交易，需要 Binance API key、BSC 钱包私钥、执行合约地址和 PancakeSwap V3 池子配置

安装依赖：

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

macOS/Linux 激活虚拟环境：

```bash
source .venv/bin/activate
```

## 配置

复制环境变量模板：

```bash
copy .env.example .env
```

关键配置项：

- `BINANCE_API_KEY`, `BINANCE_API_SECRET`：Binance Futures WebSocket API 凭证。
- `BINANCE_FUTURES_SYMBOL`：Binance Futures 交易对，例如 `BUSDT`。
- `CEX_QUANTITY_PRECISION`, `CEX_PRICE_PRECISION`：CEX 下单数量和价格精度。
- `CHAINSTACK_WSS_URL`：BSC WebSocket RPC，用于订阅 PancakeSwap 日志。
- `CHAINSTACK_HTTPS_URL`：BSC HTTP RPC，用于查询 receipt 和加载 pending nonce。
- `DEX_RPC_URL`：DEX 交易提交使用的 RPC。
- `BSC_PRIVATE_KEY`：BSC 钱包私钥。
- `CONTRACT_ADDRESS`：执行合约地址，同时用于识别自己的 DEX Swap 日志。
- `DEX_RECIPIENT`：DEX swap 接收地址；为空时使用执行合约地址。
- `DEX_GAS_LIMIT`, `DEX_GAS_PRICE_WEI`, `CHAIN_ID`：链上交易参数。
- `PANCAKE_V3_POOL_ADDRESS`：PancakeSwap V3 池子地址。
- `POOL_TOKEN0_ADDRESS`, `POOL_TOKEN1_ADDRESS`：池子 token 元数据。
- `POOL_BNB`：池子价格是否需要乘以 BNB/USDT 中间价。
- `BASE_BPS`, `THRESHOLD_BPS`：基准价差和触发阈值。
- `MIN_SIGNAL_INTERVAL_MS`：同方向信号冷却时间。
- `MAX_POSITIONS`, `INITIAL_D_TO_C_POSITIONS`：简单库存约束。
- `QUANTITY`：每次交易的 token0 数量，进入 CEX 前会按精度向下取整。
- `WEBHOOK`, `SECRET`：最终交易通知的 webhook 地址和签名密钥。
- `SHUTDOWN_TIMEOUT_MS`：优雅关闭时等待 Trader 与 Summary drain 的超时时间。

## 测试

```bash
python -m pytest -q
```

测试覆盖行情解析、BNB 价格缓存、Swap 日志解码、价差计算、策略决策、CEX/DEX 执行封装、汇总、记录、通知和关闭流程。测试设计为离线运行，不需要真实 API key、钱包私钥、RPC URL 或 `.env`。

## 离线示例

```bash
python scripts/offline_replay.py
```

该脚本会发布合成的订单簿 tick 和 Swap tick，经过真实的 `ArbCalculator` 与 `StrategyEngine`，并打印生成的交易决策。

## 运行时行为

运行时入口在 `src/main.py`，负责组装以下组件：

- `TickCache`
- `ArbCalculator`
- `BNBPriceCache`
- `StrategyEngine`
- `BinanceOrderFillSource`
- `Summary`
- `Trader`
- `Recorder`
- `Notifier`
- Binance/PancakeSwap 外部数据源

DEX 侧交易需要配套部署 `contracts/PancakeV3SwapExecutor.sol`。Python 侧会调用该合约的
`swap(pool, recipient, zeroForOne, amountSpecified, sqrtPriceLimitX96, inToken)` 方法，
`CONTRACT_ADDRESS` 应配置为部署后的执行合约地址。该合约通过 PancakeSwap V3 callback 向池子支付
`inToken`，因此执行前需要确保合约内有足够的对应 token 余额；剩余资产可由 owner 调用 `withdraw`
取回。合约使用 Solidity `0.8.28` 和 transient storage 指令 `tstore`/`tload`，部署前需确认目标链和编译配置支持这些指令。

启动时会校验实时运行所需的关键配置，包括 Binance 凭证、RPC 地址、执行合约地址、池子地址和 token 地址。初始化 DEX 交易前会加载链上 pending nonce，并写入本地 nonce 状态。

运行时本地状态：

- nonce 状态：`data/nonce_state.json`
- 最终交易摘要：`data/final_trades.sqlite3`
- 日志：当前 logger 输出到 stdout；仓库保留并忽略 `logs/` 目录，便于后续接入文件日志

## 风险与边界

- 这是研究原型，不应直接作为生产交易系统使用。
- 当前汇总逻辑是顺序匹配，适合简单 in-flight 行为，不适合复杂并发对账。
- DEX 日志处理会忽略 `removed=true` 的日志，但没有完整链重组恢复机制。
- 当前没有完整风控、资金管理、熔断、限频恢复或 dry-run/live 隔离。
- 不要提交 `.env`、私钥、API secret、webhook secret、nonce 状态、SQLite 输出或真实运行日志。

## 开发说明

项目将外部 IO 边界放在 `sources/` 和 `trading/`，核心计算和决策放在 `components/`，数据契约放在 `models/`。这种结构便于把行情解析、价差计算、策略判断、汇总、记录和通知拆开测试，也方便后续替换真实交易执行或扩展更多数据源。
