"""Conftest for unit/cli tests.

Stubs out heavy optional dependencies (tqdm, matplotlib) that are declared in
requirements.txt but may not be installed in the unit-test venv. This allows
importing jutsu_engine.cli.main (and submodules) without those packages present.

Must run before any test collection in this directory, which pytest guarantees
by loading all conftest.py files before collecting tests.
"""
import sys
import types


def _stub_if_missing(name: str, attrs: dict) -> None:
    """Register a module stub only if the real module is absent."""
    if name in sys.modules:
        return
    try:
        __import__(name)
    except ModuleNotFoundError:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod


# --- tqdm stub ---------------------------------------------------------------
class _TqdmStub:
    """Minimal tqdm stand-in that iterates transparently."""

    def __init__(self, iterable=None, *args, **kwargs):
        self._iter = iter(iterable) if iterable is not None else iter([])

    def __iter__(self):
        return self._iter

    def update(self, *args, **kwargs):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


_stub_if_missing("tqdm", {"tqdm": _TqdmStub})

# --- matplotlib stub ---------------------------------------------------------
_mpl_plt = types.ModuleType("matplotlib.pyplot")
_mpl_plt.figure = lambda *a, **kw: None  # type: ignore[attr-defined]
_mpl_plt.show = lambda *a, **kw: None  # type: ignore[attr-defined]
_mpl_plt.subplots = lambda *a, **kw: (None, None)  # type: ignore[attr-defined]
_mpl_plt.savefig = lambda *a, **kw: None  # type: ignore[attr-defined]
_mpl_plt.close = lambda *a, **kw: None  # type: ignore[attr-defined]

_mpl = types.ModuleType("matplotlib")
_mpl.pyplot = _mpl_plt  # type: ignore[attr-defined]
_mpl.use = lambda *a, **kw: None  # type: ignore[attr-defined]

_stub_if_missing("matplotlib", {"pyplot": _mpl_plt, "use": lambda *a, **kw: None})
_stub_if_missing("matplotlib.pyplot", {
    "figure": lambda *a, **kw: None,
    "show": lambda *a, **kw: None,
    "subplots": lambda *a, **kw: (None, None),
    "savefig": lambda *a, **kw: None,
    "close": lambda *a, **kw: None,
})
# Make matplotlib.pyplot accessible as an attribute of the matplotlib stub
if "matplotlib" in sys.modules:
    sys.modules["matplotlib"].pyplot = sys.modules.get(  # type: ignore[attr-defined]
        "matplotlib.pyplot", _mpl_plt
    )
