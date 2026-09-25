import logging

from app.core.logging import setup_logging


def _ours(root):
    return [h for h in root.handlers if h.get_name() == "app-stdout"]


def test_app_messages_reach_stdout_and_web_clients_stay_quiet(capsys, monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    root = logging.getLogger()
    before, level = list(root.handlers), root.level
    # Other tests may have started the app already; start from none.
    for h in _ours(root):
        root.removeHandler(h)
    try:
        setup_logging()
        setup_logging()  # a second call adds nothing
        assert len(_ours(root)) == 1

        logging.getLogger("app.llm.client").info("LLM call: task=parsing")
        logging.getLogger("httpx").info("HTTP Request: GET https://storage.test/file?token=secret")
        out = capsys.readouterr().out
        assert "INFO app.llm.client: LLM call: task=parsing" in out
        assert "token=secret" not in out
    finally:
        root.handlers[:] = before
        root.setLevel(level)
