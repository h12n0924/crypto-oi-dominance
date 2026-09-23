# OI Dominance 2021+ 历史扩展

## 当前目标

把现有 2024-09-08 起的 Coinalyze BTC / ETH / Others OI dominance 向前扩展，同时保持股票代币逐合约、逐日剔除口径。

## 已确认取舍

- 不把覆盖范围不同的数据伪装成同一精确口径。
- 不对早期序列做平滑、缩放或主观修正。
- 2022-07-30 以后使用 Coinalyze 日线；2021-12-01 至其起点前使用 Binance USD-M/COIN-M + Bybit linear/inverse 固定交易所重建段，并在图中以虚线显示。
- 2021-01 至 2021-11 暂不并入全市场 dominance，因为免费公开数据不足以可靠恢复 `Others` 分母。

## 已完成

- 新增 `outputs/oi-dominance/binance-backfill.py`：
  - 从 Binance Data Vision S3 自动发现历史合约；
  - 下载并校验 metrics ZIP；
  - COIN-M 使用同时间点 5 分钟 mark price 换算美元；
  - SQLite 断点保存并导出逐合约、聚合 CSV。
- Binance 2021-12-01 至 2022-08-31 回填完成：
  - 274 个连续日点；
  - 57,588 条合约日观测；
  - 每日 183–245 个市场；
  - 0 个未解决失败；
  - 7 个旧归档文件缺少官方 SHA-256，已标记为 `unverified_checksums`，ZIP CRC 正常；
  - 股票代币分类命中 0。
- 新增 `outputs/oi-dominance/bybit-backfill.py`，通过官方区域域名回填 Bybit linear/inverse：
  - 132 个符合报价与上线日期条件的当前合约；
  - 274 个连续日点、29,710 条合约日观测、失败 0；
  - linear 合约按同时间点日线价格换算美元，inverse 合约使用官方美元 OI；
  - 重叠期总 OI 相对 Coinalyze 的均值比例约 1.0034；
  - 当前合约目录可能遗漏已退市历史合约。
- 新增 `outputs/oi-dominance/combine-2021plus.mjs`，用于合并分段序列并计算重叠期偏差。
- 新增 `outputs/oi-dominance/run-binance-backfill.ps1`。
- Gate.io 实测旧时间请求返回 `from time exceeds 180-day limit`，不能用于 2021 回填。
- Coinalyze 2022-07-27 至 2024-09-07 增量回填完成：查询 1,007 个历史已存在的当前合约，得到 774 个连续日点。
- 2022-07-27 至 2022-07-29 的 Coinalyze 总 OI 只有约 3.8 亿美元，2022-07-30 跳升至约 140 亿美元，说明前三日覆盖不完整；最终切换日设为 2022-07-30。
- 已生成 `dominance-2021plus.csv`、`dominance-2021plus.html` 和汇总 JSON。
- 合并 HTML 已增加 BTCUSDT 现货价格曲线和右轴；日期、价格、dominance 与来源共用悬停提示。
- 新增 `outputs/oi-dominance/daily-update.ps1`：回看最近 3 个 UTC 日、合并 Coinalyze 与 BTC 价格增量、重建最终产物；同一窗口支持断点续跑。

## 最终验证

- 2021-12-01 至 2026-09-19 共 1,754 个连续日点，无缺日、无负 OI。
- BTC + ETH + Others 最大求和误差约为 `1e-8`。
- 来源只切换一次：2022-07-29 Binance + Bybit 固定交易所段 → 2022-07-30 Coinalyze 当前合约宇宙段。
- 33 日重叠期内，Binance + Bybit 相对 Coinalyze 的平均差为 BTC -2.8505 pp、ETH -1.9560 pp、Others +4.8065 pp，确认仍存在结构性覆盖偏差。
- 早期段不做平滑、缩放或主观校正，只能作为覆盖型趋势参考。
- BTC 价格右轴与价格曲线已在 1,024、736、360 像素宽度下通过浏览器验证。

## 日更边界

- Coinalyze 限制按 symbol 计算；2026-09-20 实测 5,048 个符合口径的当前合约，每日约需 126 分钟，无法通过缩短历史窗口绕过。
- API Key 已使用 Windows DPAPI 保存为当前用户专属密文，文件 ACL 仅允许当前 Windows 用户；Key 不以明文进入仓库、脚本或自动任务。
- 本地自动任务 `每日更新 OI Dominance`（automation id：`oi-dominance`）已于 2026-09-20 暂停，避免旧版全量扫描继续运行。
- 首次无人值守补更于 2026-09-20 启动，目标日期为 2026-09-19；在 100/5,048 个合约处按用户要求安全停止，未覆盖正式输出。
- 2026-09-20 12:39（北京时间）按用户确认重新以隐藏后台进程补更，复用同一窗口缓存并严格按 40 symbols/min 及 `Retry-After` 控速；14:38 完成 5,048/5,048 个合约、BTC 价格更新和最终重建。最新观测为 2026-09-19，共 1,754 日；缺日、负 OI、缺 BTC 价格均为 0，错误日志为空。
- 2026-09-23 23:47（北京时间）再次启动隐藏后台补更，目标窗口为 2026-09-17 至 2026-09-22；本次当前目录为 5,079 个合约，严格按 40 symbols/min 与 `Retry-After` 控速，预计约 127 分钟。
- 当前目录共有 5,048 个符合报价口径的合约；提前排除 822 个股票代币后仍有 4,226 个。按最近两周缓存，约 2,514 个加密合约仍活跃，因此仅做活跃过滤仍需约 63 分钟。若要进入分钟级日更，需要改用交易所批量接口，或接受“高 OI 合约每日更新 + 低频全量校验”的近似方案并量化误差。

## 仍待补的交易所

- Kraken Futures 与 Bitfinex 均有官方历史 OI 区间接口，但当前终端和浏览器网络都被客户端策略拦截，尚未落地采集。
- Gate.io 的公开接口实测只允许近 180 日，不能回填 2021。
- OKX 的历史合约 OI 端点于 2024-06 才加入；HTX、BitMEX、Deribit 的免费公开接口无法形成可靠的 2021 全市场日线。
- 切换日剩余主要缺口约为 OKX 14.04%、Deribit 5.11%、BitMEX 3.21%、dYdX 2.74%、HTX 2.33%、Bitfinex 1.26%（按 Coinalyze 当日样本占比），因此现阶段不能标为全市场复刻。
