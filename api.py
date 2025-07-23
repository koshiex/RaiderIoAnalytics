from __future__ import annotations

import json
import re
from typing import List, Dict
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

HEADERS = {"User-Agent": "MythicTrackerBot/1.0 (+https://github.com)"}


class RaiderIOClient:
    BASE = "https://raider.io"

    CHAR_RUNS_BASE = (
        "{base}/api/characters/mythic-plus-runs?season={season}"
        "&characterId={character_id}&role=all&specId=0&mode=scored&affixes=all&date=all"
    )
    RUN_DETAILS_ENDPOINT = (
        "{base}/api/v1/mythic-plus/run-details?id={run_id}&season={season}&access_key={access_key}"
    )
    PROFILE_ENDPOINT = (
        "{base}/api/v1/characters/profile?region={region}&realm={realm}&name={name}"  # noqa: E501
        "&access_key={access_key}&fields="
        "mythic_plus_best_runs:all,mythic_plus_alternate_runs:all,mythic_plus_recent_runs"
    )

    def __init__(self, access_key: str, season: str) -> None:
        self.access_key = access_key
        self.season = season

    # ------------------------ Public API ------------------------

    def fetch_runs_for_dungeon(self, character_id: int, dungeon_id: int) -> List[dict]:
        url = (self.CHAR_RUNS_BASE + f"&dungeonId={dungeon_id}").format(
            base=self.BASE,
            season=self.season,
            character_id=character_id,
        )
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            return data.get("runs") or data.get("data") or []
        return data

    def fetch_dungeon_ids(self, region: str, realm: str, name: str) -> List[int]:
        url = self.PROFILE_ENDPOINT.format(
            base=self.BASE,
            region=region,
            realm=realm,
            name=quote(name),
            access_key=self.access_key,
        )
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        payload = response.json()

        zone_ids: set[int] = set()
        for field in (
            "mythic_plus_best_runs",
            "mythic_plus_alternate_runs",
            "mythic_plus_recent_runs",
        ):
            for run in payload.get(field, []):
                zone_id = run.get("zone_id")
                if zone_id:
                    zone_ids.add(zone_id)

        return sorted(zone_ids)

    def fetch_run_roster(self, run_id: int) -> List[dict]:
        url = self.RUN_DETAILS_ENDPOINT.format(
            base=self.BASE, run_id=run_id, season=self.season, access_key=self.access_key
        )
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "roster" in data:
            return [member.get("character", member) for member in data["roster"]]

        if "participants" in data:
            return data["participants"]

        logged = data.get("logged_details") or {}
        characters: list[dict] = []

        for enc in logged.get("encounters", []):
            for member in enc.get("roster", []):
                char_obj = member.get("character", member)
                if char_obj:
                    characters.append(char_obj)

        if characters:
            return characters

        return data.get("characters", [])


# ------------------------ Utility helpers ------------------------

def extract_run_id(run: dict) -> int | None:
    if not isinstance(run, dict):
        return None

    run_id = run.get("keystone_run_id") or run.get("id")
    if run_id:
        return run_id

    summary = run.get("summary")
    if isinstance(summary, dict):
        return summary.get("keystone_run_id") or summary.get("id")

    return None


def scrape_character_id(region: str, realm: str, name: str, season: str) -> int:
    url = f"https://raider.io/characters/{region}/{realm}/{quote(name)}?season={season}"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    html = response.text

    regex_candidates = [
        r"CharacterID[^0-9]{0,20}(\d+)",
        r"\"characterId\"\s*:?\s*(\d+)",
    ]

    for pattern in regex_candidates:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return int(match.group(1))

    soup = BeautifulSoup(html, "html.parser")

    for script in soup.find_all("script"):
        data = (script.string or "").strip()
        if "characterId" in data:
            try:
                json_obj = json.loads(data)
                if isinstance(json_obj, dict):
                    char_id = int(json_obj.get("characterId", 0))
                    if char_id:
                        return char_id
            except Exception:
                match = re.search(r"characterId[^0-9]{0,20}(\d+)", data, re.IGNORECASE)
                if match:
                    return int(match.group(1))

    raise RuntimeError("Unable to locate CharacterID on Raider.IO page") 