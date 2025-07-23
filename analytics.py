from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import List

import matplotlib.pyplot as plt

from api import RaiderIOClient, extract_run_id


def build_teammate_stats(
    runs: List[dict],
    client: RaiderIOClient,
    self_name: str,
) -> Counter:
    teammate_counter: Counter = Counter()

    total = len(runs)

    for idx, run in enumerate(runs, 1):
        run_id = extract_run_id(run)
        if not run_id:
            continue

        print(f"Processing run {idx}/{total} (id={run_id})…")

        try:
            roster = client.fetch_run_roster(run_id)
        except Exception as exc:
            print(f"⚠️  Skipping run {run_id}: {exc}")
            continue

        for character in roster:
            name = character.get("name")
            realm = character.get("realm") or character.get("realm_slug", "")

            if isinstance(realm, dict):
                realm = realm.get("slug") or realm.get("name") or ""

            full = f"{name}-{realm}" if realm else name

            if name.lower() == self_name.lower():
                continue

            teammate_counter[full] += 1

        time.sleep(0.05)

    return teammate_counter


def plot_teammates(
    counter: Counter,
    player_name: str,
    total_runs: int,
    output_path: Path,
) -> None:
    if not counter:
        print("No teammate data to plot.")
        return

    top = counter.most_common(20)
    names, counts = zip(*top)

    fig_height = max(6, len(top) * 0.45)
    plt.figure(figsize=(10, fig_height))

    bars = plt.barh(range(len(top))[::-1], counts[::-1], color="steelblue")
    plt.yticks(range(len(top))[::-1], names[::-1], fontsize=8)
    plt.xlabel("Number of Shared Runs")
    plt.title("Top Mythic+ Teammates")

    for bar, count in zip(bars, counts[::-1]):
        plt.text(
            count + 0.5,
            bar.get_y() + bar.get_height() / 2,
            str(count),
            va="center",
            fontsize=8,
        )

    plt.text(
        0.98,
        0.02,
        f"{player_name} — {total_runs} runs",
        transform=plt.gcf().transFigure,
        ha="right",
        va="bottom",
        fontsize=8,
        color="gray",
    )

    plt.tight_layout(rect=[0.15, 0.05, 0.95, 1])
    plt.savefig(output_path, dpi=150)
    print(f"Chart saved to {output_path}") 