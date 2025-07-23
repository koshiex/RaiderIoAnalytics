import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

CONFIG_PATH = Path(__file__).with_name("config.json")
OUTPUT_CHART = Path(__file__).with_name("teammates_chart.png")

HEADERS = {
    "User-Agent": "MythicTrackerBot/1.0 (+https://github.com)"
}


class RaiderIOClient:
    """Minimal wrapper around the Raider.IO public API used in this script."""

    BASE = "https://raider.io"
    CHAR_RUNS_ENDPOINT = (
        "{base}/api/characters/mythic-plus-runs?season={season}"
        "&characterId={character_id}&role=all&specId=0&mode=all&affixes=all&date=all"
    )
    RUN_DETAILS_ENDPOINT = (
        "{base}/api/v1/mythic-plus/run-details?id={run_id}&season={season}&access_key={access_key}"
    )

    def __init__(self, access_key: str, season: str):
        self.access_key = access_key
        self.season = season

    def fetch_character_runs(self, character_id: int) -> List[dict]:
        """Fetch all mythic+ runs for the given character (single request)."""
        url = self.CHAR_RUNS_ENDPOINT.format(
            base=self.BASE, season=self.season, character_id=character_id
        )
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Endpoint may wrap runs in "runs" or return a list directly.
        if isinstance(data, dict):
            runs = data.get("runs") or data.get("data") or []
        else:
            runs = data
        return runs

    def fetch_run_roster(self, run_id: int) -> List[dict]:
        """Fetch roster (list of characters) for a specific run."""
        url = self.RUN_DETAILS_ENDPOINT.format(
            base=self.BASE, run_id=run_id, season=self.season, access_key=self.access_key
        )
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Response shape: {"roster": [{"character": {...}}, ...]} or similar.
        if "roster" in data:
            return [member.get("character", member) for member in data["roster"]]
        if "participants" in data:
            return data["participants"]
        # Fallback: try top-level character list
        return data.get("characters", [])


def load_config() -> Dict[str, str]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def scrape_character_id(region: str, realm: str, name: str, season: str) -> int:
    """Return Raider.IO numeric character id by scraping public profile page."""
    url = f"https://raider.io/characters/{region}/{realm}/{quote(name)}?season={season}"

    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text

    # 1) Fast regex search (case-insensitive, tolerate html tags/newlines)
    regex_candidates = [
        r"CharacterID[^0-9]{0,20}(\d+)",  # Original pattern, but flexible
        r"\"characterId\"\s*:?\s*(\d+)",  # JSON attribute inside scripts, both `'` & `"` handled later
    ]
    for pattern in regex_candidates:
        m = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return int(m.group(1))

    # 2) Search <script> tags that might contain JSON with character data
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        data = (script.string or "").strip()
        if "characterId" in data:
            try:
                # Some scripts embed JSON directly
                json_obj = json.loads(data)
                if isinstance(json_obj, dict):
                    cid = int(json_obj.get("characterId"))
                    if cid:
                        return cid
            except Exception:
                # Fallback to regex inside script content
                m = re.search(r"characterId[^0-9]{0,20}(\d+)", data, re.IGNORECASE)
                if m:
                    return int(m.group(1))

    raise RuntimeError("Failed to locate CharacterID on Raider.IO page. The page structure may have changed.")


def build_teammate_stats(runs: List[dict], client: RaiderIOClient, self_name: str) -> Counter:
    """Download each run's roster and count how many times each teammate appears."""
    teammate_counter: Counter = Counter()

    for run in runs:
        run_id = run.get("keystone_run_id") or run.get("id")
        if not run_id:
            continue
        try:
            roster = client.fetch_run_roster(run_id)
        except Exception as exc:
            print(f"⚠️ Skipping run {run_id} due to error: {exc}")
            continue
        for character in roster:
            name = character.get("name")
            realm = character.get("realm") or character.get("realm_slug", "")
            full = f"{name}-{realm}" if realm else name
            if name == self_name:
                continue  # skip ourselves
            teammate_counter[full] += 1
        time.sleep(0.05)  # polite delay
    return teammate_counter


def plot_teammates(counter: Counter):
    if not counter:
        print("No teammate data to plot.")
        return
    top = counter.most_common(20)  # show top 20
    names, counts = zip(*top)
    plt.figure(figsize=(max(10, len(top) * 0.5), 6))
    bars = plt.bar(names, counts, color="steelblue")
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Number of Shared Runs")
    plt.title("Top Mythic+ Teammates")
    # Annotate bars
    for bar, count in zip(bars, counts):
        plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), str(count),
                 ha="center", va="bottom", fontsize=8)
    plt.tight_layout()
    plt.savefig(OUTPUT_CHART, dpi=150)
    print(f"Chart saved to {OUTPUT_CHART}")


def main():
    cfg = load_config()

    region = cfg["region"]
    realm = cfg["realm"]
    name = cfg["name"]
    season = cfg["season"]
    access_key = cfg["access_key"]

    print("Fetching CharacterID…")
    char_id = scrape_character_id(region, realm, name, season)
    print(f"Character ID: {char_id}")

    client = RaiderIOClient(access_key=access_key, season=season)

    print("Fetching all runs for the character… (this may take a while)")
    runs = client.fetch_character_runs(char_id)
    print(f"Total runs fetched: {len(runs)}")

    print("Building teammate statistics…")
    counter = build_teammate_stats(runs, client, name)

    print("Plotting results…")
    plot_teammates(counter)


if __name__ == "__main__":
    main()
