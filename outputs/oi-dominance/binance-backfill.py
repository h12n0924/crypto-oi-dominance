#!/usr/bin/env python3
"""Reconstruct daily Binance futures OI from the public Data Vision archive.

The collector discovers the historical symbol universe from S3, verifies every
download against Binance's published SHA-256 checksum, and stores compact,
resumable observations in SQLite. USD-M OI is already reported in quote value.
COIN-M OI is reported in base-asset value and is converted with the matching
5-minute mark-price open at the observation timestamp.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import io
import json
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path


S3_ENDPOINT = "https://s3.ap-northeast-1.amazonaws.com/data.binance.vision"
DATA_BASE = "https://data.binance.vision"
S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
DATE_RE = re.compile(r"-metrics-(\d{4}-\d{2}-\d{2})\.zip$")
USER_AGENT = "oi-dominance-research/1.0"
HTTP_STATE = threading.local()


class HttpStatusError(RuntimeError):
    def __init__(self, status: int, url: str, body: bytes):
        self.status = status
        super().__init__(f"HTTP {status}: {url}: {body[:200]!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument("--market", choices=("um", "cm", "both"), default="both")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--symbols", help="Optional comma-separated smoke-test symbols")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent / "data" / "binance-backfill"),
    )
    return parser.parse_args()


def validate_date(value: str) -> str:
    date.fromisoformat(value)
    return value


def get_bytes(url: str, retries: int = 5) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            parsed = urllib.parse.urlsplit(url)
            path_and_query = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            connections = getattr(HTTP_STATE, "connections", None)
            if connections is None:
                connections = {}
                HTTP_STATE.connections = connections
            connection = connections.get(parsed.netloc)
            if connection is None:
                connection = http.client.HTTPSConnection(parsed.netloc, timeout=45)
                connections[parsed.netloc] = connection
            connection.request("GET", path_and_query, headers={"User-Agent": USER_AGENT})
            response = connection.getresponse()
            body = response.read()
            if response.status >= 400:
                raise HttpStatusError(response.status, url, body)
            return body
        except (HttpStatusError, OSError, TimeoutError, ConnectionError, http.client.HTTPException) as error:
            last_error = error
            if isinstance(error, HttpStatusError) and error.status == 404:
                raise
            connections = getattr(HTTP_STATE, "connections", {})
            connection = connections.pop(urllib.parse.urlsplit(url).netloc, None)
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            if attempt + 1 < retries:
                time.sleep(min(20, 2**attempt))
    raise RuntimeError(f"download failed after {retries} attempts: {url}: {last_error}")


def list_s3(params: dict[str, str]) -> ET.Element:
    url = f"{S3_ENDPOINT}?{urllib.parse.urlencode(params)}"
    return ET.fromstring(get_bytes(url))


def discover_symbols(market: str) -> list[str]:
    prefix = f"data/futures/{market}/daily/metrics/"
    symbols: list[str] = []
    token: str | None = None
    while True:
        params = {"list-type": "2", "prefix": prefix, "delimiter": "/", "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        root = list_s3(params)
        for node in root.findall("s3:CommonPrefixes/s3:Prefix", S3_NS):
            symbols.append(node.text.rstrip("/").rsplit("/", 1)[-1])
        truncated = root.findtext("s3:IsTruncated", default="false", namespaces=S3_NS) == "true"
        if not truncated:
            break
        token = root.findtext("s3:NextContinuationToken", namespaces=S3_NS)
        if not token:
            raise RuntimeError("S3 listing was truncated without a continuation token")
    return sorted(set(symbols))


def list_metric_tasks(market: str, symbol: str, from_date: str, to_date: str) -> list[tuple[str, str, str]]:
    prefix = f"data/futures/{market}/daily/metrics/{symbol}/"
    start_after = f"{prefix}{symbol}-metrics-{from_date}"
    root = list_s3(
        {
            "list-type": "2",
            "prefix": prefix,
            "start-after": start_after,
            "max-keys": "1000",
        }
    )
    tasks: list[tuple[str, str, str]] = []
    for node in root.findall("s3:Contents/s3:Key", S3_NS):
        key = node.text or ""
        match = DATE_RE.search(key)
        if not match:
            continue
        day = match.group(1)
        if from_date <= day <= to_date:
            tasks.append((market, symbol, key))
    return tasks


def verify_zip(key: str, payload: bytes) -> tuple[str, bool | None]:
    digest = hashlib.sha256(payload).hexdigest()
    try:
        checksum = get_bytes(f"{DATA_BASE}/{key}.CHECKSUM").decode("utf-8", errors="replace").strip()
    except HttpStatusError as error:
        if error.status == 404:
            return digest, None
        raise
    expected = checksum.split()[0].lower() if checksum else ""
    if not expected:
        return digest, None
    if digest != expected:
        raise ValueError(f"SHA-256 checksum mismatch: {key}")
    return digest, True


def read_metric(payload: bytes) -> dict[str, object]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise ValueError(f"ZIP CRC failed: {bad_file}")
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV in metrics ZIP, got {names}")
        text = io.TextIOWrapper(archive.open(names[0]), encoding="utf-8-sig", newline="")
        rows = 0
        last: dict[str, str] | None = None
        for row in csv.DictReader(text):
            if row.get("create_time") and row.get("sum_open_interest_value"):
                last = row
                rows += 1
        if not last:
            raise ValueError("metrics CSV has no usable rows")
        return {
            "create_time": last["create_time"],
            "oi_contracts": float(last["sum_open_interest"]),
            "oi_value": float(last["sum_open_interest_value"]),
            "metric_rows": rows,
        }


def read_mark_price(payload: bytes, target_time: str) -> float:
    target = int(datetime.strptime(target_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    best_distance: int | None = None
    best_price: float | None = None
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise ValueError(f"mark-price ZIP CRC failed: {bad_file}")
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV in mark-price ZIP, got {names}")
        text = io.TextIOWrapper(archive.open(names[0]), encoding="utf-8-sig", newline="")
        reader = csv.reader(text)
        for row in reader:
            if not row or not row[0].isdigit():
                continue
            timestamp = int(row[0]) // 1000
            distance = abs(timestamp - target)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_price = float(row[1])
    if best_price is None or best_distance is None or best_distance > 300:
        raise ValueError(f"no mark price within five minutes of {target_time}")
    return best_price


def base_asset(market: str, symbol: str) -> str:
    if market == "um":
        match = re.match(r"^(.+?)(?:USDT|BUSD|USDC|FDUSD)(?:_\d+)?$", symbol)
    else:
        match = re.match(r"^(.+?)USD(?:_PERP|_\d+)$", symbol)
    return match.group(1) if match else symbol


def collect_task(task: tuple[str, str, str]) -> dict[str, object]:
    market, symbol, key = task
    match = DATE_RE.search(key)
    if not match:
        raise ValueError(f"cannot parse date from {key}")
    day = match.group(1)
    payload = get_bytes(f"{DATA_BASE}/{key}")
    digest, checksum_ok = verify_zip(key, payload)
    metric = read_metric(payload)
    mark_price: float | None = None
    oi_usd = float(metric["oi_value"])
    if market == "cm":
        mark_key = (
            f"data/futures/cm/daily/markPriceKlines/{symbol}/5m/"
            f"{symbol}-5m-{day}.zip"
        )
        mark_payload = get_bytes(f"{DATA_BASE}/{mark_key}")
        mark_digest, mark_checksum_ok = verify_zip(mark_key, mark_payload)
        checksum_ok = checksum_ok is True and mark_checksum_ok is True
        mark_price = read_mark_price(mark_payload, str(metric["create_time"]))
        oi_usd *= mark_price
    end_of_day = datetime.fromisoformat(f"{day}T23:59:59+00:00")
    observation_time = datetime.strptime(str(metric["create_time"]), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    stale_minutes = max(0.0, (end_of_day - observation_time).total_seconds() / 60)
    return {
        "market_type": market,
        "symbol": symbol,
        "base_asset": base_asset(market, symbol),
        "date": day,
        "create_time": metric["create_time"],
        "oi_contracts": metric["oi_contracts"],
        "oi_value": metric["oi_value"],
        "mark_price": mark_price,
        "oi_usd": oi_usd,
        "metric_rows": metric["metric_rows"],
        "stale_minutes": stale_minutes,
        "source_url": f"{DATA_BASE}/{key}",
        "sha256": digest,
        "checksum_ok": int(checksum_ok is True),
    }


def open_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS observations (
          market_type TEXT NOT NULL,
          symbol TEXT NOT NULL,
          base_asset TEXT NOT NULL,
          date TEXT NOT NULL,
          create_time TEXT NOT NULL,
          oi_contracts REAL NOT NULL,
          oi_value REAL NOT NULL,
          mark_price REAL,
          oi_usd REAL NOT NULL,
          metric_rows INTEGER NOT NULL,
          stale_minutes REAL NOT NULL,
          source_url TEXT NOT NULL,
          sha256 TEXT NOT NULL,
          checksum_ok INTEGER NOT NULL,
          PRIMARY KEY (market_type, symbol, date)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS failures (
          market_type TEXT NOT NULL,
          symbol TEXT NOT NULL,
          date TEXT NOT NULL,
          source_key TEXT NOT NULL,
          error TEXT NOT NULL,
          recorded_at TEXT NOT NULL,
          PRIMARY KEY (market_type, symbol, date)
        )
        """
    )
    connection.commit()
    return connection


def insert_observation(connection: sqlite3.Connection, row: dict[str, object]) -> None:
    columns = list(row)
    connection.execute(
        f"INSERT OR REPLACE INTO observations ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        [row[column] for column in columns],
    )
    connection.execute(
        "DELETE FROM failures WHERE market_type=? AND symbol=? AND date=?",
        (row["market_type"], row["symbol"], row["date"]),
    )


def export_outputs(connection: sqlite3.Connection, output_dir: Path, from_date: str, to_date: str) -> None:
    detail_columns = [item[1] for item in connection.execute("PRAGMA table_info(observations)")]
    detail_rows = connection.execute(
        "SELECT * FROM observations WHERE date BETWEEN ? AND ? ORDER BY date, market_type, symbol",
        (from_date, to_date),
    ).fetchall()
    with (output_dir / "binance-daily-by-symbol.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(detail_columns)
        writer.writerows(detail_rows)

    aggregate = connection.execute(
        """
        SELECT date,
               SUM(oi_usd) AS all_oi_usd,
               SUM(CASE WHEN base_asset='BTC' THEN oi_usd ELSE 0 END) AS btc_oi_usd,
               SUM(CASE WHEN base_asset='ETH' THEN oi_usd ELSE 0 END) AS eth_oi_usd,
               COUNT(*) AS market_count,
               SUM(CASE WHEN checksum_ok=0 THEN 1 ELSE 0 END) AS unverified_checksums,
               MAX(stale_minutes) AS max_stale_minutes
        FROM observations
        WHERE date BETWEEN ? AND ?
        GROUP BY date
        ORDER BY date
        """,
        (from_date, to_date),
    ).fetchall()
    aggregate_columns = [
        "date", "all_oi_usd", "btc_oi_usd", "eth_oi_usd", "others_oi_usd",
        "btc_pct", "eth_pct", "others_pct", "market_count", "unverified_checksums", "max_stale_minutes",
    ]
    output_rows: list[dict[str, object]] = []
    for day, total, btc, eth, market_count, unverified_checksums, max_stale in aggregate:
        others = total - btc - eth
        output_rows.append(
            {
                "date": day,
                "all_oi_usd": round(total, 2),
                "btc_oi_usd": round(btc, 2),
                "eth_oi_usd": round(eth, 2),
                "others_oi_usd": round(others, 2),
                "btc_pct": round(btc / total * 100, 8) if total else None,
                "eth_pct": round(eth / total * 100, 8) if total else None,
                "others_pct": round(others / total * 100, 8) if total else None,
                "market_count": market_count,
                "unverified_checksums": unverified_checksums,
                "max_stale_minutes": round(max_stale, 2),
            }
        )
    with (output_dir / "binance-dominance.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=aggregate_columns)
        writer.writeheader()
        writer.writerows(output_rows)

    failure_count = connection.execute(
        "SELECT COUNT(*) FROM failures WHERE date BETWEEN ? AND ?", (from_date, to_date)
    ).fetchone()[0]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "from": from_date,
        "to": to_date,
        "observations": len(detail_rows),
        "days": len(output_rows),
        "failure_count": failure_count,
        "first": output_rows[0] if output_rows else None,
        "last": output_rows[-1] if output_rows else None,
        "limitations": [
            "Binance-only fixed-venue series; not Coinalyze global dominance",
            "Archive gaps are retained as missing observations and recorded in SQLite",
            "COIN-M USD value uses the closest 5-minute mark price",
        ],
    }
    (output_dir / "binance-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    from_date = validate_date(args.from_date)
    to_date = validate_date(args.to_date)
    if from_date > to_date:
        raise ValueError("--from must not be after --to")
    if args.workers < 1 or args.workers > 64:
        raise ValueError("--workers must be between 1 and 64")
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    connection = open_database(output_dir / "binance-archive.sqlite")
    requested = {item.strip().upper() for item in args.symbols.split(",")} if args.symbols else None
    markets = ("um", "cm") if args.market == "both" else (args.market,)

    all_tasks: list[tuple[str, str, str]] = []
    for market in markets:
        symbols = sorted(requested) if requested else discover_symbols(market)
        print(json.dumps({"event": "symbols", "market": market, "count": len(symbols)}), flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(list_metric_tasks, market, symbol, from_date, to_date): symbol
                for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    all_tasks.extend(future.result())
                except Exception as error:
                    print(json.dumps({"event": "list_error", "market": market, "symbol": symbol, "error": str(error)}), flush=True)

    existing = {
        (row[0], row[1], row[2])
        for row in connection.execute(
            "SELECT market_type, symbol, date FROM observations WHERE date BETWEEN ? AND ?",
            (from_date, to_date),
        )
    }
    pending = []
    for task in sorted(set(all_tasks)):
        market, symbol, key = task
        day = DATE_RE.search(key).group(1)
        if (market, symbol, day) not in existing:
            pending.append(task)
    print(json.dumps({"event": "tasks", "discovered": len(set(all_tasks)), "cached": len(existing), "pending": len(pending)}), flush=True)

    completed = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(collect_task, task): task for task in pending}
        for future in as_completed(futures):
            market, symbol, key = futures[future]
            day = DATE_RE.search(key).group(1)
            try:
                row = future.result()
                insert_observation(connection, row)
            except Exception as error:
                failed += 1
                connection.execute(
                    "INSERT OR REPLACE INTO failures VALUES (?,?,?,?,?,?)",
                    (market, symbol, day, key, str(error), datetime.now(timezone.utc).isoformat()),
                )
            completed += 1
            if completed % 100 == 0 or completed == len(pending):
                connection.commit()
                print(json.dumps({"event": "progress", "completed": completed, "pending": len(pending), "failed": failed}), flush=True)
    connection.commit()
    export_outputs(connection, output_dir, from_date, to_date)
    print(json.dumps({"event": "done", "output": str(output_dir), "failed": failed}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted; completed observations remain in SQLite for resume.", file=sys.stderr)
        raise SystemExit(130)
