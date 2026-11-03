from app.ingestion.dailymed_client import parse_dailymed_date


def test_parse_dailymed_date_formats() -> None:
    assert parse_dailymed_date("Jul 15, 2026").isoformat() == "2026-07-15"
    assert parse_dailymed_date("2024-06-27").isoformat() == "2024-06-27"
    assert parse_dailymed_date(None) is None
    assert parse_dailymed_date("null") is None
