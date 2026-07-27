"""Queued text-to-speech with graceful platform fallbacks.

Backends are tried in this order:

1. Windows SAPI through ``comtypes`` (Windows only)
2. Piper using a local voice model
3. ``espeak-ng`` or ``espeak``
4. Silence

Piper never downloads a model implicitly. Set ``MSU_ANECHOIC_PIPER_VOICE`` to
either a voice name or an ONNX model path. When it is unset, the voice name
defaults to ``en_US-lessac-medium``. Set ``MSU_ANECHOIC_PIPER_DATA_DIR`` when
the named model is not in the current working directory.
"""

from __future__ import annotations

import io
import logging
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

DEFAULT_PIPER_VOICE = "en_US-lessac-medium"
PIPER_VOICE_ENV = "MSU_ANECHOIC_PIPER_VOICE"
PIPER_DATA_DIR_ENV = "MSU_ANECHOIC_PIPER_DATA_DIR"

_LOGGER = logging.getLogger(__name__)


class _Backend(Protocol):
    name: str

    def speak(self, phrase: str) -> None: ...

    def close(self) -> None: ...


class _SilentBackend:
    name = "silence"

    def speak(self, phrase: str) -> None:
        pass

    def close(self) -> None:
        pass


class _WindowsComtypesBackend:
    name = "Windows SAPI"

    def __init__(self) -> None:
        import comtypes
        import comtypes.client

        self._comtypes = comtypes
        comtypes.CoInitialize()
        try:
            self._voice = comtypes.client.CreateObject("SAPI.SpVoice")
        except Exception:
            comtypes.CoUninitialize()
            raise

    def speak(self, phrase: str) -> None:
        self._voice.Speak(phrase, 0)

    def close(self) -> None:
        self._voice = None
        self._comtypes.CoUninitialize()


class _PiperBackend:
    name = "Piper"

    def __init__(
        self,
        model_path: Path,
        player_command: Callable[[Path], list[str]] | None,
    ) -> None:
        from piper import PiperVoice

        self._voice = PiperVoice.load(model_path)
        self._player_command = player_command

    def speak(self, phrase: str) -> None:
        if sys.platform == "win32":
            self._speak_windows(phrase)
            return

        assert self._player_command is not None
        wav_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
                wav_path = Path(wav_file.name)

            with wave.open(str(wav_path), "wb") as wav_file:
                self._voice.synthesize_wav(phrase, wav_file)

            subprocess.run(
                self._player_command(wav_path),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        finally:
            if wav_path is not None:
                wav_path.unlink(missing_ok=True)

    def _speak_windows(self, phrase: str) -> None:
        import winsound

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wav_file:
            self._voice.synthesize_wav(phrase, wav_file)
        winsound.PlaySound(wav_buffer.getvalue(), winsound.SND_MEMORY)

    def close(self) -> None:
        self._voice = None


class _EspeakBackend:
    name = "eSpeak"

    def __init__(self, executable: str) -> None:
        self._executable = executable

    def speak(self, phrase: str) -> None:
        subprocess.run(
            [self._executable, phrase],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def close(self) -> None:
        pass


_BackendFactory = Callable[[], _Backend | None]


class _FallbackSpeaker:
    """Select a backend lazily and advance if the active backend fails."""

    def __init__(self, factories: tuple[_BackendFactory, ...]) -> None:
        self._factories = factories
        self._next_factory = 0
        self._backend: _Backend | None = None

    def speak(self, phrase: str) -> None:
        while True:
            if self._backend is None:
                self._backend = self._get_next_backend()

            try:
                self._backend.speak(phrase)
                return
            except Exception:
                _LOGGER.exception(
                    "Sound backend %s failed; trying the next backend",
                    self._backend.name,
                )
                try:
                    self._backend.close()
                except Exception:
                    _LOGGER.exception(
                        "Could not close failed sound backend %s",
                        self._backend.name,
                    )
                self._backend = None

    def close(self) -> None:
        if self._backend is not None:
            self._backend.close()
            self._backend = None

    def _get_next_backend(self) -> _Backend:
        while self._next_factory < len(self._factories):
            factory = self._factories[self._next_factory]
            self._next_factory += 1
            try:
                backend = factory()
            except Exception:
                _LOGGER.exception("Could not initialize a sound backend")
                continue

            if backend is not None:
                _LOGGER.info("Using %s for text-to-speech", backend.name)
                return backend

        # The factory list normally includes this backend, but retain a final
        # guard so a custom/test factory list can never exhaust the loop.
        return _SilentBackend()


def _try_windows_comtypes() -> _Backend | None:
    if sys.platform != "win32":
        return None
    return _WindowsComtypesBackend()


def _piper_model_path() -> Path | None:
    voice = os.environ.get(PIPER_VOICE_ENV, DEFAULT_PIPER_VOICE)
    requested_path = Path(voice).expanduser()

    if requested_path.suffix == ".onnx" or requested_path.parent != Path("."):
        config_path = Path(f"{requested_path}.json")
        return requested_path if requested_path.is_file() and config_path.is_file() else None

    model_name = requested_path.name
    if not model_name.endswith(".onnx"):
        model_name = f"{model_name}.onnx"

    search_dirs: list[Path] = []
    configured_data_dir = os.environ.get(PIPER_DATA_DIR_ENV)
    if configured_data_dir:
        search_dirs.append(Path(configured_data_dir).expanduser())
    search_dirs.extend(
        (
            Path.cwd(),
            Path.home() / ".local" / "share" / "piper-voices",
            Path.home() / ".cache" / "piper-voices",
        )
    )

    for data_dir in search_dirs:
        model_path = data_dir / model_name
        if model_path.is_file() and Path(f"{model_path}.json").is_file():
            return model_path

    return None


def _piper_player_command() -> Callable[[Path], list[str]] | None:
    if sys.platform == "win32":
        return None

    if sys.platform == "darwin":
        afplay = shutil.which("afplay")
        if afplay:
            return lambda wav_path: [afplay, str(wav_path)]

    aplay = shutil.which("aplay")
    if aplay:
        return lambda wav_path: [aplay, "-q", str(wav_path)]

    pw_play = shutil.which("pw-play")
    if pw_play:
        return lambda wav_path: [pw_play, str(wav_path)]

    ffplay = shutil.which("ffplay")
    if ffplay:
        return lambda wav_path: [
            ffplay,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "quiet",
            str(wav_path),
        ]

    return None


def _try_piper() -> _Backend | None:
    model_path = _piper_model_path()
    if model_path is None:
        return None

    player_command = _piper_player_command()
    if sys.platform != "win32" and player_command is None:
        return None

    try:
        import piper  # noqa: F401
    except ImportError:
        return None

    return _PiperBackend(model_path, player_command)


def _try_espeak() -> _Backend | None:
    executable = shutil.which("espeak-ng") or shutil.which("espeak")
    if executable is None:
        return None
    return _EspeakBackend(executable)


def _create_fallback_speaker() -> _FallbackSpeaker:
    return _FallbackSpeaker(
        (
            _try_windows_comtypes,
            _try_piper,
            _try_espeak,
            _SilentBackend,
        )
    )


_state_lock = threading.Lock()
_say_queue: queue.Queue[str | None] | None = None
_say_thread: threading.Thread | None = None


def _speaker_worker(messages: queue.Queue[str | None]) -> None:
    global _say_queue
    global _say_thread

    speaker = _create_fallback_speaker()
    try:
        while True:
            phrase = messages.get()
            if phrase is None:
                break
            speaker.speak(phrase)
    finally:
        speaker.close()
        with _state_lock:
            if _say_queue is messages:
                _say_queue = None
                _say_thread = None


def say(phrase: str) -> None:
    """Queue a phrase for text-to-speech without blocking the caller."""

    global _say_queue
    global _say_thread

    with _state_lock:
        if _say_thread is None:
            _say_queue = queue.Queue()
            _say_thread = threading.Thread(
                target=_speaker_worker,
                args=(_say_queue,),
                name="anechoic-speaker",
                daemon=True,
            )
            _say_thread.start()

        assert _say_queue is not None
        _say_queue.put(phrase)


def kill_speaker() -> None:
    """Ask the text-to-speech worker to finish queued work and stop."""

    with _state_lock:
        if _say_queue is not None:
            _say_queue.put(None)


if __name__ == "__main__":
    import time

    say("Hello, this is a test of the speaker system.")
    say("This is another message.")

    time.sleep(5)
    say("Shutting down now")
    kill_speaker()
    if _say_thread is not None:
        _say_thread.join()
