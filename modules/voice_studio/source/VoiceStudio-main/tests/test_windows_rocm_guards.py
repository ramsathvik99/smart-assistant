"""Windows setup uses its native installer; Linux indexes never cross platforms."""
import importlib
import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_source_setup_never_installs_linux_rocm_wheels(platform, monkeypatch):
    path = Path(__file__).parents[1] / "scripts" / "setup.py"
    spec = importlib.util.spec_from_file_location("vs_setup_guards", path)
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    called = []
    native = []
    monkeypatch.setattr("sys.platform", platform)
    monkeypatch.setenv("OMNIVOICE_TORCH_VARIANT", "rocm")
    monkeypatch.setattr(setup, "_ensure_vcredist_windows", lambda: None)
    monkeypatch.setattr(setup, "_ensure_rocm_torch", lambda: called.append(True))
    monkeypatch.setattr(setup, "_find_compat_dir", lambda: None)
    monkeypatch.setattr(setup.subprocess, "check_call", lambda command, **kwargs: native.append(command))
    setup.main()
    assert called == []
    assert [command[1:3] for command in native] == (
        [["-m", "backend.core.windows_rocm.install"]] if platform == "win32" else []
    )


@pytest.mark.parametrize("family", ["cpu", "rocm"])
def test_windows_sidecar_cannot_select_linux_rocm_index(family, monkeypatch):
    si = importlib.import_module("services.sidecar_install")
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("OMNIVOICE_TORCH_VARIANT", "rocm")
    monkeypatch.setattr(si, "_host_family", lambda: family)
    assert si._rocm_index_url() is None


@pytest.mark.parametrize("state", ["amd_cuda_build:win32", "amd_cpu_build:win32"])
def test_windows_gpu_report_has_no_unavailable_automatic_recipe(state):
    report = importlib.import_module("core.gpu_report")
    assert report._OPTIONS[state] == ("vulkan_engines", "rocm_windows_manual")
