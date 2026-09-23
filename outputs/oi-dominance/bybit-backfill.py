#!/usr/bin/env python3
"""Backfill Bybit futures OI using the public V5 API."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


USER_AGENT = "oi-dominance-research/1.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--base-url", default="https://api.bybit.kz")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent / "data" / "bybit-backfill"),
    )
    return parser.parse_args()


def get_json(base_url: str, endpoint: str, params: dict[str, object], retries: int = 6) -> dict:
    url = f"{base_url}{endpoint}?{urllib.parse.urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.load(response)
            if payload.get("retCode") != 0:
                raise RuntimeError(f"Bybit error {payload.get('retCode')}: {payload.get('retMsg')}: {url}")
            return payload
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as error:
            last_error = error
            if attempt + 1 < retries:
                time.sleep(min(20, 2**attempt))
    raise RuntimeError(f"request failed after {retries} attempts: {url}: {last_error}")


def discover_instruments(base_url: str) -> list[dict[str, object]]:
    instruments: list[dict[str, object]] = []
    for category in ("linear", "inverse"):
        cursor = ""
        while True:
            params: dict[str, object] = {"category": category, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            result = get_json(base_url, "/v5/market/instruments-info", params)["result"]
            for item in result.get("list", []):
                instruments.append(
                    {
                        "category": category,
                        "symbol": item["symbol"],
                        "base_asset": item["baseCoin"],
                        "quote_asset": item["quoteCoin"],
                        "launch_time": int(item["launchTime"]),
                        "contract_type": item["contractType"],
                    }
                )
            cursor = result.get("nextPageCursor") or ""
            if not cursor:
                break
    return instruments


def date_chunks(start: date, end: date, days: int = 190) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    current = start
    while current <= end:
        chunk_end = min(end, current + timedelta(days=days - 1))
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def to_milliseconds(value: date, end_of_day: bool = False) -> int:
    moment = datetime.combine(value, datetime.max.time() if end_of_day else datetime.min.time(), tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def fetch_instrument(
    base_url: str,
    instrument: dict[str, object],
    start: date,
    end: date,
    cache_dir: Path,
) -> list[dict[str, object]]:
    category = str(instrument["category"])
    symbol = str(instrument["symbol"])
    cache_key = hashlib.sha1(f"reported-v2:{category}:{symbol}:{start}:{end}".encode()).hexdigest()[:12]
    cache_path = cache_dir / f"{category}-{symbol}-{cache_key}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))["observations"]

    observations: list[dict[str, object]] = []
    for chunk_start, chunk_end in date_chunks(start, end):
        common = {
            "category": category,
            "symbol": symbol,
            "startTime": to_milliseconds(chunk_start),
            "endTime": to_milliseconds(chunk_end, end_of_day=True),
        }
        oi_result = get_json(
            base_url,
            "/v5/market/open-interest",
            {**common, "intervalTime": "1d", "limit": 200},
        )["result"]
        kline_result = get_json(
            base_url,
            "/v5/market/kline",
            {
                "category": category,
                "symbol": symbol,
                "interval": "D",
                "start": common["startTime"],
                "end": common["endTime"],
                "limit": 1000,
            },
        )["result"]
        prices = {int(row[0]): float(row[1]) for row in kline_result.get("list", [])}
        for row in oi_result.get("list", []):
            timestamp = int(row["timestamp"])
            price = prices.get(timestamp)
            if price is None:
                continue
            reported_oi = float(row["openInterest"])
            oi_usd = reported_oi if category == "inverse" else reported_oi * price
            observations.append(
                {
                    "date": datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date().isoformat(),
                    "symbol": symbol,
                    "category": category,
                    "base_asset": instrument["base_asset"],
                    "quote_asset": instrument["quote_asset"],
                    "reported_oi": reported_oi,
                    "price": price,
                    "oi_usd": oi_usd,
                }
            )
    observations.sort(key=lambda row: str(row["date"]))
    cache_path.write_text(
        json.dumps({"instrument": instrument, "observations": observations}, separators=(",", ":")),
        encoding="utf-8",
    )
    return observations


def round_number(value: float) -> float:
    return round(value + 0.0, 8)


def main() -> None:
    args = parse_args()
    start = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)
    if end < start:
        raise ValueError("--to must be on or after --from")
    output_dir = Path(args.output_dir).resolve()
    cache_dir = output_dir / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    discovered = discover_instruments(args.base_url)
    cutoff = to_milliseconds(end, end_of_day=True)
    instruments = [
        item for item in discovered
        if int(item["launch_time"]) <= cutoff and item["quote_asset"] in {"USD", "USDT", "USDC"}
    ]
    observations: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(fetch_instrument, args.base_url, item, start, end, cache_dir): item
            for item in instruments
        }
        for index, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            try:
                observations.extend(future.result())
            except Exception as error:
                failures.append({"symbol": str(item["symbol"]), "error": str(error)})
            if index % 25 == 0 or index == len(futures):
                print(f"processed {index}/{len(futures)} instruments; failures={len(failures)}", flush=True)

    if failures:
        (output_dir / "failures.json").write_text(
            json.dumps(failures, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise RuntimeError(f"{len(failures)} Bybit instruments failed; see failures.json")

    observations.sort(key=lambda row: (str(row["date"]), str(row["symbol"])))
    detail_fields = (
        "date", "symbol", "category", "base_asset", "quote_asset",
        "reported_oi", "price", "oi_usd",
    )
    with (output_dir / "bybit-daily-by-symbol.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=detail_fields)
        writer.writeheader()
        writer.writerows(observations)

    daily: dict[str, dict[str, float | int]] = {}
    for row in observations:
        day = str(row["date"])
        bucket = daily.setdefault(day, {"all": 0.0, "btc": 0.0, "eth": 0.0, "markets": 0})
        value = float(row["oi_usd"])
        bucket["all"] = float(bucket["all"]) + value
        bucket["markets"] = int(bucket["markets"]) + 1
        if row["base_asset"] == "BTC":
            bucket["btc"] = float(bucket["btc"]) + value
        elif row["base_asset"] == "ETH":
            bucket["eth"] = float(bucket["eth"]) + value

    aggregate_rows: list[dict[str, object]] = []
    for day in sorted(daily):
        bucket = daily[day]
        all_oi = float(bucket["all"])
        btc_oi = float(bucket["btc"])
        eth_oi = float(bucket["eth"])
        others_oi = all_oi - btc_oi - eth_oi
        aggregate_rows.append(
            {
                "date": day,
                "all_oi_usd": round_number(all_oi),
                "btc_oi_usd": round_number(btc_oi),
                "eth_oi_usd": round_number(eth_oi),
                "others_oi_usd": round_number(others_oi),
                "btc_pct": round_number(btc_oi / all_oi * 100),
                "eth_pct": round_number(eth_oi / all_oi * 100),
                "others_pct": round_number(others_oi / all_oi * 100),
                "market_count": bucket["markets"],
            }
        )
    aggregate_fields = (
        "date", "all_oi_usd", "btc_oi_usd", "eth_oi_usd", "others_oi_usd",
        "btc_pct", "eth_pct", "others_pct", "market_count",
    )
    with (output_dir / "bybit-dominance.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=aggregate_fields)
        writer.writeheader()
        writer.writerows(aggregate_rows)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "from": aggregate_rows[0]["date"],
        "to": aggregate_rows[-1]["date"],
        "discovered_instruments": len(discovered),
        "eligible_instruments": len(instruments),
        "symbol_day_observations": len(observations),
        "days": len(aggregate_rows),
        "failures": len(failures),
        "oi_definition": "Bybit reported openInterest (sum of both sides, matching Coinalyze); linear contracts converted with same-timestamp daily kline open; inverse contracts already USD",
        "limitation": "Current Bybit instrument directory; delisted historical contracts may be missing",
    }
    (output_dir / "bybit-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
