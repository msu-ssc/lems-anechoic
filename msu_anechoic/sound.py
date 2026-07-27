"""Optional Windows text-to-speech support."""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import queue
    import threading

    import comtypes
    import comtypes.client as cc

    _say_queue: queue.Queue[str | None] = queue.Queue()

    def speaker_worker(messages: queue.Queue[str | None]) -> None:
        comtypes.CoInitialize()
        try:
            voice = cc.CreateObject("SAPI.SpVoice")
            while True:
                text = messages.get()
                if text is None:
                    break
                voice.Speak(text, 0)
        finally:
            comtypes.CoUninitialize()

    _say_thread = threading.Thread(
        target=speaker_worker,
        args=(_say_queue,),
        name="anechoic-speaker",
        daemon=True,
    )
    _say_thread.start()

    def say(phrase: str) -> None:
        """Queue a phrase for Windows text-to-speech."""

        _say_queue.put(phrase)

    def kill_speaker() -> None:
        """Ask the Windows text-to-speech worker to stop."""

        _say_queue.put(None)

else:

    def say(phrase: str) -> None:
        """Do nothing when Windows text-to-speech is unavailable."""

    def kill_speaker() -> None:
        """Do nothing when Windows text-to-speech is unavailable."""


if __name__ == "__main__":
    import time

    say("Hello, this is a test of the speaker system.")
    say("This is another message.")

    time.sleep(5)
    say("Shutting down now")
    kill_speaker()
    if sys.platform == "win32":
        _say_thread.join()
