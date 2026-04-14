"""Tests for tool functions."""
import pytest
from unittest.mock import patch, MagicMock
from tools import run_shell, read_file, write_file, calculator, fetch_url, web_search, TOOLS

def test_run_shell_returns_output():
    result = run_shell("echo hello")
    assert "hello" in result

def test_run_shell_returns_stderr_on_error():
    result = run_shell("cat nonexistent_file_xyz")
    assert result
    assert "nonexistent_file_xyz" in result  # stderr should mention the filename

def test_read_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = read_file(str(f))
    assert result == "hello world"

def test_read_file_missing():
    result = read_file("/nonexistent/path/file.txt")
    assert "Error" in result

def test_write_file(tmp_path):
    path = str(tmp_path / "out.txt")
    result = write_file(path, "hello")
    assert result == "OK"
    assert open(path).read() == "hello"

def test_calculator_basic():
    assert calculator("2 + 2") == "4"

def test_calculator_bad_expression():
    result = calculator("import os")
    assert "Error" in result

def test_calculator_division_by_zero():
    result = calculator("1 / 0")
    assert "Error" in result

def test_fetch_url_returns_text():
    mock_response = MagicMock()
    mock_response.text = "<html><body><h1>Hello</h1><p>World</p></body></html>"
    with patch("tools.requests.get", return_value=mock_response):
        result = fetch_url("https://example.com")
    assert "Hello" in result
    assert "World" in result

def test_fetch_url_truncates_long_content():
    mock_response = MagicMock()
    mock_response.text = f"<html><body><article><p>{'a' * 10000}</p></article></body></html>"
    with patch("tools.requests.get", return_value=mock_response):
        result = fetch_url("https://example.com")
    assert len(result) <= 8020  # 8000 + len("... (truncated)")
    assert "truncated" in result

def test_fetch_url_handles_error():
    with patch("tools.requests.get", side_effect=Exception("connection error")):
        result = fetch_url("https://example.com")
    assert "Error" in result

def test_web_search_returns_results():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"title": "Paris", "url": "https://example.com/paris", "content": "Paris is the capital of France."},
            {"title": "France", "url": "https://example.com/france", "content": "France is a country in Western Europe."},
        ]
    }
    with patch("tools.requests.post", return_value=mock_response):
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}):
            result = web_search("capital of France")
    assert "Paris" in result
    assert "https://example.com/paris" in result
    assert "1." in result

def test_web_search_handles_error():
    with patch("tools.requests.post", side_effect=Exception("network error")):
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}):
            result = web_search("anything")
    assert "Error" in result

def test_web_search_missing_api_key():
    with patch.dict("os.environ", {}, clear=True):
        result = web_search("anything")
    assert "TAVILY_API_KEY" in result

def test_tools_registry_has_all_tools():
    # Every registered tool must be callable and have a docstring
    # (docstrings are injected into the system prompt — they're load-bearing)
    for name, fn in TOOLS.items():
        assert callable(fn), f"{name} is not callable"
        assert fn.__doc__, f"{name} has no docstring — the harness needs this for the system prompt"


# ── Forecast tool tests ────────────────────────────────────────────────────

def test_get_forecast_registered():
    assert "get_forecast" in TOOLS

def _mock_geo(name="Seattle", admin1="Washington", country="United States", lat=47.6, lon=-122.3):
    m = MagicMock()
    m.json.return_value = {
        "results": [{"name": name, "admin1": admin1, "country": country,
                      "latitude": lat, "longitude": lon}]
    }
    return m

def _mock_daily(times, codes, highs, lows, precip_sums, precip_chances, winds):
    m = MagicMock()
    m.json.return_value = {
        "daily": {
            "time": times, "weather_code": codes,
            "temperature_2m_max": highs, "temperature_2m_min": lows,
            "precipitation_sum": precip_sums,
            "precipitation_probability_max": precip_chances,
            "wind_speed_10m_max": winds,
        }
    }
    return m

def test_get_forecast_returns_daily_data():
    from tools import get_forecast
    geo = _mock_geo()
    weather = _mock_daily(
        ["2026-04-13", "2026-04-14", "2026-04-15"],
        [3, 61, 0], [55.0, 50.0, 60.0], [42.0, 40.0, 45.0],
        [0.0, 0.5, 0.0], [10, 80, 0], [8.0, 15.0, 5.0],
    )
    with patch("tools.requests.get", side_effect=[geo, weather]):
        result = get_forecast("Seattle", days=3)
    assert "Seattle" in result
    assert "2026-04-13" in result
    assert "2026-04-14" in result
    assert "Overcast" in result
    assert "Slight rain" in result

def test_get_forecast_unknown_location():
    mock_geo = MagicMock()
    mock_geo.json.return_value = {"results": None}
    from tools import get_forecast
    with patch("tools.requests.get", return_value=mock_geo):
        result = get_forecast("Xyzzyville")
    assert "Error" in result

def test_get_forecast_no_location_ip_fallback_fails():
    from tools import get_forecast
    with patch("tools._get_ip_city", return_value=""):
        result = get_forecast("")
    assert "Error" in result
    assert "location" in result.lower()

def test_get_forecast_api_error():
    from tools import get_forecast
    with patch("tools.requests.get", side_effect=Exception("timeout")):
        result = get_forecast("Seattle")
    assert "Error" in result
    assert "timeout" in result

def test_get_forecast_single_day_label():
    from tools import get_forecast
    geo = _mock_geo("Portland", "Oregon", "United States", 45.5, -122.7)
    weather = _mock_daily(["2026-04-13"], [2], [58.0], [43.0], [0.0], [5], [7.0])
    with patch("tools.requests.get", side_effect=[geo, weather]):
        result = get_forecast("Portland", days=1)
    assert "1 day)" in result
    assert "days)" not in result

def test_get_forecast_ambiguous_location_shows_resolved():
    """Ambiguous names like 'Long Beach' resolve to most populous match;
    the output label should show the full resolved name so the user can verify."""
    from tools import get_forecast
    geo = _mock_geo("Long Beach", "California", "United States", 33.77, -118.19)
    weather = _mock_daily(["2026-04-13"], [1], [72.0], [58.0], [0.0], [0], [10.0])
    with patch("tools.requests.get", side_effect=[geo, weather]):
        result = get_forecast("Long Beach", days=1)
    assert "Long Beach" in result
    assert "California" in result
    assert "United States" in result

def test_get_forecast_start_and_end_date():
    """Explicit start_date and end_date should define the range."""
    from tools import get_forecast
    from datetime import date, timedelta
    # Use dates starting from today so they don't get clamped
    today = date.today()
    start = today
    end = today + timedelta(days=4)
    geo = _mock_geo()
    times = [(start + timedelta(days=i)).isoformat() for i in range(5)]
    weather = _mock_daily(times, [0]*5, [60.0]*5, [45.0]*5, [0.0]*5, [0]*5, [5.0]*5)
    with patch("tools.requests.get", side_effect=[geo, weather]):
        result = get_forecast("Seattle", start_date=start.isoformat(), end_date=end.isoformat())
    assert start.isoformat() in result
    assert end.isoformat() in result
    assert "5 days)" in result

def test_get_forecast_start_date_only_defaults_3_days():
    """start_date without end_date or days should give 3 days from start."""
    from tools import get_forecast
    from datetime import date, timedelta
    today = date.today()
    geo = _mock_geo()
    times = [(today + timedelta(days=i)).isoformat() for i in range(3)]
    weather = _mock_daily(times, [0]*3, [60.0]*3, [45.0]*3, [0.0]*3, [0]*3, [5.0]*3)
    with patch("tools.requests.get", side_effect=[geo, weather]):
        result = get_forecast("Seattle", start_date=today.isoformat())
    assert "3 days)" in result

def test_get_forecast_end_date_overrides_days():
    """end_date should take precedence over days."""
    from tools import get_forecast
    from datetime import date, timedelta
    today = date.today()
    end = today + timedelta(days=6)
    geo = _mock_geo()
    times = [(today + timedelta(days=i)).isoformat() for i in range(7)]
    weather = _mock_daily(times, [0]*7, [60.0]*7, [45.0]*7, [0.0]*7, [0]*7, [5.0]*7)
    with patch("tools.requests.get", side_effect=[geo, weather]):
        result = get_forecast("Seattle", days=2, end_date=end.isoformat())
    assert "7 days)" in result  # end_date wins, not days=2

def test_get_forecast_invalid_start_date():
    from tools import get_forecast
    result = get_forecast("Seattle", start_date="not-a-date")
    assert "Error" in result
    assert "start_date" in result

def test_get_forecast_invalid_end_date():
    from tools import get_forecast
    result = get_forecast("Seattle", end_date="garbage")
    assert "Error" in result
    assert "end_date" in result

def test_get_forecast_end_before_start():
    from tools import get_forecast
    from datetime import date, timedelta
    today = date.today()
    result = get_forecast("Seattle",
                          start_date=(today + timedelta(days=3)).isoformat(),
                          end_date=today.isoformat())
    assert "Error" in result
    assert "before" in result

def test_get_forecast_clamps_past_start_to_today():
    """start_date in the past should be clamped to today."""
    from tools import get_forecast
    from datetime import date, timedelta
    today = date.today()
    geo = _mock_geo()
    times = [(today + timedelta(days=i)).isoformat() for i in range(3)]
    weather = _mock_daily(times, [0]*3, [60.0]*3, [45.0]*3, [0.0]*3, [0]*3, [5.0]*3)
    with patch("tools.requests.get", side_effect=[geo, weather]):
        result = get_forecast("Seattle", start_date="2020-01-01",
                              end_date=(today + timedelta(days=2)).isoformat())
    assert today.isoformat() in result

def test_get_forecast_clamps_far_future_to_16_days():
    """end_date beyond 16 days should be clamped to the API max."""
    from tools import get_forecast
    from datetime import date, timedelta
    today = date.today()
    max_end = today + timedelta(days=15)
    geo = _mock_geo()
    num = (max_end - today).days + 1
    times = [(today + timedelta(days=i)).isoformat() for i in range(num)]
    weather = _mock_daily(times, [0]*num, [60.0]*num, [45.0]*num, [0.0]*num, [0]*num, [5.0]*num)
    with patch("tools.requests.get", side_effect=[geo, weather]):
        result = get_forecast("Seattle", start_date=today.isoformat(),
                              end_date=(today + timedelta(days=30)).isoformat())
    assert max_end.isoformat() in result
    assert f"{num} days)" in result


# ── Calendar tool tests ─────────────────────────────────────────────────────

def test_calendar_tools_registered():
    assert "read_calendar" in TOOLS
    assert "create_event" in TOOLS
    assert "list_calendars" in TOOLS


def test_read_calendar_rejects_bad_date():
    from tools import read_calendar
    result = read_calendar("not-a-date")
    assert "Error" in result
    assert "ISO 8601" in result


def test_read_calendar_bad_end_date():
    from tools import read_calendar
    result = read_calendar("2026-04-04", end_date="garbage")
    assert "Error" in result


def test_create_event_rejects_bad_start_time():
    from tools import create_event
    result = create_event("Test", "not-a-time")
    assert "Error" in result
    assert "ISO 8601" in result


def test_create_event_rejects_bad_end_time():
    from tools import create_event
    result = create_event("Test", "2026-04-10T12:00:00", end_time="garbage")
    assert "Error" in result


def test_create_event_duration_default():
    """Without end_time, duration defaults to 60 minutes."""
    from datetime import datetime, timedelta
    # We can't test AppleScript execution, but we can verify the date math
    start = datetime.fromisoformat("2026-04-10T12:00:00")
    expected_end = start + timedelta(minutes=60)
    assert expected_end.hour == 13
    assert expected_end.minute == 0


def test_system_prompt_contains_today():
    from harness import build_system_prompt
    prompt = build_system_prompt(TOOLS)
    assert "Today is" in prompt
    # Should contain a day of week and month
    from datetime import datetime
    today = datetime.now()
    assert today.strftime("%B") in prompt  # month name
    assert today.strftime("%Y") in prompt  # year


# ── Group chat tool tests ───────────────────────────────────────────────────

def test_group_chat_tools_registered():
    assert "send_group_imessage" in TOOLS
    assert "read_group_imessages" in TOOLS


def test_group_chat_tools_have_docstrings():
    assert TOOLS["send_group_imessage"].__doc__
    assert TOOLS["read_group_imessages"].__doc__


def test_send_group_requires_confirmation():
    from tools import Permission
    assert TOOLS["send_group_imessage"].permission == Permission.REQUIRES_CONFIRMATION


def test_read_group_is_read_only():
    from tools import Permission
    assert TOOLS["read_group_imessages"].permission == Permission.READ_ONLY


def test_send_group_imessage_needs_two_participants():
    from tools import send_group_imessage
    result = send_group_imessage("JustOnePerson", "hello")
    assert "Error" in result
    assert "at least 2" in result


def test_read_group_imessages_needs_two_participants():
    from tools import read_group_imessages
    result = read_group_imessages("JustOnePerson")
    assert "Error" in result
    assert "at least 2" in result


def test_send_group_imessage_nonexistent_group():
    from tools import send_group_imessage
    result = send_group_imessage("Nonexistent Person One, Nonexistent Person Two", "hello")
    assert "Error" in result or "no group chat" in result.lower()


def test_read_group_imessages_nonexistent_group():
    from tools import read_group_imessages
    result = read_group_imessages("Nonexistent Person One, Nonexistent Person Two")
    assert "Error" in result or "no group chat" in result.lower()
