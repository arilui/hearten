from app.config import Settings


def test_allowed_origins_are_split_and_trimmed():
    s = Settings(allowed_origins="https://a.example, http://localhost:3000 ,")
    assert s.allowed_origin_list == ["https://a.example", "http://localhost:3000"]


def test_plain_postgres_urls_get_the_psycopg_driver():
    neon = "postgresql://user:pw@ep-x.us-east-2.aws.neon.tech/hearten?sslmode=require"
    assert Settings(database_url=neon).database_url == (
        "postgresql+psycopg://user:pw@ep-x.us-east-2.aws.neon.tech/hearten?sslmode=require"
    )
    assert Settings(database_url="postgres://u@h/db").database_url == "postgresql+psycopg://u@h/db"


def test_database_url_can_come_from_ssm(monkeypatch):
    from app import config

    monkeypatch.setenv("DATABASE_URL_PARAM", "/hearten/database_url")
    monkeypatch.setattr(config, "read_ssm_parameter",
                        lambda name: "postgresql://u:p@db.example.com/hearten?sslmode=require")
    config.get_settings.cache_clear()
    try:
        url = config.get_settings().database_url
        assert url == "postgresql+psycopg://u:p@db.example.com/hearten?sslmode=require"
    finally:
        config.get_settings.cache_clear()
