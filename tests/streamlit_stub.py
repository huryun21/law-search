"""Minimal recording stub for the Streamlit surface the app renders with."""

from __future__ import annotations

from contextlib import contextmanager


class Rerun(RuntimeError):
    """Raised by FakeStreamlit.rerun() to model Streamlit stopping the script."""


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        self[name] = value


class _Child:
    def __init__(self, parent):
        self._parent = parent

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        return getattr(self._parent, name)


class FakeStreamlit:
    def __init__(self, session_state=None, *, buttons=None, selections=None):
        self.session_state = SessionState(session_state or {})
        self.calls: list[tuple[str, tuple, dict]] = []
        self.reruns = 0
        self.fragment_schedules: list[dict] = []
        self.fragment_runs: list[str] = []
        self._buttons = dict(buttons or {})
        self._selections = dict(selections or {})

    # recording helpers -------------------------------------------------
    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def names(self) -> list[str]:
        return [name for name, _, _ in self.calls]

    def text(self, *, sep=" ") -> str:
        return sep.join(str(arg) for _, args, _ in self.calls for arg in args)

    # passive widgets -------------------------------------------------
    def markdown(self, *a, **k):
        self._record("markdown", *a, **k)

    def caption(self, *a, **k):
        self._record("caption", *a, **k)

    def subheader(self, *a, **k):
        self._record("subheader", *a, **k)

    def title(self, *a, **k):
        self._record("title", *a, **k)

    def write(self, *a, **k):
        self._record("write", *a, **k)

    def info(self, *a, **k):
        self._record("info", *a, **k)

    def warning(self, *a, **k):
        self._record("warning", *a, **k)

    def error(self, *a, **k):
        self._record("error", *a, **k)

    def divider(self, *a, **k):
        self._record("divider", *a, **k)

    def link_button(self, label, url, *a, **k):
        self._record("link_button", label, url, *a, **k)

    def set_page_config(self, *a, **k):
        self._record("set_page_config", *a, **k)

    # active widgets -------------------------------------------------
    def button(self, label, *a, **k):
        self._record("button", label, *a, **k)
        return bool(self._buttons.get(k.get("key", label), False))

    def form_submit_button(self, label, *a, **k):
        self._record("form_submit_button", label, *a, **k)
        return bool(self._buttons.get(label, False))

    def radio(self, label, options, *a, **k):
        self._record("radio", label, options, *a, **k)
        options = list(options)
        return self._selections.get(
            k.get("key", label), options[0] if options else None
        )

    def selectbox(self, label, options, *a, **k):
        self._record("selectbox", label, options, *a, **k)
        options = list(options)
        return self._selections.get(
            k.get("key", label), options[0] if options else None
        )

    def text_input(self, *a, **k):
        self._record("text_input", *a, **k)
        return self._selections.get("text_input", "")

    def rerun(self):
        self.reruns += 1
        raise Rerun()

    def fragment(self, *a, **k):
        """Record that a fragment was scheduled, then run it once.

        Real ``st.fragment(run_every=...)`` runs the decorated function on this
        script run and re-runs it on the timer afterwards -- so a schedule that
        never happens is a timer that never fires. ``fragment_schedules`` is
        what a test asserts on to tell "scheduled" from "not scheduled".
        """
        self._record("fragment", *a, **k)
        self.fragment_schedules.append(dict(k))

        def decorate(function):
            def scheduled(*args, **kwargs):
                self.fragment_runs.append(getattr(function, "__name__", repr(function)))
                return function(*args, **kwargs)

            return scheduled

        return decorate

    # layout -------------------------------------------------
    def columns(self, spec, *a, **k):
        self._record("columns", spec, *a, **k)
        count = spec if isinstance(spec, int) else len(spec)
        return [_Child(self) for _ in range(count)]

    @contextmanager
    def container(self, *a, **k):
        self._record("container", *a, **k)
        yield self

    @contextmanager
    def expander(self, label, *a, **k):
        self._record("expander", label, *a, **k)
        yield self

    @contextmanager
    def form(self, *a, **k):
        self._record("form", *a, **k)
        yield self

    @contextmanager
    def spinner(self, *a, **k):
        self._record("spinner", *a, **k)
        yield self

    @property
    def sidebar(self):
        self._record("sidebar")
        return _Child(self)
