from sqlalchemy.pool import NullPool

from app.core.database import engine_options


def test_serverless_opens_a_connection_per_request():
    options = engine_options(0)
    assert options["poolclass"] is NullPool
    assert options["connect_args"] == {"statement_cache_size": 0}


def test_long_running_server_keeps_connections_open():
    options = engine_options(5)
    assert "poolclass" not in options
    assert (options["pool_size"], options["max_overflow"]) == (5, 5)
    connect_args = options["connect_args"]
    assert connect_args["statement_cache_size"] == 0
    # Unique names: statements left on a shared pooler connection never clash.
    name = connect_args["prepared_statement_name_func"]
    assert name() != name()
