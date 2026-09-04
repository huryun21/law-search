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


def test_requirements_pin_tested_versions_and_install_the_package():
    import httpx
    import streamlit

    lines = [
        line.strip()
        for line in (_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert "." in lines, "requirements.txt must install the lawsearch package"

    pins = dict(line.split("==", 1) for line in lines if "==" in line)
    assert pins.get("streamlit") == streamlit.__version__
    assert pins.get("httpx") == httpx.__version__
