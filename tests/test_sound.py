from __future__ import annotations

import threading
from pathlib import Path

from msu_anechoic import sound


class FakeBackend:
    def __init__(self, name: str, calls: list[str], *, fail: bool = False) -> None:
        self.name = name
        self.calls = calls
        self.fail = fail
        self.closed = False

    def speak(self, phrase: str) -> None:
        self.calls.append(f"{self.name}:{phrase}")
        if self.fail:
            raise RuntimeError("backend failed")

    def close(self) -> None:
        self.closed = True


def test_fallback_speaker_uses_factories_in_order():
    calls: list[str] = []
    first = FakeBackend("first", calls, fail=True)
    second = FakeBackend("second", calls)
    speaker = sound._FallbackSpeaker((lambda: None, lambda: first, lambda: second))

    speaker.speak("hello")

    assert calls == ["first:hello", "second:hello"]
    assert first.closed
    assert not second.closed


def test_piper_model_path_uses_default_voice_in_configured_directory(monkeypatch, tmp_path: Path):
    model_path = tmp_path / f"{sound.DEFAULT_PIPER_VOICE}.onnx"
    model_path.touch()
    Path(f"{model_path}.json").touch()
    monkeypatch.delenv(sound.PIPER_VOICE_ENV, raising=False)
    monkeypatch.setenv(sound.PIPER_DATA_DIR_ENV, str(tmp_path))

    assert sound._piper_model_path() == model_path


def test_piper_model_path_accepts_explicit_path(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "custom.onnx"
    model_path.touch()
    Path(f"{model_path}.json").touch()
    monkeypatch.setenv(sound.PIPER_VOICE_ENV, str(model_path))

    assert sound._piper_model_path() == model_path


def test_espeak_prefers_espeak_ng(monkeypatch):
    monkeypatch.setattr(
        sound.shutil,
        "which",
        lambda executable: f"/usr/bin/{executable}" if executable in {"espeak-ng", "espeak"} else None,
    )

    backend = sound._try_espeak()

    assert isinstance(backend, sound._EspeakBackend)
    assert backend._executable == "/usr/bin/espeak-ng"


def test_say_uses_lazy_background_worker(monkeypatch):
    spoken = threading.Event()

    class EventBackend(FakeBackend):
        def speak(self, phrase: str) -> None:
            super().speak(phrase)
            spoken.set()

    calls: list[str] = []
    backend = EventBackend("test", calls)
    monkeypatch.setattr(
        sound,
        "_create_fallback_speaker",
        lambda: sound._FallbackSpeaker((lambda: backend,)),
    )

    assert sound._say_thread is None
    sound.say("queued")
    assert spoken.wait(timeout=2)
    worker = sound._say_thread
    assert worker is not None
    sound.kill_speaker()
    worker.join(timeout=2)

    assert calls == ["test:queued"]
    assert backend.closed
    assert not worker.is_alive()
    assert sound._say_thread is None
