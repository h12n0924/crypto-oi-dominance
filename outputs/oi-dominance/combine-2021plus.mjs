import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(SCRIPT_DIR, 'data');
const COINALYZE_PATH = path.join(DATA_DIR, 'dominance-cleaned.csv');
const COINALYZE_EARLY_PATH = path.join(DATA_DIR, 'coinalyze-early', 'dominance-cleaned.csv');
const BINANCE_PATH = path.join(DATA_DIR, 'binance-backfill', 'binance-dominance.csv');
const BYBIT_PATH = path.join(DATA_DIR, 'bybit-backfill', 'bybit-dominance.csv');
const BTC_PRICE_PATH = path.join(DATA_DIR, 'btc-price', 'btc-price-daily.csv');
const STABLE_COINALYZE_START = '2022-07-30';

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const columns = lines.shift().split(',');
  return lines.filter(Boolean).map((line) => {
    const values = line.split(',');
    return Object.fromEntries(columns.map((column, index) => [column, values[index] ?? '']));
  });
}

function csvCell(value) {
  if (value === null || value === undefined) return '';
  const text = String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function toCsv(rows, columns) {
  return [columns.join(','), ...rows.map((row) => columns.map((column) => csvCell(row[column])).join(','))].join('\n') + '\n';
}

function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function round(value, digits = 8) {
  return Number.isFinite(value) ? Number(value.toFixed(digits)) : null;
}

function comparison(rows, key, sourceKey = 'binance') {
  const differences = rows.map((row) => row[sourceKey][key] - row.coinalyze[key]);
  return {
    mean_signed_pp: round(differences.reduce((sum, value) => sum + value, 0) / differences.length),
    mean_absolute_pp: round(differences.reduce((sum, value) => sum + Math.abs(value), 0) / differences.length),
    max_absolute_pp: round(Math.max(...differences.map(Math.abs))),
  };
}

function buildHtml(rows, summary) {
  const data = JSON.stringify(rows.map((row) => ({
    d: row.date,
    b: row.btc_pct,
    e: row.eth_pct,
    o: row.others_pct,
    p: row.btc_price_usd,
    s: row.source_scope,
  })));
  const metadata = JSON.stringify(summary);
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OI Dominance 2021+</title><style>
:root{color-scheme:dark;font-family:Inter,"Segoe UI",sans-serif}body{margin:0;background:#111318;color:#e8ebf2}main{max-width:1180px;margin:auto;padding:28px 20px 40px}h1{margin:0 0 6px;font-size:24px}.sub,.note{color:#9ba3b3}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:18px 0}.card{background:#1a1e26;border:1px solid #2a303b;border-radius:10px;padding:12px}.card small{display:block;color:#9ba3b3}.card strong{display:block;margin-top:5px;font-size:18px}.chart{position:relative;background:#171a20;border:1px solid #2a303b;border-radius:12px;padding:12px}canvas{display:block;width:100%;height:500px;cursor:crosshair;touch-action:none}.tooltip{position:absolute;z-index:2;display:none;pointer-events:none;min-width:190px;padding:10px 12px;border:1px solid #465064;border-radius:8px;background:rgba(18,21,27,.96);box-shadow:0 8px 24px rgba(0,0,0,.32);font-size:12px;line-height:1.55;color:#e8ebf2}.tooltip strong{display:block;margin-bottom:4px;font-size:13px}.tooltip .price{margin-bottom:3px;color:#f1c979}.tooltip .row{display:flex;justify-content:space-between;gap:18px}.tooltip .source{margin-top:4px;padding-top:4px;border-top:1px solid #343b48;color:#9ba3b3}.legend{display:flex;flex-wrap:wrap;gap:16px;margin:12px 4px 4px;font-size:13px}.dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:6px}.line{width:16px;height:0;border-top:2px solid #f1c979;display:inline-block;margin:0 6px 3px 0}.note{margin-top:14px;line-height:1.6;font-size:13px}@media(max-width:760px){.grid{grid-template-columns:1fr}canvas{height:360px}}
</style></head><body><main><h1>BTC / ETH / Others OI Dominance · 2021+</h1>
<div class="sub">虚线：Binance + Bybit 固定交易所重建段；实线：Coinalyze 当前合约宇宙清洗段。悬停显示日期与 Binance BTCUSDT 现货日收盘价（UTC）。</div>
<div class="grid"><div class="card"><small>序列起点</small><strong>${summary.from}</strong></div><div class="card"><small>口径切换</small><strong>${summary.switch_date}</strong></div><div class="card"><small>重叠校验天数</small><strong>${summary.overlap_days}</strong></div></div>
<div class="chart" id="chart-wrap"><canvas id="chart" role="img" aria-label="BTC、ETH 与 Others 的每日 OI dominance，以及右轴 BTC 美元价格；鼠标悬停可查看具体日期与数值"></canvas><div class="tooltip" id="tooltip" role="tooltip"></div><div class="legend"><span><i class="dot" style="background:#3267d6"></i>BTC</span><span><i class="dot" style="background:#18a68d"></i>ETH</span><span><i class="dot" style="background:#e57932"></i>Others</span><span><i class="line"></i>BTC price · 右轴</span><span>虚线 = Binance + Bybit</span><span>实线 = Coinalyze</span></div></div>
<div class="note">⚠ ${summary.warning}</div>
<script>
const data=${data},summary=${metadata};
const c=document.getElementById('chart'),wrap=document.getElementById('chart-wrap'),tip=document.getElementById('tooltip'),x=c.getContext('2d');
const colors={b:'#3267d6',e:'#18a68d',o:'#e57932'};
const money=new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2});
const compactUsd=new Intl.NumberFormat('en-US',{notation:'compact',style:'currency',currency:'USD',maximumFractionDigits:0});
const prices=data.map(row=>row.p).filter(Number.isFinite),priceLow=Math.min(...prices),priceHigh=Math.max(...prices),pricePad=Math.max(1,(priceHigh-priceLow)*.06),priceMin=Math.max(0,priceLow-pricePad),priceMax=priceHigh+pricePad;
let hover=-1,layout=null,pinned=false;
function render(){
  const q=devicePixelRatio||1,r=c.getBoundingClientRect();
  c.width=Math.round(r.width*q);c.height=Math.round(r.height*q);x.setTransform(q,0,0,q,0,0);
  const w=r.width,h=r.height,p={l:52,r:68,t:24,b:34};layout={w,h,p};
  x.clearRect(0,0,w,h);x.font='12px Segoe UI';x.strokeStyle='#313744';x.fillStyle='#858d9b';
  for(let y=0;y<=100;y+=20){const py=p.t+(100-y)/100*(h-p.t-p.b);x.beginPath();x.moveTo(p.l,py);x.lineTo(w-p.r,py);x.stroke();x.fillText(y+'%',8,py+4)}
  x.fillStyle='#858d9b';x.fillText('OI dominance',p.l,p.t-8);const priceTitle='BTC price';x.fillText(priceTitle,w-p.r-x.measureText(priceTitle).width,p.t-8);
  for(let step=0;step<=4;step++){const value=priceMin+(priceMax-priceMin)*step/4,py=h-p.b-step/4*(h-p.t-p.b),label=compactUsd.format(value);x.fillText(label,w-p.r+8,py+4)}
  const priceY=value=>p.t+(priceMax-value)/(priceMax-priceMin)*(h-p.t-p.b);
  x.beginPath();x.strokeStyle='#f1c979';x.globalAlpha=.82;x.lineWidth=1.7;x.setLineDash([]);let priceStarted=false;data.forEach((row,i)=>{if(!Number.isFinite(row.p)){priceStarted=false;return}const px=p.l+i/Math.max(1,data.length-1)*(w-p.l-p.r),py=priceY(row.p);if(!priceStarted){x.moveTo(px,py);priceStarted=true}else{x.lineTo(px,py)}});x.stroke();x.globalAlpha=1;
  const plot=(key,color,scope,dash)=>{x.beginPath();x.strokeStyle=color;x.lineWidth=2;x.setLineDash(dash);let started=false;data.forEach((row,i)=>{if(row.s!==scope){started=false;return}const px=p.l+i/Math.max(1,data.length-1)*(w-p.l-p.r),py=p.t+(100-row[key])/100*(h-p.t-p.b);if(!started){x.moveTo(px,py);started=true}else{x.lineTo(px,py)}});x.stroke();x.setLineDash([])};
  for(const [key,color] of Object.entries(colors)){plot(key,color,'binance_bybit_fixed_venues',[6,4]);plot(key,color,'coinalyze_current_universe',[])}
  const bi=data.findIndex(row=>row.d===summary.switch_date);
  if(bi>=0){const px=p.l+bi/Math.max(1,data.length-1)*(w-p.l-p.r);x.strokeStyle='#d7ad63';x.setLineDash([3,4]);x.beginPath();x.moveTo(px,p.t);x.lineTo(px,h-p.b);x.stroke();x.setLineDash([])}
  if(data.length){x.fillStyle='#858d9b';x.fillText(data[0].d,p.l,h-8);const end=data.at(-1).d;x.fillText(end,w-p.r-x.measureText(end).width,h-8)}
  if(hover>=0)drawHover();
}
function drawHover(){
  if(!layout||hover<0)return;
  const {w,h,p}=layout,row=data[hover],px=p.l+hover/Math.max(1,data.length-1)*(w-p.l-p.r);
  x.strokeStyle='#aab2c0';x.lineWidth=1;x.setLineDash([3,3]);x.beginPath();x.moveTo(px,p.t);x.lineTo(px,h-p.b);x.stroke();x.setLineDash([]);
  for(const key of Object.keys(colors)){const py=p.t+(100-row[key])/100*(h-p.t-p.b);x.fillStyle=colors[key];x.beginPath();x.arc(px,py,4,0,Math.PI*2);x.fill();x.strokeStyle='#171a20';x.stroke()}
  const py=p.t+(priceMax-row.p)/(priceMax-priceMin)*(h-p.t-p.b);x.fillStyle='#f1c979';x.beginPath();x.arc(px,py,4,0,Math.PI*2);x.fill();x.strokeStyle='#171a20';x.stroke();
  tip.innerHTML='<strong>'+row.d+'</strong><div class="price">BTC '+money.format(row.p)+'</div><div class="row"><span>BTC dominance</span><b>'+row.b.toFixed(2)+'%</b></div><div class="row"><span>ETH dominance</span><b>'+row.e.toFixed(2)+'%</b></div><div class="row"><span>Others</span><b>'+row.o.toFixed(2)+'%</b></div><div class="source">'+(row.s==='binance_bybit_fixed_venues'?'Binance + Bybit 固定交易所段':'Coinalyze 多交易所段')+'</div>';
  tip.style.display='block';
  const preferred=c.offsetLeft+px+12,max=wrap.clientWidth-tip.offsetWidth-8;
  tip.style.left=Math.max(8,Math.min(preferred,max))+'px';tip.style.top=(c.offsetTop+p.t+8)+'px';
}
function setHover(event){
  if(!layout)return;
  const r=c.getBoundingClientRect(),{w,p}=layout,local=event.clientX-r.left;
  hover=Math.max(0,Math.min(data.length-1,Math.round((local-p.l)/(w-p.l-p.r)*(data.length-1))));render();
}
c.addEventListener('pointermove',event=>{if(!pinned)setHover(event)});
c.addEventListener('pointerleave',()=>{if(!pinned){hover=-1;tip.style.display='none';render()}});
c.addEventListener('pointerdown',event=>{setHover(event);pinned=!pinned});
addEventListener('resize',render);render();
</script></main></body></html>\n`;
}

const mapCoinalyze = (row) => ({
  date: row.date,
  all_oi_usd: number(row.crypto_oi_usd),
  btc_oi_usd: number(row.btc_oi_usd),
  eth_oi_usd: number(row.eth_oi_usd),
  others_oi_usd: number(row.others_oi_usd),
  btc_pct: number(row.btc_pct),
  eth_pct: number(row.eth_pct),
  others_pct: number(row.others_pct),
  excluded_oi_usd: number(row.excluded_oi_usd),
  source_scope: 'coinalyze_current_universe',
  quality_tier: 'high_with_survivorship_caveat',
});
const earlyCoinalyze = parseCsv(await fs.readFile(COINALYZE_EARLY_PATH, 'utf8')).map(mapCoinalyze);
const recentCoinalyze = parseCsv(await fs.readFile(COINALYZE_PATH, 'utf8')).map(mapCoinalyze);
const coinalyzeByDateCombined = new Map(earlyCoinalyze.map((row) => [row.date, row]));
for (const row of recentCoinalyze) coinalyzeByDateCombined.set(row.date, row);
const coinalyze = [...coinalyzeByDateCombined.values()]
  .filter((row) => row.date >= STABLE_COINALYZE_START)
  .sort((a, b) => a.date.localeCompare(b.date));
const binance = parseCsv(await fs.readFile(BINANCE_PATH, 'utf8')).map((row) => ({
  date: row.date,
  all_oi_usd: number(row.all_oi_usd),
  btc_oi_usd: number(row.btc_oi_usd),
  eth_oi_usd: number(row.eth_oi_usd),
  others_oi_usd: number(row.others_oi_usd),
  btc_pct: number(row.btc_pct),
  eth_pct: number(row.eth_pct),
  others_pct: number(row.others_pct),
  excluded_oi_usd: 0,
  source_scope: 'binance_fixed_venue',
  quality_tier: 'partial_exchange_coverage',
}));
const bybitByDate = new Map(
  parseCsv(await fs.readFile(BYBIT_PATH, 'utf8')).map((row) => [row.date, {
    all_oi_usd: number(row.all_oi_usd),
    btc_oi_usd: number(row.btc_oi_usd),
    eth_oi_usd: number(row.eth_oi_usd),
    others_oi_usd: number(row.others_oi_usd),
  }]),
);
const earlyVenues = binance.map((row) => {
  const bybit = bybitByDate.get(row.date);
  if (!bybit) throw new Error(`Missing Bybit observation for ${row.date}`);
  const allOi = row.all_oi_usd + bybit.all_oi_usd;
  const btcOi = row.btc_oi_usd + bybit.btc_oi_usd;
  const ethOi = row.eth_oi_usd + bybit.eth_oi_usd;
  const othersOi = row.others_oi_usd + bybit.others_oi_usd;
  return {
    ...row,
    all_oi_usd: allOi,
    btc_oi_usd: btcOi,
    eth_oi_usd: ethOi,
    others_oi_usd: othersOi,
    btc_pct: btcOi / allOi * 100,
    eth_pct: ethOi / allOi * 100,
    others_pct: othersOi / allOi * 100,
    source_scope: 'binance_bybit_fixed_venues',
    quality_tier: 'partial_multi_exchange_coverage',
  };
});
const btcPriceByDate = new Map(
  parseCsv(await fs.readFile(BTC_PRICE_PATH, 'utf8')).map((row) => [row.date, number(row.btc_price_usd)]),
);

if (!coinalyze.length || !binance.length) throw new Error('Both input series must contain observations');
const switchDate = coinalyze[0].date;
const coinalyzeByDate = new Map(coinalyze.map((row) => [row.date, row]));
const overlap = earlyVenues.filter((row) => coinalyzeByDate.has(row.date)).map((row) => ({
  earlyVenues: row,
  coinalyze: coinalyzeByDate.get(row.date),
}));
if (!overlap.length) throw new Error('No overlap dates are available for source comparison');

const combined = [
  ...earlyVenues.filter((row) => row.date < switchDate),
  ...coinalyze,
].sort((a, b) => a.date.localeCompare(b.date)).map((row) => ({
  ...row,
  btc_price_usd: btcPriceByDate.get(row.date) ?? null,
}));
const oneDayMs = 24 * 60 * 60 * 1000;
const dateGapCount = combined.slice(1).filter((row, index) => (
  Date.parse(`${row.date}T00:00:00Z`) - Date.parse(`${combined[index].date}T00:00:00Z`) !== oneDayMs
)).length;
const negativeOiRowCount = combined.filter((row) => (
  row.all_oi_usd < 0 || row.btc_oi_usd < 0 || row.eth_oi_usd < 0 || row.others_oi_usd < 0
)).length;
const missingBtcPriceRowCount = combined.filter((row) => !Number.isFinite(row.btc_price_usd)).length;
const maxPercentageSumError = Math.max(...combined.map((row) => (
  Math.abs(row.btc_pct + row.eth_pct + row.others_pct - 100)
)));
if (dateGapCount || negativeOiRowCount || missingBtcPriceRowCount) {
  throw new Error(`Combined validation failed: date gaps=${dateGapCount}, negative OI rows=${negativeOiRowCount}, missing BTC prices=${missingBtcPriceRowCount}`);
}
const summary = {
  generated_at: new Date().toISOString(),
  from: combined[0].date,
  to: combined.at(-1).date,
  observations: combined.length,
  switch_date: switchDate,
  source_observations: {
    binance_bybit_fixed_venues: combined.filter((row) => row.source_scope === 'binance_bybit_fixed_venues').length,
    coinalyze_current_universe: combined.filter((row) => row.source_scope === 'coinalyze_current_universe').length,
  },
  validation: {
    date_gap_count: dateGapCount,
    negative_oi_row_count: negativeOiRowCount,
    missing_btc_price_row_count: missingBtcPriceRowCount,
    max_percentage_sum_error: maxPercentageSumError,
  },
  overlap_from: overlap[0].earlyVenues.date,
  overlap_to: overlap.at(-1).earlyVenues.date,
  overlap_days: overlap.length,
  overlap_difference_early_venues_minus_coinalyze_pp: {
    btc: comparison(overlap, 'btc_pct', 'earlyVenues'),
    eth: comparison(overlap, 'eth_pct', 'earlyVenues'),
    others: comparison(overlap, 'others_pct', 'earlyVenues'),
  },
  early_venues: ['Binance USD-M/COIN-M', 'Bybit linear/inverse'],
  btc_price_source: 'Binance BTCUSDT spot daily close (UTC)',
  warning: '2021-12 至口径切换日前覆盖 Binance 与 Bybit，不等同于 Coinalyze 全市场；切换处仍可能存在结构性跳变。',
};
const columns = [
  'date', 'all_oi_usd', 'excluded_oi_usd', 'btc_oi_usd', 'eth_oi_usd', 'others_oi_usd',
  'btc_pct', 'eth_pct', 'others_pct', 'btc_price_usd', 'source_scope', 'quality_tier',
];
await fs.writeFile(path.join(DATA_DIR, 'dominance-2021plus.csv'), toCsv(combined, columns));
await fs.writeFile(path.join(DATA_DIR, 'dominance-2021plus-summary.json'), JSON.stringify(summary, null, 2) + '\n');
await fs.writeFile(path.join(DATA_DIR, 'dominance-2021plus.html'), buildHtml(combined, summary));
console.log(JSON.stringify(summary, null, 2));
