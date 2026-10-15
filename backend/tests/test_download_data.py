import csv

from scripts import download_data
from scripts.import_data import read_bls_prices

PAYLOAD = {
    "status": "REQUEST_SUCCEEDED",
    "Results": {"series": [
        {"seriesID": "APU0000701111", "data": [
            {"year": "2026", "period": "M08", "value": "0.60"},
            {"year": "2026", "period": "M07", "value": "0.55"},
        ]},
        {"seriesID": "APU0000708111", "data": [
            {"year": "2026", "period": "M08", "value": "3.00"},
            {"year": "2025", "period": "M13", "value": "2.80"},  # annual average: skipped
            {"year": "2026", "period": "M09", "value": "-"},     # not yet published
        ]},
    ]},
}


def test_bls_api_payload_to_columns():
    columns = download_data.bls_to_columns(PAYLOAD)
    assert columns == {
        "APU0000701111": {"2026-08-01": "0.60", "2026-07-01": "0.55"},
        "APU0000708111": {"2026-08-01": "3.00"},
    }


def test_downloaded_file_reads_back_as_prices(tmp_path, monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *args):
            import json
            return json.dumps(PAYLOAD).encode()

    monkeypatch.setattr(download_data, "bls_series_ids",
                        lambda: ["APU0000701111", "APU0000708111"])
    monkeypatch.setattr(download_data.urllib.request, "urlopen", lambda *a, **k: Response())
    target = tmp_path / "bls.csv"
    assert download_data.download_bls_prices(target)
    rows = list(csv.reader(target.open()))
    assert rows[0] == ["observation_date", "APU0000701111", "APU0000708111"]

    mapping = tmp_path / "map.csv"
    mapping.write_text("series_id,item,unit,grams_per_unit,fdc_id,sr_description\n"
                       "APU0000701111,Flour,lb,453.592,168894,Flour\n")
    prices = read_bls_prices(target, mapping)
    assert prices["price_period"].item() == "2026-08"
