"""Fare parsing for flight_watch — fixture is real Google Flights page text."""

from __future__ import annotations

from typing import Any

import pytest

import flight_watch as fw
from integrations import mcp_scraper

WATCH: dict[str, Any] = {
    "origin": "STL", "destination": "MSY",
    "depart": "2026-10-01", "return": "2026-10-04", "nonstop_only": True,
}

PAGE = """Search results
17 results returned.
Track prices from St. Louis to New Orleans departing 2026-10-01 and returning 2026-10-04
St. Louis STL
New Orleans MSY
Top departing flights
10:20 AM
–
4:31 PM
Frontier
6 hr 11 min
STL–MSY
1 stop
2 hr 36 min DFW
150 kg CO2e
0
0
$430
round trip
8:30 AM
–
10:15 AM
Southwest
1 hr 45 min
STL–MSY
Nonstop
100 kg CO2e
1
0
$880
round trip
Price insights
Other departing flights
6:39 PM
–
7:07 PM+1
Frontier
24 hr 28 min
STL–MSY
1 stop
20 hr 3 min MCO
200 kg CO2e
0
0
$430
round trip
12:46 PM
–
6:46 PM
AmericanOperated by Envoy Air as American Eagle
6 hr
STL–MSY
2 stops
218 kg CO2e
1
0
$1,515
round trip
View more flights
"""


class TestParseFares:
    def test_reads_every_itinerary(self) -> None:
        items = fw.parse_fares(PAGE, WATCH)
        assert [(i["price"], i["stops"], i["airline"]) for i in items] == [
            (430.0, 1, "Frontier"),
            (880.0, 0, "Southwest"),
            (430.0, 1, "Frontier"),
            (1515.0, 2, "American"),
        ]

    def test_duration_is_the_trip_not_the_layover(self) -> None:
        items = fw.parse_fares(PAGE, WATCH)
        assert [i["durationMinutes"] for i in items] == [371, 105, 1468, 360]
        assert items[1]["departureTime"] == "8:30 AM"

    def test_ignores_fares_for_another_route(self) -> None:
        assert fw.parse_fares(PAGE.replace("STL–MSY", "STL–MCO"), WATCH) == []

    def test_nonstop_watch_scores_only_nonstops(self) -> None:
        summary = fw.summarize(fw.parse_fares(PAGE, WATCH), nonstop_only=True)
        assert summary["min_price"] == 880.0
        assert summary["usable"] == 1

    def test_any_stops_watch_drops_day_long_itineraries(self) -> None:
        summary = fw.summarize(fw.parse_fares(PAGE, WATCH))
        assert summary["min_price"] == 430.0
        assert summary["usable"] == 3  # the 24-hour Frontier connection is excluded


class TestSearchUrl:
    def test_nonstop_watch_asks_google_for_nonstop(self) -> None:
        assert "Nonstop%20flights%20from%20STL%20to%20MSY" in fw.search_url(WATCH)
        assert "through%202026-10-04" in fw.search_url(WATCH)

    def test_one_way_any_stops(self) -> None:
        url = fw.search_url({**WATCH, "return": None, "nonstop_only": False})
        assert "q=Flights%20from%20STL" in url
        assert "through" not in url


class TestFetchGuards:
    @pytest.mark.parametrize(
        ("page", "problem"),
        [
            (PAGE.replace("departing 2026-10-01", "departing 2026-11-01"), "departure date"),
            (PAGE.replace("returning 2026-10-04", "returning 2026-10-09"), "return date"),
            (PAGE.replace("MSY", "MCO"), "route"),
        ],
    )
    def test_refuses_a_page_for_a_different_trip(
        self, monkeypatch: pytest.MonkeyPatch, page: str, problem: str
    ) -> None:
        monkeypatch.setattr(fw, "read_page", lambda url, ready=None: page)
        with pytest.raises(RuntimeError, match=problem):
            fw.fetch_fares(WATCH)

    def test_failed_fetch_is_recorded_not_raised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(url: str, ready: Any = None) -> str:
            raise mcp_scraper.McpScraperError("browser_open: no slots")

        monkeypatch.setattr(fw, "read_page", boom)
        state: dict[str, Any] = {}
        line = fw.run_watch({**WATCH, "key": "k"}, state, dry_run=True, force=False)
        assert "FETCH FAILED" in line
        assert "no slots" in state["watches"]["k"]["last_error"]


class TestRpcParsing:
    def test_reads_event_stream_and_plain_json(self) -> None:
        body = '{"result": {"content": [{"type": "text", "text": "{\\"ok\\": true}"}]}}'
        assert mcp_scraper._parse_rpc(f"event: message\ndata: {body}\n")["result"]
        assert mcp_scraper._unwrap(mcp_scraper._parse_rpc(body)["result"]) == {"ok": True}

    def test_plain_text_payload_is_returned_as_text(self) -> None:
        result = {"content": [{"type": "text", "text": "# Credits"}]}
        assert mcp_scraper._unwrap(result) == "# Credits"

    def test_structured_content_wins(self) -> None:
        result = {"structuredContent": {"a": 1}, "content": [{"type": "text", "text": "x"}]}
        assert mcp_scraper._unwrap(result) == {"a": 1}


class TestApiKey:
    @pytest.mark.parametrize("name", ["MCP_SCRAPER_API_KEY", "MCPSCRAPER_API_KEY"])
    def test_either_spelling_is_read(self, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
        monkeypatch.delenv("MCP_SCRAPER_API_KEY", raising=False)
        monkeypatch.delenv("MCPSCRAPER_API_KEY", raising=False)
        monkeypatch.setenv(name, "key-from-env")
        assert mcp_scraper.api_key() == "key-from-env"
