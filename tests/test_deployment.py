from pathlib import Path

_ROOT = Path(__file__).parents[1]


def test_streamlit_app_delegates_to_lawsearch_main(monkeypatch):
    calls = []
    monkeypatch.setattr("lawsearch.app.main", lambda: calls.append(True))

    path = _ROOT / "streamlit_app.py"
    exec(  # noqa: S102 - executing our own committed entry point under test
        compile(path.read_text(encoding="utf-8"), str(path), "exec"),
        {"__name__": "streamlit_app"},
    )

    assert calls == [True]
