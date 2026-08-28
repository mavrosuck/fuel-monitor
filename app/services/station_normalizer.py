import json
from pathlib import Path

from app.services.keyword_filter import normalize_text


class StationNormalizer:
    def __init__(self, stations_path: Path | None = None) -> None:
        path = stations_path or Path(__file__).resolve().parents[2] / "data" / "stations.json"
        self.stations = json.loads(path.read_text(encoding="utf-8"))["stations"]

    def normalize(self, brand: str | None, location: str | None) -> str:
        haystack = normalize_text(" ".join(part for part in [brand, location] if part))
        for station in self.stations:
            aliases = [station["id"], *station["aliases"], f"{station['brand']} {station['location']}"]
            if any(normalize_text(alias) in haystack for alias in aliases if haystack):
                return station["id"]
        if brand and location:
            for station in self.stations:
                if normalize_text(station["brand"]) == normalize_text(brand) and normalize_text(station["location"]) in normalize_text(location):
                    return station["id"]
        return "unknown:" + normalize_text("|".join(part or "" for part in [brand, location]))
