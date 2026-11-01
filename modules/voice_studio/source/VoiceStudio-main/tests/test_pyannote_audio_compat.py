"""Real local WAV I/O and strict older-stack no-op for the retired audio APIs."""
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile
import torch


def test_old_complete_api_is_identity_noop(monkeypatch):
    from services.pyannote_audio_compat import ensure_pyannote_audio_compat

    original = SimpleNamespace(AudioMetaData=object(), info=object(),
                               list_audio_backends=object(), load=object())
    before = vars(original).copy()
    monkeypatch.setitem(sys.modules, "torchaudio", original)
    assert not ensure_pyannote_audio_compat()
    assert vars(original) == before


def test_missing_api_dispatches_only_explicit_soundfile(monkeypatch, tmp_path):
    from services.pyannote_audio_compat import ensure_pyannote_audio_compat

    calls = []
    original = SimpleNamespace(load=lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setitem(sys.modules, "torchaudio", original)
    assert ensure_pyannote_audio_compat()
    assert not ensure_pyannote_audio_compat()
    assert original.list_audio_backends() == ["soundfile"]
    original.load("default")
    original.load("other", backend="ffmpeg")
    assert calls == [(("default",), {}), (("other",), {"backend": "ffmpeg"})]
    wav = tmp_path / "speech.wav"
    samples = np.arange(200, dtype=np.int16).reshape(100, 2)
    soundfile.write(wav, samples, 16000, subtype="PCM_16")
    info = original.info(wav)
    assert tuple(info) == (16000, 100, 2, 16, "PCM_S")
    waveform, rate = original.load(wav, 10, 20, False, True, backend="soundfile")
    assert rate == 16000 and waveform.dtype == torch.int16
    np.testing.assert_array_equal(waveform.numpy(), samples[10:30].T)


@pytest.mark.parametrize("subtype,dtype", [("PCM_U8", torch.uint8), ("FLOAT", torch.float32)])
def test_native_dtype_and_normalization(tmp_path, subtype, dtype):
    from services.pyannote_audio_compat import _soundfile_load

    wav = tmp_path / "sample.wav"
    soundfile.write(wav, np.array([-0.5, 0, 0.5]), 16000, subtype=subtype)
    native, _ = _soundfile_load(wav, normalize=False)
    normalized, _ = _soundfile_load(wav)
    assert native.dtype == dtype
    torch.testing.assert_close(normalized, torch.tensor([[-0.5, 0, 0.5]]))


def test_invalid_ranges_rejected_before_open():
    from services.pyannote_audio_compat import _soundfile_load

    with pytest.raises(ValueError):
        _soundfile_load("missing.wav", frame_offset=-1)
