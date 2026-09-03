# Streamlit Community Cloud Private Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository deployable as a private Streamlit Community Cloud app — the app runs from `st.secrets` for its API key when no local key file exists, has a Cloud entry point, and has pinned dependencies — without changing any local (Windows / `run.bat`) behaviour.

**Architecture:** `lawsearch.config` gains a single credential resolver, `resolve_api_key(settings, secrets)`, that prefers a `LAW_API_KEY` secret and falls back to the existing local key file; `Settings.api_key_file` becomes optional and `load_settings` no longer requires a `config.local.toml`. `lawsearch.app` reads `st.secrets` through a small helper and passes the resolved key straight to `LawApiClient` — the value never touches `Settings`, the cache, logs, or the screen. A root `streamlit_app.py` delegates to `lawsearch.app.main`, and `requirements.txt` pins the tested dependency versions and installs the package.

**Tech Stack:** Python 3.11+, Streamlit 1.63.0, httpx 0.28.1, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-03-desktop-search-workspace-design.md` §8 (private team deployment), §7 (`lawsearch.config` boundary), §10 (test list items for the local-file / secrets paths). Read that spec plus `docs/CLAUDE_HANDOFF.md` §8 and `CLAUDE.md`.

## PREREQUISITE — do not execute before this is true

This plan modifies `src/lawsearch/app.py` (`_search`, `_contexts`) and `tests/test_app.py` (`test_search_client_is_closed_in_the_same_event_loop`), which PR #1 (`feature/desktop-search-workspace-ui`) also rewrites. **Execute this plan only after PR #1 is merged into `main`.** Before starting:

```bash
git checkout main && git pull
git log --oneline -1        # expect the PR #1 merge / "feat: add side-by-side compare view" ancestry
.venv/Scripts/python.exe -m pytest -q   # expect 198 passed, 7 skipped
git checkout -b feature/streamlit-cloud-deployment
```

If this plan's own branch (`feature/streamlit-cloud-deployment`) was created earlier from a pre-merge `main` and already holds this document, rebase it onto the merged `main` first (`git rebase main`) — the only file it carries is this plan doc, so the rebase is trivial.

All line numbers below refer to the **post-PR-#1** `main`.

## Global Constraints

Every task's requirements implicitly include this section.

- **Credential handling.** The `LAW_API_KEY` value comes only from `st.secrets` (Cloud) or the local key file (`load_api_key`). It is passed only to `LawApiClient(...)`. It must never appear in `Settings`, the SQLite cache, logs, error messages, test output, the screen, or git. A test asserts `Settings` has no credential field.
- **`Settings` shape.** `Settings(api_key_file: Path | None, cache_path: Path)` — `api_key_file` is `None` when neither `config.local.toml` nor `LAW_API_KEY_FILE` supplies a path. `cache_path` always resolves (default `data/cache.db` under the project root).
- **Local behaviour is unchanged.** `run.bat` still requires `config.local.toml` and still runs on `127.0.0.1` only. Do not modify `run.bat`. The local flow (key file via `config.local.toml` or `LAW_API_KEY_FILE`) keeps working exactly as before.
- **Dependency pins.** `requirements.txt` pins `streamlit` and `httpx` to the exact versions currently installed in `.venv` (`streamlit==1.63.0`, `httpx==0.28.1` at time of writing — a task asserts the pins equal the importable `__version__`), and contains `.` so Community Cloud installs the `lawsearch` package. `pyproject.toml` dependency ranges are not changed.
- **Never commit** `.streamlit/secrets.toml` or `config.local.toml`. `.streamlit/secrets.toml.example` (no real key) is committed.
- **Ephemeral Cloud cache.** Do not add code that assumes the SQLite cache persists across restarts — the app already re-fetches from the official API when the cache is gone; keep it that way.
- **Deploy source.** `main` branch is the Community Cloud deploy source (spec §8.4). Actual Cloud dashboard steps — creating the app, entering secrets, inviting viewers, setting it private — are performed by the user, not this plan.
- **TDD, `.venv/Scripts/python.exe -m pytest -q` for the suite, one purpose per commit.** End every commit message with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  ```
  No `git push`, deployment, or repo-setting change without explicit user approval.

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `streamlit_app.py` (repo root) | Community Cloud entry point. Imports and calls `lawsearch.app.main`. No logic. |
| `requirements.txt` (repo root) | Pins `streamlit` / `httpx` to tested versions and installs the local package (`.`) so Cloud can import `lawsearch`. |
| `.streamlit/secrets.toml.example` | Documents the one secret (`LAW_API_KEY`) the Cloud app needs. Committed; the real `.streamlit/secrets.toml` is git-ignored. |
| `tests/test_deployment.py` | Tests for `streamlit_app.py`, `requirements.txt`, `.gitignore`, and `.streamlit/secrets.toml.example`. |

**Modified:**

| File | Change |
| --- | --- |
| `src/lawsearch/config.py` | `Settings.api_key_file: Path | None`; `load_settings` treats a missing `config.local.toml` as empty config and defaults `cache_path`; new `resolve_api_key(settings, secrets=None) -> str`. |
| `src/lawsearch/app.py` | New `_app_secrets() -> Mapping[str, str]` reading `st.secrets`; `_search` and `_contexts` call `resolve_api_key(settings, _app_secrets())` instead of `load_api_key(settings.api_key_file)`; import cleanup. |
| `tests/test_config.py` | Add resolver / missing-config / credential-shape tests. |
| `tests/test_app.py` | `test_search_client_is_closed_in_the_same_event_loop` monkeypatches `app.resolve_api_key` instead of `app.load_api_key`. |
| `.gitignore` | Add `.streamlit/secrets.toml`. |
| `README.md` | New "## Streamlit Community Cloud 배포" section; local section unchanged. |
| `docs/CLAUDE_HANDOFF.md` | §8: mark repo preparation done; list only the user's dashboard steps as remaining. |
| `CLAUDE.md` | "현재 제품 경계": note the repo is Cloud-deployable; actual deploy is the user's dashboard action. |

---

## Task 1: `Settings.api_key_file` optional and `load_settings` without a config file

**Files:**
- Modify: `src/lawsearch/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings(api_key_file: Path | None, cache_path: Path)` — frozen dataclass, `api_key_file` may be `None`.
- Produces: `load_settings(project_root: Path, environ: Mapping[str, str] | None = None) -> Settings` — a missing `config.local.toml` is not an error; `cache_path` defaults to `project_root / "data/cache.db"`; a malformed `config.local.toml` still raises `ConfigError`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py` (the file already imports `ConfigError, load_api_key, load_settings` and `pytest`, `Path`):

```python
from lawsearch.config import Settings


def test_load_settings_without_config_file_has_no_key_file_and_default_cache(tmp_path):
    settings = load_settings(tmp_path, {})

    assert settings.api_key_file is None
    assert settings.cache_path == tmp_path / "data" / "cache.db"


def test_load_settings_env_key_file_works_without_a_config_file(tmp_path):
    key_file = tmp_path / "law-key.txt"

    settings = load_settings(tmp_path, {"LAW_API_KEY_FILE": str(key_file)})

    assert settings.api_key_file == key_file
    assert settings.cache_path == tmp_path / "data" / "cache.db"


def test_load_settings_still_rejects_a_malformed_config_file(tmp_path):
    (tmp_path / "config.local.toml").write_text("this is not = valid = toml", encoding="utf-8")

    with pytest.raises(ConfigError, match="형식"):
        load_settings(tmp_path, {})
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -q -k "without_config_file or without_a_config_file or malformed_config"`
Expected: FAIL — `load_settings` raises `ConfigError("로컬 설정 파일을 찾을 수 없습니다.")` when the file is missing.

- [ ] **Step 3: Implement**

In `src/lawsearch/config.py`:

Change the `Settings` dataclass:

```python
@dataclass(frozen=True)
class Settings:
    api_key_file: Path | None
    cache_path: Path
```

Replace the body of `load_settings` from the `try:` block through the `return` with:

```python
    config_path = project_root / "config.local.toml"
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        config = {}
    except tomllib.TOMLDecodeError as error:
        raise ConfigError("로컬 설정 파일 형식이 올바르지 않습니다.") from error

    environment = process_environ if environ is None else environ
    api_key_file = environment.get("LAW_API_KEY_FILE", config.get("api_key_file"))
    cache_path = (
        environment.get("LAW_CACHE_PATH", config.get("cache_path"))
        or "data/cache.db"
    )

    resolved_cache_path = Path(cache_path)
    if not resolved_cache_path.is_absolute():
        resolved_cache_path = project_root / resolved_cache_path

    return Settings(
        api_key_file=Path(api_key_file) if api_key_file else None,
        cache_path=resolved_cache_path,
    )
```

(The old `if not api_key_file or not cache_path: raise ConfigError(...)` line is removed.)

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -q`
Expected: PASS — including the pre-existing `test_settings_store_only_external_key_path`, `test_environment_overrides_local_config`, `test_plaintext_key_is_trimmed`, `test_labeled_key_file_selects_exact_law_api_field`, `test_empty_key_file_is_rejected`.

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. If `test_search_client_is_closed_in_the_same_event_loop` fails here it is because `app._load_resources` / `_search` now sees `api_key_file=None` in some path — it should not yet; that test still monkeypatches `load_api_key`. Investigate before continuing.

- [ ] **Step 6: Commit**

```bash
git add src/lawsearch/config.py tests/test_config.py
git commit -m "feat: allow settings without a local config file"
```

---

## Task 2: `resolve_api_key` credential resolver

**Files:**
- Modify: `src/lawsearch/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Settings.api_key_file` (Task 1), `load_api_key(path)` (unchanged).
- Produces: `resolve_api_key(settings: Settings, secrets: Mapping[str, str] | None = None) -> str`
  - non-empty `secrets["LAW_API_KEY"]` (stripped) wins;
  - else `load_api_key(settings.api_key_file)` when `api_key_file is not None`;
  - else raise `ConfigError`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
from lawsearch.config import resolve_api_key


def _settings_with_key_file(tmp_path, contents="file-key"):
    key_file = tmp_path / "law-key.txt"
    key_file.write_text(contents, encoding="utf-8")
    return Settings(api_key_file=key_file, cache_path=tmp_path / "data" / "cache.db")


def test_resolve_api_key_prefers_secret_over_file(tmp_path):
    settings = _settings_with_key_file(tmp_path)

    assert resolve_api_key(settings, {"LAW_API_KEY": " secret-key "}) == "secret-key"


def test_resolve_api_key_falls_back_to_local_file(tmp_path):
    settings = _settings_with_key_file(tmp_path)

    assert resolve_api_key(settings, {}) == "file-key"
    assert resolve_api_key(settings, None) == "file-key"


def test_resolve_api_key_ignores_blank_secret(tmp_path):
    settings = _settings_with_key_file(tmp_path)

    assert resolve_api_key(settings, {"LAW_API_KEY": "   "}) == "file-key"


def test_resolve_api_key_raises_when_no_source_available(tmp_path):
    settings = Settings(api_key_file=None, cache_path=tmp_path / "data" / "cache.db")

    with pytest.raises(ConfigError):
        resolve_api_key(settings, {})


def test_resolve_api_key_labeled_file_still_selects_the_law_field(tmp_path):
    settings = _settings_with_key_file(
        tmp_path,
        "6. other: wrong\n7. 국가법령정보 공동활용: selected-law-value\n",
    )

    assert resolve_api_key(settings, None) == "selected-law-value"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -q -k resolve_api_key`
Expected: FAIL — `ImportError: cannot import name 'resolve_api_key'`.

- [ ] **Step 3: Implement**

In `src/lawsearch/config.py`, add after `load_api_key`:

```python
def resolve_api_key(
    settings: Settings, secrets: Mapping[str, str] | None = None
) -> str:
    """Return the API key from a Cloud secret, else the local key file."""
    if secrets:
        secret_value = secrets.get("LAW_API_KEY")
        if secret_value is not None and str(secret_value).strip():
            return str(secret_value).strip()
    if settings.api_key_file is not None:
        return load_api_key(settings.api_key_file)
    raise ConfigError(
        "API 인증정보가 없습니다. 로컬은 config.local.toml, "
        "클라우드는 st.secrets의 LAW_API_KEY가 필요합니다."
    )
```

`Mapping` is already imported in `config.py` (`from typing import Mapping`).

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lawsearch/config.py tests/test_config.py
git commit -m "feat: add resolve_api_key with secret-then-file fallback"
```

---

## Task 3: App reads the key from `st.secrets` or the local file

**Files:**
- Modify: `src/lawsearch/app.py`
- Modify: `tests/test_app.py`
- Test: `tests/test_config.py` (a small integration test for `_app_secrets`)

**Interfaces:**
- Consumes: `resolve_api_key` (Task 2).
- Produces: `_app_secrets() -> Mapping[str, str]` in `lawsearch.app` — returns `{"LAW_API_KEY": <value>}` when `st.secrets` has it, otherwise `{}` (never raises).
- `_search` and `_contexts` build `LawApiClient(resolve_api_key(settings, _app_secrets()))`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_app.py`, change `test_search_client_is_closed_in_the_same_event_loop`:

```python
    monkeypatch.setattr(app, "resolve_api_key", lambda settings, secrets: "test-key")
```

(replacing the `monkeypatch.setattr(app, "load_api_key", lambda path: "test-key")` line), and add:

```python
def test_app_secrets_returns_empty_without_a_secrets_file(monkeypatch):
    import types

    fake_streamlit = types.SimpleNamespace()

    class _NoSecrets:
        def __contains__(self, key):
            raise RuntimeError("no secrets file")

        def __getitem__(self, key):
            raise RuntimeError("no secrets file")

    fake_streamlit.secrets = _NoSecrets()
    monkeypatch.setitem(__import__("sys").modules, "streamlit", fake_streamlit)

    assert app._app_secrets() == {}


def test_app_secrets_reads_law_api_key_when_present(monkeypatch):
    import types

    fake_streamlit = types.SimpleNamespace(secrets={"LAW_API_KEY": "cloud-key"})
    monkeypatch.setitem(__import__("sys").modules, "streamlit", fake_streamlit)

    assert app._app_secrets() == {"LAW_API_KEY": "cloud-key"}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -q -k "app_secrets or client_is_closed"`
Expected: FAIL — `app` has no attribute `_app_secrets`; `client_is_closed` fails because `resolve_api_key` is not yet imported into `app`.

- [ ] **Step 3: Implement**

In `src/lawsearch/app.py`:

- Change the config import to:
  ```python
  from lawsearch.config import ConfigError, Settings, load_settings, resolve_api_key
  ```
  (drop `load_api_key` — it is no longer referenced in `app.py`).
- Add `Mapping` to the typing import:
  ```python
  from typing import TYPE_CHECKING, Any, Awaitable, Mapping, TypeVar
  ```
- Add the helper (near `_run`):
  ```python
  def _app_secrets() -> Mapping[str, str]:
      try:
          import streamlit as st

          return {
              key: str(st.secrets[key])
              for key in ("LAW_API_KEY",)
              if key in st.secrets
          }
      except Exception:
          return {}
  ```
- In `_search`, replace `LawApiClient(load_api_key(settings.api_key_file))` with:
  ```python
  LawApiClient(resolve_api_key(settings, _app_secrets()))
  ```
- In `_contexts`, make the same replacement.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -q`
Expected: PASS

- [ ] **Step 5: Full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (198 → 200+ with the two new `_app_secrets` tests; exact count depends on Task 1/2 additions).

- [ ] **Step 6: Commit**

```bash
git add src/lawsearch/app.py tests/test_app.py
git commit -m "feat: resolve the API key from st.secrets or the local file"
```

---

## Task 4: `streamlit_app.py` Cloud entry point

**Files:**
- Create: `streamlit_app.py`
- Test: `tests/test_deployment.py`

**Interfaces:**
- Consumes: `lawsearch.app.main`.
- Produces: a repo-root module that runs `lawsearch.app.main()` on import/execution.

- [ ] **Step 1: Write the failing test**

Create `tests/test_deployment.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deployment.py -q`
Expected: FAIL — `FileNotFoundError: streamlit_app.py`.

- [ ] **Step 3: Implement**

Create `streamlit_app.py` at the repo root:

```python
"""Streamlit Community Cloud entry point.

Community Cloud runs ``streamlit run streamlit_app.py`` from the repository
root. All UI, state, and configuration live in :mod:`lawsearch.app`.
"""

from lawsearch.app import main

main()
```

- [ ] **Step 4: Run test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deployment.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add streamlit_app.py tests/test_deployment.py
git commit -m "feat: add Streamlit Community Cloud entry point"
```

---

## Task 5: `requirements.txt`

**Files:**
- Create: `requirements.txt`
- Test: `tests/test_deployment.py`

**Interfaces:**
- Produces: a repo-root `requirements.txt` that Community Cloud installs with `pip install -r requirements.txt`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_deployment.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deployment.py -q -k requirements`
Expected: FAIL — `FileNotFoundError: requirements.txt`.

- [ ] **Step 3: Implement**

Create `requirements.txt` at the repo root. Read the exact versions first:

```bash
.venv/Scripts/python.exe -c "import streamlit, httpx; print(streamlit.__version__, httpx.__version__)"
```

Then write (substituting the printed versions):

```
# Streamlit Community Cloud installs from this file.
# Pins match the versions the test suite runs against.
streamlit==1.63.0
httpx==0.28.1
.
```

- [ ] **Step 4: Run test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deployment.py -q -k requirements`
Expected: PASS

- [ ] **Step 5: Sanity-check resolution (no install)**

Run: `.venv/Scripts/python.exe -m pip install -r requirements.txt --dry-run`
Expected: resolves without conflict; reports `streamlit`, `httpx`, and `lawsearch` already satisfied / to-be-installed. Do not perform a real install.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt tests/test_deployment.py
git commit -m "feat: pin deployment dependencies in requirements.txt"
```

---

## Task 6: Ignore `.streamlit/secrets.toml`, add the example

**Files:**
- Modify: `.gitignore`
- Create: `.streamlit/secrets.toml.example`
- Test: `tests/test_deployment.py`

**Interfaces:** none (config files).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_deployment.py`:

```python
def test_gitignore_excludes_streamlit_secrets():
    entries = (_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".streamlit/secrets.toml" in entries


def test_streamlit_secrets_example_documents_the_key_without_a_value():
    example = _ROOT / ".streamlit" / "secrets.toml.example"
    text = example.read_text(encoding="utf-8")
    assert "LAW_API_KEY" in text
    # placeholder only — never a real-looking key
    assert "=" in text
    value = text.split("LAW_API_KEY", 1)[1].split("=", 1)[1].strip().strip('"')
    assert not value or not value.isalnum() or len(value) < 20
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deployment.py -q -k "gitignore or secrets_example"`
Expected: FAIL — `.streamlit/secrets.toml` not in `.gitignore`; example file missing.

- [ ] **Step 3: Implement**

Append to `.gitignore` (after `.superpowers/`):

```
.streamlit/secrets.toml
```

Create `.streamlit/secrets.toml.example`:

```toml
# Streamlit Community Cloud: 앱 관리 화면 > Settings > Secrets 에 아래 한 줄을 붙여넣으세요.
# 로컬에서 클라우드 인증 경로를 시험하려면 이 파일을 .streamlit/secrets.toml 로 복사하고 값을 채우세요.
# .streamlit/secrets.toml 은 Git에 커밋하지 않습니다 (.gitignore).
LAW_API_KEY = "국가법령정보 공동활용 승인 키를 여기에"
```

- [ ] **Step 4: Run tests + confirm nothing sensitive is staged**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deployment.py -q`
Then: `git status --porcelain` — confirm only `.gitignore` and `.streamlit/secrets.toml.example` are new/changed, and no `.streamlit/secrets.toml`.

- [ ] **Step 5: Commit**

```bash
git add .gitignore .streamlit/secrets.toml.example tests/test_deployment.py
git commit -m "chore: ignore streamlit secrets and add the example"
```

---

## Task 7: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/CLAUDE_HANDOFF.md`
- Modify: `CLAUDE.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: README — add a Cloud deployment section**

In `README.md`, after the "## 검증" section and before "## 법적·출처 고지", add:

```markdown
## Streamlit Community Cloud 배포

로컬 실행과 별개로, 저장소를 Community Cloud 비공개 앱으로 배포할 수 있습니다. `main` 브랜치가 배포 원본입니다.

1. Community Cloud에서 이 저장소를 연결하고 브랜치 `main`, 메인 파일 `streamlit_app.py`를 선택합니다.
2. 앱 관리 화면 > Settings > Secrets 에 다음을 입력합니다. (`.streamlit/secrets.toml.example` 참고)

   ```toml
   LAW_API_KEY = "국가법령정보 공동활용 승인 키"
   ```

3. 앱을 비공개로 설정하고 팀원 이메일을 뷰어로 초대합니다. 워크스페이스당 비공개 앱은 1개로 제한됩니다.
4. 의존성은 `requirements.txt`로 고정됩니다. 버전을 바꾸면 재설치가 일어납니다.

API 키는 `st.secrets`에서만 읽어 API 클라이언트를 만들 때만 전달되며, 저장소·설정 객체·SQLite·로그·화면에는 남지 않습니다. 클라우드의 SQLite 캐시는 컨테이너 재시작 시 사라지며, 이 경우 공식 API에서 다시 조회합니다. `.streamlit/secrets.toml`은 커밋하지 마십시오.
```

Leave the "## 설치 및 설정" and "## 실행과 검색 문법" sections unchanged — they describe the local flow.

- [ ] **Step 2: CLAUDE_HANDOFF §8 — repo prep done**

In `docs/CLAUDE_HANDOFF.md` §8, replace the "먼저 구현해야 할 항목" list (the 6 numbered items) with:

```markdown
저장소 준비는 완료됐다(2026-09-03):

- 루트 `streamlit_app.py` 진입점, `requirements.txt` 버전 고정, `.streamlit/secrets.toml` Git 제외, `.streamlit/secrets.toml.example`
- `lawsearch.config.resolve_api_key()`가 `st.secrets`의 `LAW_API_KEY` → 로컬 키 파일 순으로 인증값을 고른다. `Settings`에는 인증값을 담지 않는다.
- `config.local.toml`이 없어도 앱이 시작된다(캐시 경로 기본값 `data/cache.db`).

남은 작업은 저장소 코드가 아니라 사용자의 Community Cloud 대시보드 작업이다: 앱 생성, `main`/`streamlit_app.py` 지정, Secrets에 `LAW_API_KEY` 입력, 비공개 설정, 팀원 이메일 초대.
```

- [ ] **Step 3: CLAUDE.md — product boundary**

In `CLAUDE.md` under "## 현재 제품 경계", change the first bullet from:

```
- 현재 배포된 제품은 아니다. run.bat가 로컬 PC의 http://127.0.0.1:8501에서 Streamlit을 실행한다.
```

to:

```
- run.bat가 로컬 PC의 http://127.0.0.1:8501에서 Streamlit을 실행한다. 저장소는 Streamlit Community Cloud 비공개 배포가 가능하도록 구성돼 있으나(streamlit_app.py, requirements.txt, st.secrets 인증), 실제 배포·Secrets 입력·팀원 초대는 사용자가 대시보드에서 수행한다.
```

- [ ] **Step 4: Secret scan on the docs**

Run:
```bash
git diff --staged -- README.md docs/CLAUDE_HANDOFF.md CLAUDE.md | grep -nE "OC=[A-Za-z0-9]|내 드라이브|[A-Za-z0-9]{24,}" || echo "clean"
```
Expected: `clean`.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/CLAUDE_HANDOFF.md CLAUDE.md
git commit -m "docs: document Streamlit Community Cloud deployment"
```

---

## Task 8: Final verification

**Files:** none (verification only).

- [ ] **Step 1: Full suite, verbose**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: all pass, only the 7 live-API tests skipped. Record the counts.

- [ ] **Step 2: Credential-leak scan across the tree**

Run:
```bash
git grep -n -I -E "OC=[A-Za-z0-9]|내 드라이브|my_api_keys\.txt" -- ':!docs/**' ':!tests/**' ':!src/lawsearch/data/region_api_verification.json'
```
Expected: no matches. Then:
```bash
git grep -n -I "LAW_API_KEY" -- ':!docs/**' ':!.streamlit/**' ':!README.md'
```
Expected: matches only in `src/lawsearch/config.py`, `src/lawsearch/app.py`, and test files — and every match is a key *name*, never a value.

- [ ] **Step 3: `Settings` has no credential field**

Run:
```bash
.venv/Scripts/python.exe -c "import dataclasses; from lawsearch.config import Settings; print([f.name for f in dataclasses.fields(Settings)])"
```
Expected: `['api_key_file', 'cache_path']` — no `api_key`.

- [ ] **Step 4: Local flow still works (no regression)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py tests/test_app.py -q`
Expected: PASS — the local key-file tests (`test_settings_store_only_external_key_path`, `test_plaintext_key_is_trimmed`, `test_labeled_key_file_selects_exact_law_api_field`, `test_environment_overrides_local_config`, `test_search_client_is_closed_in_the_same_event_loop`) confirm the Windows path is unchanged.

- [ ] **Step 5: `requirements.txt` resolves**

Run: `.venv/Scripts/python.exe -m pip install -r requirements.txt --dry-run`
Expected: no resolution error.

- [ ] **Step 6: `git diff --check`**

Run: `git diff --check main...HEAD`
Expected: clean.

- [ ] **Step 7: Report**

Summarize: test counts, files added/changed, the credential-leak scan result, and the exact user-side dashboard steps that remain (from CLAUDE_HANDOFF §8). Do not push. Hand back for review; the user creates PR #2 or merges per the finishing-a-development-branch flow.

---

## Self-Review

**1. Spec coverage (§8 and related)**

| Spec requirement | Task |
| --- | --- |
| §8.2 root `streamlit_app.py` entry point | Task 4 |
| §8.2 `requirements.txt` pinning tested Streamlit version | Task 5 |
| §8.2 exclude `.streamlit/secrets.toml`, `config.local.toml`, SQLite, logs, `.superpowers/` from Git | Task 6 (`.streamlit/secrets.toml` is the only one not already ignored — verified against current `.gitignore`) |
| §8.2 README separates local run vs Cloud deploy | Task 7 Step 1 |
| §8.3 local = `LAW_API_KEY_FILE` / `config.local.toml` key file | Task 2 (`resolve_api_key` file fallback); Task 1 (`load_settings` env + config) |
| §8.3 Cloud = `st.secrets` `LAW_API_KEY`, passed only to the API client | Task 2 + Task 3 |
| §8.3 value never in repo/Settings/SQLite/logs/screen; `.streamlit/secrets.toml` not in Git | Global Constraints; Task 3 (`_app_secrets` isolates it); Task 6; Task 8 Steps 2–3 |
| §8.4 `main` branch = deploy source | Global Constraints; Task 7 Step 1 |
| §8.1 one private app per workspace; email viewers | Task 7 Step 1 (documented); dashboard action is the user's |
| §7 `lawsearch.config` selects an available auth source; `Settings` holds no credential | Task 1 + Task 2; Task 8 Step 3 |
| §6 / §8 Cloud SQLite is ephemeral, app still works without it | Global Constraints (no code assumes persistence — `load_settings` only sets a path; `CacheStore` already tolerates a fresh DB) |
| §10 "`Settings`와 직렬화 가능한 상태에 API 인증값이 없다" | Task 8 Step 3; `resolve_api_key` returns a local `str`, never stored |
| §10 "로컬 키 파일과 Streamlit 비밀값 경로가 각각 동작한다" | Task 2 tests (`prefers_secret_over_file`, `falls_back_to_local_file`); Task 3 tests |
| §12 step 5 (Cloud entrypoint, deps, secrets loading) | Tasks 4–6 |

Gap: none. The spec's §8 items are repo-side; the dashboard steps (app creation, secrets entry, invites, privacy) are explicitly the user's and are documented, not automated.

**2. Placeholder scan** — No "TBD" / "handle edge cases" / "similar to Task N". Task 5 Step 3 asks the implementer to read the live versions and substitute them into `requirements.txt`; the test in Step 1 pins the file to `streamlit.__version__` / `httpx.__version__` so a wrong copy fails immediately. That is a deliberate read-then-write, not a placeholder.

**3. Type consistency**
- `Settings(api_key_file: Path | None, cache_path: Path)` — Task 1 defines; Task 2 (`settings.api_key_file is not None`), Task 3, and Task 8 Step 3 all use exactly this shape.
- `resolve_api_key(settings: Settings, secrets: Mapping[str, str] | None = None) -> str` — Task 2 defines; Task 3 calls `resolve_api_key(settings, _app_secrets())`; `tests/test_app.py` monkeypatch signature `lambda settings, secrets: "test-key"` matches.
- `_app_secrets() -> Mapping[str, str]` — Task 3 defines and uses; returns `{}` or `{"LAW_API_KEY": str}`, which is a valid `Mapping[str, str]` argument to `resolve_api_key`.
- `load_api_key(path: Path) -> str` — unchanged; `resolve_api_key` calls it with `settings.api_key_file` which is `Path` in that branch (guarded by `is not None`).
- `_search` / `_contexts` — signatures unchanged by this plan; only the `LawApiClient(...)` argument expression changes. `_contexts` keeps the `*, refresh=False, limit=5` shape introduced by PR #1.
