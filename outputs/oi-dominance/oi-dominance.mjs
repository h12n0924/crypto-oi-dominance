import { createHash } from 'node:crypto';
import fsSync from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const API_BASE = 'https://api.coinalyze.net/v1';
const BATCH_SIZE = 20;
const SYMBOLS_PER_MINUTE = 40;
const WINDOW_MS = 60_000;

function parseArgs(argv) {
  const options = {};
  for (const arg of argv) {
    if (!arg.startsWith('--')) continue;
    const separator = arg.indexOf('=');
    const key = separator === -1 ? arg.slice(2) : arg.slice(2, separator);
    options[key] = separator === -1 ? true : arg.slice(separator + 1);
  }
  return options;
}

function assertDate(value, name) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) {
    throw new Error(`${name} must be YYYY-MM-DD; received ${value}`);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function chunks(values, size) {
  const result = [];
  for (let index = 0; index < values.length; index += size) {
    result.push(values.slice(index, index + size));
  }
  return result;
}

function csvCell(value) {
  if (value === null || value === undefined) return '';
  const text = String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function toCsv(rows, columns) {
  return [
    columns.join(','),
    ...rows.map((row) => columns.map((column) => csvCell(row[column])).join(',')),
  ].join('\n') + '\n';
}

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  if (!lines.length || !lines[0]) return [];
  const columns = lines.shift().split(',');
  return lines.filter(Boolean).map((line) => {
    const values = line.split(',');
    return Object.fromEntries(columns.map((column, index) => [column, values[index] ?? '']));
  });
}

function safeNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function round(value, digits = 8) {
  return Number.isFinite(value) ? Number(value.toFixed(digits)) : null;
}

function cacheName(symbol) {
  const readable = symbol.replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, 80);
  const hash = createHash('sha256').update(symbol).digest('hex').slice(0, 10);
  return `${readable}-${hash}.json`;
}

function buildHtml(rows, summary) {
  const payload = JSON.stringify(rows.map((row) => ({
    d: row.date,
    b: row.btc_pct,
    e: row.eth_pct,
    o: row.others_pct,
    rb: row.raw_btc_pct,
    re: row.raw_eth_pct,
    x: row.excluded_oi_pct,
  })));
  const summaryPayload = JSON.stringify(summary);
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Crypto-only OI Dominance</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, "Segoe UI", sans-serif; }
    body { margin: 0; background: #111318; color: #e8ebf2; }
    main { max-width: 1160px; margin: 0 auto; padding: 28px 20px 40px; }
    h1 { margin: 0 0 6px; font-size: 24px; }
    .sub { color: #949baa; margin-bottom: 20px; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 10px; margin-bottom: 16px; }
    .card { background: #1a1e26; border: 1px solid #2a303b; border-radius: 10px; padding: 12px; }
    .card small { color: #949baa; display: block; }
    .card strong { display: block; font-size: 20px; margin-top: 5px; }
    .chart { position: relative; background: #171a20; border: 1px solid #2a303b; border-radius: 12px; padding: 12px; }
    canvas { display: block; width: 100%; height: 500px; }
    #tip { position: absolute; display: none; pointer-events: none; background: #0b0d11ee; border: 1px solid #3b4350; border-radius: 8px; padding: 8px 10px; font-size: 12px; line-height: 1.55; }
    .legend { display: flex; flex-wrap: wrap; gap: 16px; margin: 12px 4px 4px; color: #c8cdd7; font-size: 13px; }
    .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; margin-right: 6px; }
    .warn { margin-top: 14px; color: #d7ad63; font-size: 13px; }
    @media (max-width: 760px) { .grid { grid-template-columns: repeat(2, 1fr); } canvas { height: 360px; } }
  </style>
</head>
<body><main>
  <h1>Crypto-only OI Dominance</h1>
  <div class="sub">Coinalyze 日频 OI · 已剔除 Tokenized stock · ${summary.from} — ${summary.to}</div>
  <div class="grid">
    <div class="card"><small>BTC</small><strong id="btc">—</strong></div>
    <div class="card"><small>ETH</small><strong id="eth">—</strong></div>
    <div class="card"><small>Others</small><strong id="others">—</strong></div>
    <div class="card"><small>剔除占原始 OI</small><strong id="excluded">—</strong></div>
  </div>
  <div class="chart">
    <canvas id="chart"></canvas><div id="tip"></div>
    <div class="legend">
      <span><i class="dot" style="background:#3267d6"></i>BTC cleaned</span>
      <span><i class="dot" style="background:#18a68d"></i>ETH cleaned</span>
      <span><i class="dot" style="background:#e57932"></i>Others cleaned</span>
      <span><i class="dot" style="background:#c47cff"></i>Excluded share</span>
    </div>
  </div>
  <div class="warn">${summary.historical_universe_filter_date
    ? `⚠ 历史扩展仅使用在 ${summary.historical_universe_filter_date} 已有记录的合约；仍会遗漏此前已退市合约。`
    : summary.partial
      ? '⚠ 当前为部分合约测试结果，不能用于市场结论。'
      : '注意：当前合约清单会遗漏已下架的历史合约；详见 README。'}</div>
</main>
<script>
const data=${payload}; const summary=${summaryPayload};
const latest=data.at(-1)||{};
for (const [id,key] of [['btc','b'],['eth','e'],['others','o'],['excluded','x']]) {
  document.getElementById(id).textContent = Number.isFinite(latest[key]) ? latest[key].toFixed(2)+'%' : '—';
}
const canvas=document.getElementById('chart'), tip=document.getElementById('tip'), ctx=canvas.getContext('2d');
const colors={b:'#3267d6',e:'#18a68d',o:'#e57932',x:'#c47cff'};
let dims;
function render(){
  const ratio=devicePixelRatio||1, rect=canvas.getBoundingClientRect();
  canvas.width=Math.round(rect.width*ratio); canvas.height=Math.round(rect.height*ratio); ctx.setTransform(ratio,0,0,ratio,0,0);
  const w=rect.width,h=rect.height,p={l:52,r:18,t:18,b:34}; dims={w,h,p}; ctx.clearRect(0,0,w,h);
  ctx.font='12px Segoe UI'; ctx.strokeStyle='#313744'; ctx.fillStyle='#858d9b'; ctx.lineWidth=1;
  for(let y=0;y<=100;y+=20){const py=p.t+(100-y)/100*(h-p.t-p.b);ctx.beginPath();ctx.moveTo(p.l,py);ctx.lineTo(w-p.r,py);ctx.stroke();ctx.fillText(y+'%',8,py+4)}
  const plot=(key,color,dash=[])=>{ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=2;ctx.setLineDash(dash);data.forEach((r,i)=>{const x=p.l+i/Math.max(1,data.length-1)*(w-p.l-p.r),y=p.t+(100-r[key])/100*(h-p.t-p.b);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();ctx.setLineDash([])};
  plot('b',colors.b); plot('e',colors.e); plot('o',colors.o); plot('x',colors.x,[5,4]);
  if(data.length){ctx.fillStyle='#858d9b';ctx.fillText(data[0].d,p.l,h-8);const end=data.at(-1).d;ctx.fillText(end,w-p.r-ctx.measureText(end).width,h-8)}
}
canvas.addEventListener('mousemove',ev=>{if(!data.length)return;const r=canvas.getBoundingClientRect(),p=dims.p;const x=Math.max(p.l,Math.min(ev.clientX-r.left,dims.w-p.r));const i=Math.round((x-p.l)/(dims.w-p.l-p.r)*Math.max(1,data.length-1));const row=data[Math.min(i,data.length-1)];tip.style.display='block';tip.style.left=Math.min(x+12,dims.w-170)+'px';tip.style.top='24px';tip.innerHTML='<b>'+row.d+'</b><br>BTC '+row.b.toFixed(2)+'%<br>ETH '+row.e.toFixed(2)+'%<br>Others '+row.o.toFixed(2)+'%<br>Excluded '+row.x.toFixed(2)+'%'});
canvas.addEventListener('mouseleave',()=>tip.style.display='none'); addEventListener('resize',render); render();
</script></body></html>\n`;
}

const options = parseArgs(process.argv.slice(2));
const offline = Boolean(options.offline);
const mergeExisting = Boolean(options['merge-existing']);
const today = new Date().toISOString().slice(0, 10);
const twoYearsAgo = new Date(Date.now() - 730 * 86_400_000).toISOString().slice(0, 10);
const from = String(options.from || twoYearsAgo);
const to = String(options.to || today);
assertDate(from, '--from');
assertDate(to, '--to');
if (from > to) throw new Error('--from must be before or equal to --to');

const apiKey = process.env.COINALYZE_API_KEY;
if (!offline && !apiKey) throw new Error('COINALYZE_API_KEY is not set. Use run.ps1 or set the variable for this process.');

const outputDir = path.resolve(String(options['output-dir'] || path.join(SCRIPT_DIR, 'data')));
const cacheDir = options['cache-dir']
  ? path.resolve(String(options['cache-dir']))
  : path.join(outputDir, '.cache', mergeExisting ? 'incremental_daily' : `${from}_${to}_daily`);
await fs.mkdir(cacheDir, { recursive: true });
const lockPath = path.join(outputDir, '.run.lock');
try {
  fsSync.writeFileSync(lockPath, `${JSON.stringify({ pid: process.pid, started_at: new Date().toISOString(), from, to })}\n`, { flag: 'wx' });
} catch (error) {
  if (error?.code === 'EEXIST') {
    throw new Error(`Another run may already be using this output directory: ${lockPath}`);
  }
  throw error;
}
process.on('exit', () => {
  try { fsSync.unlinkSync(lockPath); } catch {}
});

const classification = JSON.parse(await fs.readFile(path.join(SCRIPT_DIR, 'non-crypto-underlyings.json'), 'utf8'));
const excludedAssets = new Set(classification.base_assets.map((asset) => asset.toUpperCase()));
const exemptSymbols = new Set((classification.exempt_symbols || []).map(String));
const isMarketExcluded = (market) => excludedAssets.has(String(market.base_asset).toUpperCase()) && !exemptSymbols.has(market.symbol);
const requestedAssets = options.assets
  ? new Set(String(options.assets).split(',').map((asset) => asset.trim().toUpperCase()).filter(Boolean))
  : null;
const requestedSymbols = options.symbols
  ? new Set(String(options.symbols).split(',').map((symbol) => symbol.trim()).filter(Boolean))
  : null;
const requireHistoryAt = options['require-history-at'] ? String(options['require-history-at']) : null;
const historyCacheDir = options['history-cache-dir']
  ? path.resolve(String(options['history-cache-dir']))
  : null;
if (requireHistoryAt) {
  assertDate(requireHistoryAt, '--require-history-at');
  if (!historyCacheDir) throw new Error('--history-cache-dir is required with --require-history-at');
}
const maxSymbols = options['max-symbols'] ? Number(options['max-symbols']) : null;
if (maxSymbols !== null && (!Number.isInteger(maxSymbols) || maxSymbols < 1)) {
  throw new Error('--max-symbols must be a positive integer');
}

const quotaTimestamps = [];
async function waitForQuota(cost) {
  while (true) {
    const now = Date.now();
    while (quotaTimestamps.length && now - quotaTimestamps[0] >= WINDOW_MS) quotaTimestamps.shift();
    if (quotaTimestamps.length + cost <= SYMBOLS_PER_MINUTE) {
      quotaTimestamps.push(...Array(cost).fill(now));
      return;
    }
    const waitMs = Math.max(250, WINDOW_MS - (now - quotaTimestamps[0]) + 250);
    console.log(`Rate window full; waiting ${Math.ceil(waitMs / 1000)}s...`);
    await sleep(waitMs);
  }
}

async function apiJson(endpoint, parameters = {}, symbolCost = 0) {
  const url = new URL(`${API_BASE}/${endpoint}`);
  for (const [key, value] of Object.entries(parameters)) url.searchParams.set(key, value);
  let attempt = 0;
  while (true) {
    if (symbolCost) await waitForQuota(symbolCost);
    const response = await fetch(url, { headers: { api_key: apiKey } });
    const body = await response.text();
    if (response.ok) return JSON.parse(body);
    if (response.status === 429) {
      const retryAfter = Number(response.headers.get('retry-after'));
      const waitMs = Number.isFinite(retryAfter) && retryAfter >= 0 ? (retryAfter + 1) * 1000 : 61_000;
      console.log(`API returned 429; respecting Retry-After and waiting ${Math.ceil(waitMs / 1000)}s...`);
      await sleep(waitMs);
      attempt += 1;
      if (attempt <= 8) continue;
    }
    if (response.status >= 500 && attempt < 5) {
      const waitMs = Math.min(30_000, 1000 * (2 ** attempt));
      console.log(`API returned ${response.status}; retrying in ${waitMs / 1000}s...`);
      await sleep(waitMs);
      attempt += 1;
      continue;
    }
    throw new Error(`${endpoint} failed with HTTP ${response.status}: ${body.slice(0, 300)}`);
  }
}

console.log('Loading Coinalyze future markets...');
const marketsPath = path.join(outputDir, 'future-markets.json');
const allMarkets = offline
  ? JSON.parse(await fs.readFile(marketsPath, 'utf8'))
  : await apiJson('future-markets');
if (!offline) await fs.writeFile(marketsPath, `${JSON.stringify(allMarkets, null, 2)}\n`);

const eligibleQuotes = new Set(['USD', 'USDT', 'BUSD']);
let markets = allMarkets.filter((market) => eligibleQuotes.has(String(market.quote_asset).toUpperCase()));
const eligibleCurrentMarketCount = markets.length;
if (requestedAssets) markets = markets.filter((market) => requestedAssets.has(String(market.base_asset).toUpperCase()));
if (requestedSymbols) markets = markets.filter((market) => requestedSymbols.has(market.symbol));
if (requireHistoryAt) {
  const cutoffUnix = Math.floor(Date.parse(`${requireHistoryAt}T23:59:59Z`) / 1000);
  const retained = [];
  let seedMissing = 0;
  let seedEmpty = 0;
  let launchedLater = 0;
  for (const market of markets) {
    try {
      const record = JSON.parse(await fs.readFile(path.join(historyCacheDir, cacheName(market.symbol)), 'utf8'));
      if (!Array.isArray(record.history) || record.history.length === 0) {
        seedEmpty += 1;
      } else if (Number(record.history[0].t) <= cutoffUnix) {
        retained.push(market);
      } else {
        launchedLater += 1;
      }
    } catch {
      seedMissing += 1;
    }
  }
  markets = retained;
  console.log(JSON.stringify({
    historicalUniverseFilter: requireHistoryAt,
    historyCacheDir,
    retained: retained.length,
    seedMissing,
    seedEmpty,
    launchedLater,
  }, null, 2));
}
markets.sort((a, b) => a.symbol.localeCompare(b.symbol));
const eligibleBeforeLimit = markets.length;
if (maxSymbols !== null) markets = markets.slice(0, maxSymbols);
const partial = Boolean(requestedAssets || requestedSymbols || requireHistoryAt || maxSymbols !== null);

const cached = new Map();
const missing = [];
for (const market of markets) {
  const cachePath = path.join(cacheDir, cacheName(market.symbol));
  try {
    const value = JSON.parse(await fs.readFile(cachePath, 'utf8'));
    if (value.symbol !== market.symbol || !Array.isArray(value.history)) throw new Error('invalid cache');
    if (mergeExisting && !offline && (value.query_from !== from || value.query_to !== to)) throw new Error('stale incremental cache');
    cached.set(market.symbol, value);
  } catch {
    missing.push(market);
  }
}

console.log(JSON.stringify({
  totalMarkets: allMarkets.length,
  eligibleMarkets: eligibleBeforeLimit,
  selectedMarkets: markets.length,
  cachedSymbols: cached.size,
  missingSymbols: missing.length,
  estimatedMinimumMinutesForMissing: round(missing.length / SYMBOLS_PER_MINUTE, 2),
  partial,
}, null, 2));
if (offline && missing.length) {
  throw new Error(`Offline mode cannot fetch ${missing.length} missing symbols`);
}

const fromUnix = Math.floor(Date.parse(`${from}T00:00:00Z`) / 1000);
const toUnix = Math.floor(Date.parse(`${to}T23:59:59Z`) / 1000);
let completed = cached.size;
for (const batch of chunks(missing, BATCH_SIZE)) {
  const symbols = batch.map((market) => market.symbol).join(',');
  const results = await apiJson('open-interest-history', {
    symbols,
    interval: 'daily',
    from: String(fromUnix),
    to: String(toUnix),
    convert_to_usd: 'true',
  }, batch.length);
  const bySymbol = new Map(results.map((item) => [item.symbol, item]));
  for (const market of batch) {
    const item = bySymbol.get(market.symbol) || { symbol: market.symbol, history: [] };
    const record = { symbol: market.symbol, fetched_at: new Date().toISOString(), query_from: from, query_to: to, history: item.history || [] };
    await fs.writeFile(path.join(cacheDir, cacheName(market.symbol)), `${JSON.stringify(record)}\n`);
    cached.set(market.symbol, record);
  }
  completed += batch.length;
  console.log(`Progress ${completed}/${markets.length} symbols (${round(completed / markets.length * 100, 1)}%)`);
}

const daily = new Map();
const excludedDailyByAsset = new Map();
for (const market of markets) {
  const baseAsset = String(market.base_asset).toUpperCase();
  const isExcluded = isMarketExcluded(market);
  const item = cached.get(market.symbol);
  for (const point of item?.history || []) {
    const timestamp = Number(point.t);
    const close = safeNumber(point.c);
    if (!Number.isFinite(timestamp) || timestamp < fromUnix || timestamp > toUnix || close === null || close < 0) continue;
    const bucket = daily.get(timestamp) || { all: 0, excluded: 0, btc: 0, eth: 0 };
    bucket.all += close;
    if (isExcluded) bucket.excluded += close;
    if (baseAsset === 'BTC') bucket.btc += close;
    if (baseAsset === 'ETH') bucket.eth += close;
    daily.set(timestamp, bucket);
    if (isExcluded) {
      if (!excludedDailyByAsset.has(baseAsset)) excludedDailyByAsset.set(baseAsset, new Map());
      const assetDaily = excludedDailyByAsset.get(baseAsset);
      assetDaily.set(timestamp, (assetDaily.get(timestamp) || 0) + close);
    }
  }
}

let rows = [...daily.entries()].sort(([a], [b]) => a - b).map(([timestamp, value]) => {
  const crypto = value.all - value.excluded;
  const others = crypto - value.btc - value.eth;
  return {
    date: new Date(timestamp * 1000).toISOString().slice(0, 10),
    timestamp,
    all_oi_usd: round(value.all, 2),
    excluded_oi_usd: round(value.excluded, 2),
    crypto_oi_usd: round(crypto, 2),
    btc_oi_usd: round(value.btc, 2),
    eth_oi_usd: round(value.eth, 2),
    others_oi_usd: round(others, 2),
    raw_btc_pct: value.all > 0 ? round(value.btc / value.all * 100) : null,
    raw_eth_pct: value.all > 0 ? round(value.eth / value.all * 100) : null,
    raw_others_pct: value.all > 0 ? round((value.all - value.btc - value.eth) / value.all * 100) : null,
    excluded_oi_pct: value.all > 0 ? round(value.excluded / value.all * 100) : null,
    btc_pct: crypto > 0 ? round(value.btc / crypto * 100) : null,
    eth_pct: crypto > 0 ? round(value.eth / crypto * 100) : null,
    others_pct: crypto > 0 ? round(others / crypto * 100) : null,
  };
}).filter((row) => row.all_oi_usd > 0);

let retainedExistingRows = 0;
if (mergeExisting) {
  const existingPath = path.join(outputDir, 'dominance-cleaned.csv');
  try {
    const numericColumns = new Set([
      'timestamp', 'all_oi_usd', 'excluded_oi_usd', 'crypto_oi_usd', 'btc_oi_usd', 'eth_oi_usd',
      'others_oi_usd', 'raw_btc_pct', 'raw_eth_pct', 'raw_others_pct', 'excluded_oi_pct', 'btc_pct', 'eth_pct', 'others_pct',
    ]);
    const existingRows = parseCsv(await fs.readFile(existingPath, 'utf8')).map((row) => Object.fromEntries(
      Object.entries(row).map(([key, value]) => [key, numericColumns.has(key) ? safeNumber(value) : value]),
    ));
    const byDate = new Map(existingRows.map((row) => [row.date, row]));
    for (const row of rows) byDate.set(row.date, row);
    retainedExistingRows = existingRows.filter((row) => !rows.some((fresh) => fresh.date === row.date)).length;
    rows = [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
}

if (!rows.length) throw new Error('No daily OI observations were returned');

const latestTimestamp = rows.length ? rows.at(-1).timestamp : null;
const excludedRows = [...excludedDailyByAsset.entries()].map(([base_asset, values]) => ({
  base_asset,
  oi_usd: latestTimestamp === null ? 0 : round(values.get(latestTimestamp) || 0, 2),
})).filter((row) => row.oi_usd > 0).sort((a, b) => b.oi_usd - a.oi_usd);

const summary = {
  generated_at: new Date().toISOString(),
  from: rows[0].date,
  to: rows.at(-1).date,
  requested_from: from,
  requested_to: to,
  incremental_merge: mergeExisting,
  retained_existing_observations: retainedExistingRows,
  interval: 'daily',
  partial,
  requested_assets: requestedAssets ? [...requestedAssets] : null,
  requested_symbols: requestedSymbols ? [...requestedSymbols] : null,
  max_symbols: maxSymbols,
  current_future_market_count: allMarkets.length,
  eligible_current_market_count: eligibleCurrentMarketCount,
  eligible_market_count_before_test_limit: eligibleBeforeLimit,
  processed_market_count: markets.length,
  exchange_count: new Set(markets.map((market) => market.exchange)).size,
  excluded_classification_snapshot: classification.snapshot_date,
  excluded_configured_asset_count: excludedAssets.size,
  excluded_present_market_count: markets.filter(isMarketExcluded).length,
  excluded_symbol_exemptions: [...exemptSymbols],
  historical_universe_filter_date: requireHistoryAt,
  historical_universe_seed_cache: historyCacheDir,
  observations: rows.length,
  latest: rows.at(-1) || null,
  limitations: [
    'future-markets is a current universe; delisted historical contracts may be missing',
    'tokenized-stock classification is a point-in-time snapshot and needs periodic review',
    'Others is a residual category',
  ],
};

const columns = [
  'date', 'timestamp', 'all_oi_usd', 'excluded_oi_usd', 'crypto_oi_usd', 'btc_oi_usd', 'eth_oi_usd',
  'others_oi_usd', 'raw_btc_pct', 'raw_eth_pct', 'raw_others_pct', 'excluded_oi_pct', 'btc_pct', 'eth_pct', 'others_pct',
];
await fs.writeFile(path.join(outputDir, 'dominance-cleaned.csv'), toCsv(rows, columns));
await fs.writeFile(path.join(outputDir, 'excluded-underlyings.csv'), toCsv(excludedRows, ['base_asset', 'oi_usd']));
await fs.writeFile(path.join(outputDir, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`);
await fs.writeFile(path.join(outputDir, 'dominance-cleaned.html'), buildHtml(rows, summary));
console.log(`Done. Output: ${outputDir}`);
