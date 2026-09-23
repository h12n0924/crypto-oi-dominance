#!/usr/bin/env python3
"""Download daily BTCUSDT spot closes from Binance Data Vision."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


DATA_BASE = "https://data.binance.vision/data/spot"
USER_AGENT = "oi-dominance-research/1.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--merge-existing", action="store_true")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent / "data" / "btc-price"),
    )
    return parser.parse_args()


def get_bytes(url: str, retries: int = 5) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise
            last_error = error
        except (OSError, TimeoutError, urllib.error.URLError) as error:
            last_error = error
        if attempt + 1 < retries:
            time.sleep(min(20, 2**attempt))
    raise RuntimeError(f"download failed after {retries} attempts: {url}: {last_error}")


def verify_zip(url: str, payload: bytes) -> bool | None:
    digest = hashlib.sha256(payload).hexdigest()
    try:
        checksum = get_bytes(f"{url}.CHECKSUM").decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    expected = checksum.split()[0].lower() if checksum else ""
    if not expected:
        return None
    if digest != expected:
        raise ValueError(f"SHA-256 checksum mismatch: {url}")
    return True


def read_klines(payload: bytes, source_url: str, checksum_ok: bool | None) -> list[dict[str, object]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise ValueError(f"ZIP CRC failed: {bad_file}")
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV in archive, got {names}")
        text = io.TextIOWrapper(archive.open(names[0]), encoding="utf-8-sig", newline="")
        observations: list[dict[str, object]] = []
        for row in csv.reader(text):
            if len(row) < 5 or not row[0].isdigit():
                continue
            timestamp = int(row[0])
            if timestamp >= 10**15:
                timestamp //= 1000
            day = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date().isoformat()
            observations.append(
                {
                    "date": day,
                    "btc_price_usd": float(row[4]),
                    "source_url": source_url,
                    "checksum_ok": checksum_ok,
                }
            )
        return observations


def month_starts(start: date, end: date) -> list[date]:
    current = start.replace(day=1)
    values: list[date] = []
    while current <= end:
        values.append(current)
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return values


def days_in_month(month: date, start: date, end: date) -> list[date]:
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    current = max(start, month)
    last = min(end, next_month - timedelta(days=1))
    values: list[date] = []
    while current <= last:
        values.append(current)
        current += timedelta(days=1)
    return values


def fetch_archive(url: str, cache_path: Path) -> list[dict[str, object]]:
    payload = cache_path.read_bytes() if cache_path.exists() else get_bytes(url)
    if not cache_path.exists():
        cache_path.write_bytes(payload)
    return read_klines(payload, url, verify_zip(url, payload))


def fetch_month(month: date, start: date, end: date, cache_dir: Path) -> list[dict[str, object]]:
    month_label = month.strftime("%Y-%m")
    filename = f"BTCUSDT-1d-{month_label}.zip"
    monthly_url = f"{DATA_BASE}/monthly/klines/BTCUSDT/1d/{filename}"
    try:
        return fetch_archive(monthly_url, cache_dir / filename)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    observations: list[dict[str, object]] = []
    for day in days_in_month(month, start, end):
        day_label = day.isoformat()
        filename = f"BTCUSDT-1d-{day_label}.zip"
        daily_url = f"{DATA_BASE}/daily/klines/BTCUSDT/1d/{filename}"
        observations.extend(fetch_archive(daily_url, cache_dir / filename))
    return observations


def main() -> None:
    args = parse_args()
    start = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)
    if end < start:
        raise ValueError("--to must be on or after --from")
    output_dir = Path(args.output_dir).resolve()
    cache_dir = output_dir / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(fetch_month, month, start, end, cache_dir): month
            for month in month_starts(start, end)
        }
        for future in as_completed(futures):
            rows.extend(future.result())

    by_date = {
        str(row["date"]): row
        for row in rows
        if args.from_date <= str(row["date"]) <= args.to_date
    }
    expected_days = (end - start).days + 1
    missing = [
        (start + timedelta(days=index)).isoformat()
        for index in range(expected_days)
        if (start + timedelta(days=index)).isoformat() not in by_date
    ]
    if missing:
        raise RuntimeError(f"missing BTC prices for {len(missing)} days: {missing[:10]}")

    ordered = [by_date[key] for key in sorted(by_date)]
    output_path = output_dir / "btc-price-daily.csv"
    if args.merge_existing and output_path.exists():
        with output_path.open("r", encoding="utf-8", newline="") as handle:
            existing = list(csv.DictReader(handle))
        merged = {str(row["date"]): row for row in existing}
        merged.update({str(row["date"]): row for row in ordered})
        ordered = [merged[key] for key in sorted(merged)]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("date", "btc_price_usd", "source_url", "checksum_ok"),
        )
        writer.writeheader()
        writer.writerows(ordered)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "from": ordered[0]["date"],
        "to": ordered[-1]["date"],
        "requested_from": args.from_date,
        "requested_to": args.to_date,
        "incremental_merge": args.merge_existing,
        "observations": len(ordered),
        "price_definition": "Binance BTCUSDT spot daily close (UTC)",
        "unverified_checksums": sum(str(row["checksum_ok"]).lower() != "true" for row in ordered),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
