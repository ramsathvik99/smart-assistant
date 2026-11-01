"""Source installs must honour `OMNIVOICE_TORCH_VARIANT=rocm` (#1665).

`uv sync` always restores the lockfile's CUDA torch build, which is CPU-only
on AMD cards, and `uv run` re-syncs before every launch. These tests pin the
source flow: `scripts/setup.py` reinstalls the ROCm wheel after the sync, and
`scripts/dev-backend.mjs` launches with `uv run --no-sync` so it sticks.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SETUP = os.path.join(_ROOT, "scripts", "setup.py")
_DEV_BACKEND = os.path.join(_ROOT, "scripts", "dev-backend.mjs")


def _load_setup():
    spec = importlib.util.spec_from_file_location("vs_setup", _SETUP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rocm_opt_in_requires_explicit_variant():
    setup = _load_setup()
    assert setup._rocm_opt_in({}) is None
    assert setup._rocm_opt_in({"OMNIVOICE_TORCH_VARIANT": "auto"}) is None
    assert setup._rocm_opt_in({"OMNIVOICE_TORCH_VARIANT": "ROCm"}) == setup.ROCM_TORCH_INDEX
    assert (
        setup._rocm_opt_in({"OMNIVOICE_TORCH_VARIANT": "rocm", "OMNIVOICE_TORCH_INDEX": "https://x/"})
        == "https://x/"
    )


def test_rocm_reinstall_targets_this_venv_with_pinned_stack():
    setup = _load_setup()
    cmd = setup.rocm_torch_reinstall_cmd(setup.ROCM_TORCH_INDEX, python="/venv/bin/python")
    # #3158: only the torch stack is reinstalled and the ROCm index is an
    # extra one. `--index-url` + `--reinstall` forced Pillow onto PyTorch's
    # index (no Pillow 13), so the swap was unsatisfiable.
    assert "--reinstall" not in cmd and "--index-url" not in cmd
    assert cmd == [
        "uv",
        "pip",
        "install",
        "--python",
        "/venv/bin/python",
        "--reinstall-package", "torch",
        "--reinstall-package", "torchaudio",
        "--reinstall-package", "torchvision",
        "torch==2.8.0+rocm6.4",
        "torchaudio==2.8.0+rocm6.4",
        "torchvision==0.23.0+rocm6.4",
        "--extra-index-url",
        setup.ROCM_TORCH_INDEX,
        "--index-strategy",
        "unsafe-best-match",
    ]
    # A mirror without a rocm-style name keeps the bare pins.
    mirror = setup.rocm_torch_reinstall_cmd("https://idx/", python="/venv/bin/python")
    assert "torch==2.8.0" in mirror and "https://idx/" in mirror
    assert setup.ROCM_TORCH_PINS == (
        "torch==2.8.0",
        "torchaudio==2.8.0",
        "torchvision==0.23.0",
    )


def test_dev_backend_skips_resync_when_rocm_requested():
    module_uri = Path(_DEV_BACKEND).as_uri()
    script = f"""
      const mod = await import({json.dumps(module_uri)});
      console.log(JSON.stringify({{
        base: mod.uvicornArgs({{}}),
        unset: mod.uvRunArgs({{}}),
        auto: mod.uvRunArgs({{ OMNIVOICE_TORCH_VARIANT: "auto" }}),
        rocm: mod.uvRunArgs({{ OMNIVOICE_TORCH_VARIANT: " ROCm " }}),
      }}));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(completed.stdout)
    base = observed["base"]
    assert observed["unset"] == [base[0], "--no-sync", *base[1:]]
    assert observed["auto"] == [base[0], "--no-sync", *base[1:]]
    assert observed["rocm"] == [base[0], "--no-sync", *base[1:]]


def test_rocm_swap_is_verified_in_a_fresh_interpreter(monkeypatch, capsys):
    # Review on #3553: an untagged mirror can resolve ordinary wheels, so a
    # successful uv run is not proof of a ROCm build.
    setup = _load_setup()
    monkeypatch.setenv("OMNIVOICE_TORCH_VARIANT", "rocm")
    states = iter([False, False])  # before the swap, after the swap
    monkeypatch.setattr(setup, "_installed_torch_is_rocm", lambda: next(states))
    monkeypatch.setattr(setup.subprocess, "check_call", lambda cmd: 0)
    setup._ensure_rocm_torch()
    out = capsys.readouterr().out
    assert "no ROCm support" in out
    assert "✓ ROCm torch installed" not in out
