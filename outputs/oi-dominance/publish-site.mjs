import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(scriptDir, 'data');
const siteDir = path.join(scriptDir, 'site');

await fs.rm(siteDir, { recursive: true, force: true });
await fs.mkdir(siteDir, { recursive: true });

const summary = JSON.parse(await fs.readFile(path.join(dataDir, 'dominance-2021plus-summary.json'), 'utf8'));
let html = await fs.readFile(path.join(dataDir, 'dominance-2021plus.html'), 'utf8');
const downloadStyles = `<style>
.downloads{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:0 0 18px;padding:10px 12px;background:#1a1e26;border:1px solid #2a303b;border-radius:10px;font-size:13px}
.downloads a{color:#dbe7ff;text-decoration:none;padding:6px 10px;border:1px solid #465064;border-radius:7px;background:#222834}.downloads a:hover{background:#2b3442}.downloads .fresh{margin-left:auto;color:#9ba3b3}
@media(max-width:760px){.downloads .fresh{width:100%;margin-left:0}}
</style>`;
const downloads = `<nav class="downloads" aria-label="数据下载">
<a href="dominance-2021plus.csv" download>下载 CSV</a>
<a href="oi-dominance-2021plus.xlsx" download>下载 Excel</a>
<a href="dominance-2021plus-summary.json" download>下载汇总 JSON</a>
<span class="fresh">最新完整 UTC 数据：${summary.to}</span>
</nav>`;
html = html.replace('</head>', `${downloadStyles}</head>`).replace('<body><main>', `<body><main>${downloads}`);

await Promise.all([
  fs.writeFile(path.join(siteDir, 'index.html'), html),
  fs.copyFile(path.join(dataDir, 'dominance-2021plus.csv'), path.join(siteDir, 'dominance-2021plus.csv')),
  fs.copyFile(path.join(dataDir, 'dominance-2021plus-summary.json'), path.join(siteDir, 'dominance-2021plus-summary.json')),
  fs.copyFile(path.join(dataDir, 'daily-update-status.json'), path.join(siteDir, 'daily-update-status.json')),
  fs.copyFile(path.join(dataDir, 'oi-dominance-2021plus.xlsx'), path.join(siteDir, 'oi-dominance-2021plus.xlsx')),
  fs.writeFile(path.join(siteDir, '.nojekyll'), ''),
]);
console.log(JSON.stringify({ siteDir, latest: summary.to }));

