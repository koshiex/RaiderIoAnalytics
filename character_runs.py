from __future__ import annotations

from typing import List

from api import RaiderIOClient, extract_run_id, scrape_character_id


def collect_runs_for_character(
    client: RaiderIOClient,
    region: str,
    realm: str,
    name: str,
) -> List[dict]:
    """Collects all unique Mythic+ runs for the given character."""

    character_id = scrape_character_id(region, realm, name, client.season)

    dungeon_ids = client.fetch_dungeon_ids(region, realm, name)

    print(f"Dungeons detected ({len(dungeon_ids)}): {dungeon_ids}")

    runs: list[dict] = []
    seen_run_ids: set[int] = set()

    for dungeon_id in dungeon_ids:
        print(f"Fetching runs for dungeon {dungeon_id}…")

        for run in client.fetch_runs_for_dungeon(character_id, dungeon_id):
            run_id = extract_run_id(run)
            if run_id and run_id not in seen_run_ids:
                runs.append(run)
                seen_run_ids.add(run_id)

    print(f"Total unique runs gathered: {len(runs)}")

    return runs 