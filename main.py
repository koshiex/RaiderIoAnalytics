#!/usr/bin/env python
"""Entry point for generating Mythic+ teammate statistics for a single character."""

from __future__ import annotations

import json
from pathlib import Path

from api import RaiderIOClient
from character_runs import collect_runs_for_character
from analytics import build_teammate_stats, plot_teammates

CONFIG_PATH = Path(__file__).with_name("config.json")
OUTPUT_CHART = Path(__file__).with_name("teammates_chart.png")


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def main() -> None:
    config = load_config()

    client = RaiderIOClient(
        access_key=config["access_key"],
        season=config["season"],
    )

    runs = collect_runs_for_character(
        client,
        region=config["region"],
        realm=config["realm"],
        name=config["name"],
    )

    teammate_counts = build_teammate_stats(runs, client, config["name"])

    plot_teammates(teammate_counts, config["name"], len(runs), OUTPUT_CHART)


if __name__ == "__main__":
    main()
