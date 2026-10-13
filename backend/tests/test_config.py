from app.config import Settings


def test_allowed_origins_are_split_and_trimmed():
    s = Settings(allowed_origins="https://a.example, http://localhost:3000 ,")
    assert s.allowed_origin_list == ["https://a.example", "http://localhost:3000"]
