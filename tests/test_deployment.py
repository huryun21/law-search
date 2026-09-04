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


def test_gitignore_excludes_streamlit_secrets():
    entries = (_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".streamlit/secrets.toml" in entries


def test_streamlit_secrets_example_documents_the_key_without_a_value():
    text = (_ROOT / ".streamlit" / "secrets.toml.example").read_text(encoding="utf-8")

    assert "LAW_API_KEY" in text
    value = text.split("LAW_API_KEY", 1)[1].split("=", 1)[1].strip().strip('"')
    assert not value.isalnum() or len(value) < 20, "example must not hold a real key"
