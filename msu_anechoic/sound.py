from __future__ import annotations

import threading
import queue
import time

import comtypes
import comtypes.client as cc

def speaker_worker(q: queue.Queue):
    comtypes.CoInitialize()
    try:
        voice = cc.CreateObject("SAPI.SpVoice")
        while True:
            text = q.get()
            if text is None:
                break
            voice.Speak(text, 0)
    finally:
        comtypes.CoUninitialize()

_say_queue = queue.Queue()
_say_thread = threading.Thread(target=speaker_worker, args=(_say_queue,), daemon=True)
_say_thread.start()

def say(phrase: str) -> None:
    _say_queue.put(phrase)

def kill_speaker() -> None:
    _say_queue.put(None)

if __name__ == "__main__":
    say("Hello, this is a test of the speaker system.")
    say("This is another message.")

    time.sleep(5)
    say("Shutting down now")
    kill_speaker()
    _say_thread.join()