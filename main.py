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
    CHAR_RUNS_BASE = (
        "{base}/api/characters/mythic-plus-runs?season={season}"
        "&characterId={character_id}&role=all&specId=0&mode=scored&affixes=all&date=all"
    )
    RUN_DETAILS_ENDPOINT = (
        "{base}/api/v1/mythic-plus/run-details?id={run_id}&season={season}&access_key={access_key}"
    )

    PROFILE_ENDPOINT = (
        "{base}/api/v1/characters/profile?region={region}&realm={realm}&name={name}"\
        "&access_key={access_key}&fields=mythic_plus_best_runs:all,mythic_plus_alternate_runs:all,mythic_plus_recent_runs"
    )

    def __init__(self, access_key: str, season: str):
        self.access_key = access_key
        self.season = season

    def fetch_character_runs(self, character_id: int) -> List[dict]:
        """Fetch all mythic+ runs for the given character (single request)."""
        url = self.CHAR_RUNS_BASE.format(
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

    def fetch_runs_for_dungeon(
        self,
        character_id: int,
        dungeon_id: int,
        raw_save_dir: Path | None = None,
    ) -> List[dict]:
        """Fetch runs for a specific dungeon.

        If ``raw_save_dir`` указан, сохраняет оригинальный ответ JSON в файл
        ``{raw_save_dir}/runs_{dungeon_id}.json``.
        """
        url = (self.CHAR_RUNS_BASE + f"&dungeonId={dungeon_id}").format(
            base=self.BASE, season=self.season, character_id=character_id
        )
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Save raw JSON if requested
        if raw_save_dir is not None:
            raw_save_dir.mkdir(parents=True, exist_ok=True)
            out_file = raw_save_dir / f"runs_{dungeon_id}.json"
            try:
                out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                print(f"⚠️  Не удалось сохранить raw ответ для данжа {dungeon_id}: {exc}")

        if isinstance(data, dict):
            return data.get("runs") or data.get("data") or []
        return data

    def fetch_dungeon_ids(self, region: str, realm: str, name: str) -> List[int]:
        """Retrieve unique dungeon zone_ids for current season via profile endpoint."""
        url = self.PROFILE_ENDPOINT.format(
            base=self.BASE,
            region=region,
            realm=realm,
            name=quote(name),
            access_key=self.access_key,
        )
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        zone_ids = set()
        for field in (
            "mythic_plus_best_runs",
            "mythic_plus_alternate_runs",
            "mythic_plus_recent_runs",
        ):
            for run in payload.get(field, []):
                zid = run.get("zone_id")
                if zid:
                    zone_ids.add(zid)

        return sorted(zone_ids)

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
        # Some responses embed roster within logged_details.encounters[*].roster
        logged = data.get("logged_details") or {}
        characters = []
        for enc in logged.get("encounters", []):
            for member in enc.get("roster", []):
                char_obj = member.get("character", member)
                if char_obj:
                    characters.append(char_obj)
        if characters:
            return characters
        # Fallback: try top-level character list
        return data.get("characters", [])


def load_config() -> Dict[str, str]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------
# Utility helpers
# ------------------------------


def extract_run_id(run: dict) -> int | None:
    """Return numeric run id (keystone_run_id / id) from different API shapes."""
    if not isinstance(run, dict):
        return None
    rid = run.get("keystone_run_id") or run.get("id")
    if rid:
        return rid
    summary = run.get("summary")
    if isinstance(summary, dict):
        return summary.get("keystone_run_id") or summary.get("id")
    return None


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

    total = len(runs)
    for idx, run in enumerate(runs, 1):
        run_id = extract_run_id(run)
        if not run_id:
            continue
        print(f"Processing run {idx}/{total} (id={run_id})…")
        try:
            roster = client.fetch_run_roster(run_id)
        except Exception as exc:
            print(f"⚠️ Skipping run {run_id} due to error: {exc}")
            continue
        for character in roster:
            name = character.get("name")
            realm = character.get("realm") or character.get("realm_slug", "")
            if isinstance(realm, dict):
                realm = realm.get("slug") or realm.get("name") or ""
            full = f"{name}-{realm}" if realm else name
            if name.lower() == self_name.lower():
                continue  # skip ourselves
            teammate_counter[full] += 1
        time.sleep(0.05)  # polite delay
    return teammate_counter


def plot_teammates(counter: Counter, player_name: str, total_runs: int):
    if not counter:
        print("No teammate data to plot.")
        return
    top = counter.most_common(20)  # show top 20
    names, counts = zip(*top)

    # Horizontal bar chart to better fit long names
    fig_height = max(6, len(top) * 0.45)
    plt.figure(figsize=(10, fig_height))
    bars = plt.barh(range(len(top))[::-1], counts[::-1], color="steelblue")
    plt.yticks(range(len(top))[::-1], names[::-1], fontsize=8)
    plt.xlabel("Number of Shared Runs")
    plt.title("Top Mythic+ Teammates")

    # Annotate bars with counts
    for bar, count in zip(bars, counts[::-1]):
        plt.text(count + 0.5, bar.get_y() + bar.get_height() / 2,
                 str(count), va="center", fontsize=8)

    # Add footer with character name and total runs
    plt.text(0.98, 0.02, f"{player_name} — {total_runs} runs", transform=plt.gcf().transFigure,
             ha="right", va="bottom", fontsize=8, color="gray")

    plt.tight_layout(rect=[0.15, 0.05, 0.95, 1])
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

    print("Retrieving dungeon list (zone_ids)…")
    dungeon_ids = client.fetch_dungeon_ids(region, realm, name)
    print(f"Dungeons detected ({len(dungeon_ids)}): {dungeon_ids}")

    raw_dir = Path(__file__).with_name("raw_runs")
    runs = []
    seen_ids = set()
    for d_id in dungeon_ids:
        print(f"Fetching runs for dungeon {d_id}…")
        for run in client.fetch_runs_for_dungeon(char_id, d_id, raw_save_dir=raw_dir):
            rid = extract_run_id(run)
            if rid and rid not in seen_ids:
                runs.append(run)
                seen_ids.add(rid)

    print(f"Total unique runs gathered: {len(runs)}")

    print("Building teammate statistics…")
    counter = build_teammate_stats(runs, client, name)

    print("Plotting results…")
    plot_teammates(counter, name, len(runs))


if __name__ == "__main__":
    main()
