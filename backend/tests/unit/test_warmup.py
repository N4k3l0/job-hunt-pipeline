from app.core import warmup


async def test_a_failing_step_never_stops_the_start(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "db_pool_size", 2)

    async def database_down(count):
        raise ConnectionError("database unreachable")

    def keys_down():
        raise TimeoutError("auth server slow")

    monkeypatch.setattr(warmup, "_open_database_connections", database_down)
    monkeypatch.setattr(warmup, "_fetch_login_keys", keys_down)
    monkeypatch.setattr(warmup, "_create_ai_client", lambda: "ready")

    outcome = await warmup.warm_up()
    assert outcome["modules"].split()[0].isdigit() and int(outcome["modules"].split()[0]) > 50
    assert outcome["database"].startswith("failed after") and "ConnectionError" in outcome["database"]
    assert outcome["login keys"].startswith("failed after") and "TimeoutError" in outcome["login keys"]
    assert outcome["pdf"].split()[0].isdigit()
    assert outcome["ai client"].startswith("ready")


async def test_the_database_step_is_skipped_without_a_pool(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "db_pool_size", 0)
    monkeypatch.setattr(warmup, "_fetch_login_keys", lambda: 0)
    monkeypatch.setattr(warmup, "_create_ai_client", lambda: "ready")
    assert "database" not in await warmup.warm_up()
