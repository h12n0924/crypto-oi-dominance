# Crypto-only OI Dominance

复刻 Coinalyze 的 BTC / ETH / Others OI Dominance，并从分母与 Others 中剔除 Coinalyze `Tokenized stock` 分类下的标的。

## 运行

在 PowerShell 中执行：

```powershell
.\run.ps1
```

脚本会安全提示输入 API Key；Key 只存在于当前进程环境，不会写入任何文件。

指定日期：

```powershell
.\run.ps1 -From 2024-09-08 -To 2026-09-08
```

## 2021 年后历史扩展

历史扩展分成两种来源，避免把不同覆盖范围伪装成同一口径：

1. `2022-07-30` 以后：使用 Coinalyze 日线。向前回填时可用现有缓存筛选当时已经存在的合约，减少无效 API 调用。
2. `2021-12-01` 至 Coinalyze 起点前：合并 Binance Data Vision 的 USD-M/COIN-M `metrics` 公共归档与 Bybit V5 linear/inverse 日线 OI，标记为 Binance + Bybit 固定交易所重建段。

Binance 归档采集器：

```powershell
.\run-binance-backfill.ps1 -From 2021-12-01 -To 2022-08-31 -Market both
```

Bybit 采集器：

```powershell
python .\bybit-backfill.py --from 2021-12-01 --to 2022-08-31
```

Binance 采集器会自动发现历史 symbol、核对官方 SHA-256、把 COIN-M OI 按同时间点 mark price 转为美元，并使用 SQLite 断点续跑。Bybit 采集器使用当前 linear/inverse 合约目录筛选当时已上线的合约，linear OI 按同时间点日线开盘价换算美元。完成采集后运行：

```powershell
python .\btc-price-backfill.py --from 2021-12-01 --to 2026-09-07
node .\combine-2021plus.mjs
```

合并脚本不会平滑或缩放早期数据，会在图表中用虚线和口径切换标记明确区分来源。交互图以左轴显示三类 dominance、右轴显示 BTCUSDT 现货日收盘价；悬停后显示具体日期、数值和数据来源，触屏设备点击可固定或取消提示。

## 每日增量更新

已有完整缓存后，可以执行：

```powershell
.\daily-update.ps1
```

脚本默认重拉最近 3 个 UTC 日、合并到现有历史、更新 BTC 价格，然后重建 CSV、JSON 与 HTML。API Key 默认仍通过安全提示临时输入，不写入文件。由于 Coinalyze 的 40 symbols/min 限制仍按当前全部合约计算，一次完整日更约需两小时；中断后同一日期窗口可从逐 symbol 缓存继续。

无人值守运行可使用：

```powershell
.\save-coinalyze-key.ps1
.\daily-update.ps1 -NonInteractive
```

`save-coinalyze-key.ps1` 使用 Windows DPAPI 加密 Key，并把密文限制为当前 Windows 用户可读。不要把 Key 明文写进脚本、任务定义或仓库；不再需要时运行 `remove-coinalyze-key.ps1` 删除本地密文。

本地自动任务 `每日更新 OI Dominance`（automation id：`oi-dominance`）已于 2026-09-20 暂停，避免旧版全市场日更继续占用约两小时。恢复前需先确定采用完整 Coinalyze 口径，还是采用更快但需要误差校验的活跃合约/交易所直连方案。

当前已生成的研究序列覆盖 2021-12-01 至 2026-09-22，共 1,757 个连续日点。33 日重叠期显示 Binance + Bybit 相对 Coinalyze 的平均偏差约为 BTC -2.85 pp、ETH -1.96 pp、Others +4.81 pp。加入 Bybit 明显缩小了 BTC 与 Others 的覆盖偏差，但早期段仍只适合观察方向与阶段变化，不能与后段作逐点同口径比较。

## GitHub Pages 云端日更

仓库内的 `.github/workflows/daily-update.yml` 会在每天 `00:20 UTC`（北京时间 08:20）启动完整更新；数据提交后，`.github/workflows/pages.yml` 会自动发布。云端需要：

1. 在 GitHub 仓库 Actions secrets 中配置 `COINALYZE_API_KEY`；
2. 在 Settings > Pages 中把发布来源设为 GitHub Actions；
3. 首次推送会直接发布仓库中已有的已验证数据；需要补到最新日期时，可手动运行一次 `Daily OI data update`。

工作流只在最新日期、日期连续性、负 OI 和 BTC 价格完整性全部通过时发布。页面提供 CSV、Excel 和汇总 JSON 下载；更新失败时保留上一版公开页面。

## 输出

- `data/dominance-cleaned.csv`：每日序列，可继续分析。
- `data/summary.json`：范围、覆盖和最新值。
- `data/dominance-cleaned.html`：可直接打开的交互图。
- `data/excluded-underlyings.csv`：被排除的股票代币及其 OI。
- `data/binance-backfill/`：2021-12 起的 Binance 公共归档明细、SQLite 缓存和日线聚合。
- `data/bybit-backfill/`：2021-12 起的 Bybit 逐合约明细、缓存、日线聚合和采集摘要。
- `data/dominance-2021plus.csv`：分段来源的 2021+ 研究序列。
- `data/dominance-2021plus.html`：带口径切换提示的交互图。
- `data/btc-price/btc-price-daily.csv`：用于悬停提示的 BTCUSDT 现货日收盘价。
- `data/daily-update-status.json`：最近一次日更的目标日期、最新有效观测和完整性检查。
- `.cache/`：逐 symbol 缓存，用于断点续跑。

## 口径

```text
all_oi(t)      = sum(eligible contract OI in USD)
excluded_oi(t) = sum(tokenized-stock contract OI in USD)
crypto_oi(t)   = all_oi(t) - excluded_oi(t)

BTC%(t)    = BTC_oi(t) / crypto_oi(t)
ETH%(t)    = ETH_oi(t) / crypto_oi(t)
Others%(t) = 1 - BTC%(t) - ETH%(t)
```

只纳入 `USD`、`USDT`、`BUSD` 报价合约，以对齐 Coinalyze 公布的聚合 OI 口径；每个交易所合约先由 API 使用 `convert_to_usd=true` 转为美元名义价值。

## 已知限制

1. Coinalyze 的 `future-markets` 是当前合约清单。已下架且不再出现在清单中的历史合约无法自动补回，因此两年回看可能存在幸存者偏差。
2. 股票代币清单是 `2026-09-08` 的分类快照。需要定期审核，尤其关注 ticker 复用和新上市标的。
3. 当前 API 返回 5,260 个合约，其中 4,958 个符合本项目的 USD/USDT/BUSD 口径。官方限制按 symbol 计费，40 symbols/min，首次完整回填预计至少约 124 分钟；之后依靠缓存增量更新。
4. `Others` 是残差，不代表单一资产类别；建议同时观察 `excluded_oi_pct` 与清洗对结果的影响。
5. 2021-12-01 至 2022-07-29 仅覆盖 Binance USD-M/COIN-M 与 Bybit linear/inverse；Bybit 使用当前合约目录，已退市历史合约仍可能遗漏。2021-01 至 2021-11 因免费公开数据无法恢复完整 `Others` 分母，未并入结果。

脚本没有硬编码“从 2025 年起剔除”。每个股票代币只在其合约实际返回非零 OI 的日期被扣除，因此上线前的影响自然为零。

分类先按底层代码匹配，再应用合约级豁免。当前明确保留 `PURR.H`：它是 Hyperliquid 原生加密资产 PURR，与同代码的股票衍生品存在 ticker 冲突。
