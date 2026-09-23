#!/usr/bin/env python3
"""Build the downloadable OI dominance workbook from the validated daily CSV."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import xlsxwriter


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CSV_PATH = DATA_DIR / "dominance-2021plus.csv"
SUMMARY_PATH = DATA_DIR / "dominance-2021plus-summary.json"
OUTPUT_PATH = DATA_DIR / "oi-dominance-2021plus.xlsx"


def number(row: dict[str, str], key: str) -> float:
    value = float(row[key])
    if value != value:  # NaN
        raise ValueError(f"Invalid {key} for {row.get('date')}")
    return value


def main() -> None:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    with CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("No daily observations found")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(OUTPUT_PATH)
    workbook.set_properties({
        "title": "OI Dominance 2021+",
        "subject": "Crypto-only open interest dominance and BTC daily close",
        "author": "OI Dominance daily updater",
    })

    overview = workbook.add_worksheet("总览")
    data = workbook.add_worksheet("日线数据")
    notes = workbook.add_worksheet("说明")
    overview.set_tab_color("#3267D6")
    data.set_tab_color("#18A68D")
    notes.set_tab_color("#80889A")

    base = {"font_name": "Arial", "font_size": 10, "font_color": "#1C2530"}
    title_fmt = workbook.add_format({**base, "font_size": 20, "bold": True})
    subtitle_fmt = workbook.add_format({**base, "italic": True, "font_color": "#667085"})
    header_fmt = workbook.add_format({
        **base, "bold": True, "font_color": "#FFFFFF", "bg_color": "#26313F",
        "align": "center", "valign": "vcenter", "text_wrap": True,
    })
    date_fmt = workbook.add_format({**base, "num_format": "yyyy-mm-dd", "align": "center"})
    money_fmt = workbook.add_format({**base, "num_format": '$#,##0', "align": "right"})
    price_fmt = workbook.add_format({**base, "num_format": '$#,##0.00', "align": "right"})
    pct_fmt = workbook.add_format({**base, "num_format": "0.00%", "align": "right"})
    text_fmt = workbook.add_format({**base})
    card_label = workbook.add_format({
        **base, "bold": True, "align": "center", "valign": "vcenter",
        "bg_color": "#F6F8FB", "border": 1, "border_color": "#D6DCE5",
    })
    card_pct = workbook.add_format({
        **base, "font_size": 18, "bold": True, "align": "center", "valign": "vcenter",
        "num_format": "0.00%", "bg_color": "#F6F8FB", "border": 1, "border_color": "#D6DCE5",
    })
    card_price = workbook.add_format({
        **base, "font_size": 18, "bold": True, "align": "center", "valign": "vcenter",
        "num_format": '$#,##0.00', "bg_color": "#F6F8FB", "border": 1, "border_color": "#D6DCE5",
    })
    note_fmt = workbook.add_format({
        **base, "font_color": "#7A4F01", "bg_color": "#FFF8E8", "border": 1,
        "border_color": "#E6C46A", "text_wrap": True, "valign": "vcenter",
    })
    label_fmt = workbook.add_format({**base, "bold": True, "bg_color": "#EEF2F7"})

    headers = [
        "日期", "加密 OI（USD）", "股票代币 OI（USD）", "原始总 OI（USD）",
        "BTC OI（USD）", "ETH OI（USD）", "山寨 OI（USD）", "BTC OI 占比",
        "ETH OI 占比", "山寨 OI 占比", "BTC 收盘价（USD）", "数据范围", "质量等级", "图表日期",
    ]
    data.set_row(0, 34)
    for col, header in enumerate(headers):
        data.write(0, col, header, header_fmt)

    for index, row in enumerate(rows, start=1):
        excel_row = index + 1
        day = datetime.strptime(row["date"], "%Y-%m-%d")
        crypto = number(row, "all_oi_usd")
        excluded = number(row, "excluded_oi_usd")
        btc = number(row, "btc_oi_usd")
        eth = number(row, "eth_oi_usd")
        others = number(row, "others_oi_usd")
        btc_pct = number(row, "btc_pct") / 100
        eth_pct = number(row, "eth_pct") / 100
        others_pct = number(row, "others_pct") / 100
        if max(abs(btc / crypto - btc_pct), abs(eth / crypto - eth_pct), abs(others / crypto - others_pct)) > 1e-8:
            raise ValueError(f"Dominance reconciliation failed for {row['date']}")

        data.write_datetime(index, 0, day, date_fmt)
        data.write_number(index, 1, crypto, money_fmt)
        data.write_number(index, 2, excluded, money_fmt)
        data.write_formula(index, 3, f"=B{excel_row}+C{excel_row}", money_fmt, crypto + excluded)
        data.write_number(index, 4, btc, money_fmt)
        data.write_number(index, 5, eth, money_fmt)
        data.write_number(index, 6, others, money_fmt)
        data.write_formula(index, 7, f"=E{excel_row}/B{excel_row}", pct_fmt, btc_pct)
        data.write_formula(index, 8, f"=F{excel_row}/B{excel_row}", pct_fmt, eth_pct)
        data.write_formula(index, 9, f"=G{excel_row}/B{excel_row}", pct_fmt, others_pct)
        data.write_number(index, 10, number(row, "btc_price_usd"), price_fmt)
        data.write(index, 11, row["source_scope"], text_fmt)
        data.write(index, 12, row["quality_tier"], text_fmt)
        data.write(index, 13, row["date"], text_fmt)

    last_row = len(rows)
    data.add_table(0, 0, last_row, 13, {
        "name": "OiDominanceDaily",
        "style": "Table Style Medium 2",
        "columns": [{"header": value} for value in headers],
    })
    data.freeze_panes(1, 0)
    data.set_column("A:A", 12)
    data.set_column("B:G", 18)
    data.set_column("H:J", 14)
    data.set_column("K:K", 16)
    data.set_column("L:M", 31)
    data.set_column("N:N", 13)

    overview.hide_gridlines(2)
    overview.set_column("A:J", 12)
    overview.merge_range("A1:J1", "OI Dominance", title_fmt)
    overview.merge_range("A2:J2", f"加密市场日频未平仓合约占比（UTC） · {summary['from']} 至 {summary['to']}", subtitle_fmt)
    overview.set_row(2, 8)

    cards = [
        ("A5:B5", "A6:B7", "BTC OI 占比", 7, card_pct),
        ("D5:E5", "D6:E7", "ETH OI 占比", 8, card_pct),
        ("G5:H5", "G6:H7", "山寨 OI 占比", 9, card_pct),
        ("I5:J5", "I6:J7", "BTC 收盘价", 10, card_price),
    ]
    cached_values = (btc_pct, eth_pct, others_pct, number(rows[-1], "btc_price_usd"))
    for card_index, (label_range, value_range, label, col, value_fmt) in enumerate(cards):
        overview.merge_range(label_range, label, card_label)
        overview.merge_range(value_range, "", value_fmt)
        top_left = value_range.split(":", 1)[0]
        overview.write_formula(
            top_left,
            f"='日线数据'!{xlsxwriter.utility.xl_col_to_name(col)}{last_row + 1}",
            value_fmt,
            cached_values[card_index],
        )

    dominance_chart = workbook.add_chart({"type": "line"})
    for name, col, color in (("BTC OI 占比", 7, "#3267D6"), ("ETH OI 占比", 8, "#18A68D"), ("山寨 OI 占比", 9, "#E57932")):
        dominance_chart.add_series({
            "name": name,
            "categories": ["日线数据", 1, 0, last_row, 0],
            "values": ["日线数据", 1, col, last_row, col],
            "line": {"color": color, "width": 1.5},
        })
    dominance_chart.set_title({"name": "BTC、ETH 与山寨 OI 占比"})
    dominance_chart.set_legend({"position": "bottom"})
    dominance_chart.set_y_axis({"num_format": "0%", "major_gridlines": {"visible": True, "line": {"color": "#E6EAF0"}}})
    dominance_chart.set_x_axis({"date_axis": True, "num_format": "yyyy-mm", "label_position": "low"})
    dominance_chart.set_chartarea({"border": {"none": True}})
    overview.insert_chart("A9", dominance_chart, {"x_scale": 1.42, "y_scale": 1.25})

    price_chart = workbook.add_chart({"type": "line"})
    price_chart.add_series({
        "name": "BTC 收盘价（USD）",
        "categories": ["日线数据", 1, 0, last_row, 0],
        "values": ["日线数据", 1, 10, last_row, 10],
        "line": {"color": "#C89B32", "width": 1.5},
    })
    price_chart.set_title({"name": "BTC 日收盘价（USD）"})
    price_chart.set_legend({"none": True})
    price_chart.set_y_axis({"num_format": "$#,##0", "major_gridlines": {"visible": True, "line": {"color": "#E6EAF0"}}})
    price_chart.set_x_axis({"date_axis": True, "num_format": "yyyy-mm", "label_position": "low"})
    price_chart.set_chartarea({"border": {"none": True}})
    overview.insert_chart("A29", price_chart, {"x_scale": 1.42, "y_scale": 1.0})
    overview.merge_range(
        "A46:J47",
        "2021-12-01 至 2022-07-29 为 Binance + Bybit 固定交易所重建段；2022-07-30 起为 Coinalyze 当前合约宇宙清洗段。股票代币已从后段 OI 分母中剔除。",
        note_fmt,
    )

    notes.hide_gridlines(2)
    notes.set_column("A:A", 31)
    notes.set_column("B:B", 70)
    notes.set_column("C:D", 12)
    notes.merge_range("A1:D1", "数据说明", title_fmt)
    metadata = [
        ("项目", "OI Dominance"), ("数据范围", f"{summary['from']} 至 {summary['to']}"),
        ("频率", "UTC 日频"), ("观测数", summary["observations"]),
        ("口径切换日", summary["switch_date"]),
        ("早期覆盖", "Binance USD-M/COIN-M + Bybit linear/inverse"),
        ("后期覆盖", "Coinalyze 当前合约宇宙，剔除股票代币"),
    ]
    for offset, (label, value) in enumerate(metadata, start=2):
        notes.write(offset, 0, label, label_fmt)
        notes.write(offset, 1, value, text_fmt)
    notes.write_row("A11", ["来源", "网址"], header_fmt)
    sources = [
        ("Coinalyze API", "https://api.coinalyze.net/v1/doc/"),
        ("Binance Data Vision", "https://data.binance.vision/"),
        ("Bybit V5 Open Interest", "https://bybit-exchange.github.io/docs/v5/market/open-interest"),
    ]
    for offset, source in enumerate(sources, start=11):
        notes.write_row(offset, 0, source, text_fmt)
    notes.write_row("A16", ["质量等级", "含义"], header_fmt)
    notes.write_row("A17", ["partial_multi_exchange_coverage", "固定交易所覆盖，不能视为 Coinalyze 全市场原序列"], text_fmt)
    notes.write_row("A18", ["high_with_survivorship_caveat", "多交易所清洗序列，但当前合约目录可能遗漏已退市历史合约"], text_fmt)
    notes.merge_range("A20:D22", summary["warning"], note_fmt)

    workbook.close()
    print(json.dumps({"output": str(OUTPUT_PATH), "observations": len(rows), "from": summary["from"], "to": summary["to"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

