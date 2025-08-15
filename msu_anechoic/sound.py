import multiprocessing
import queue
import threading
import pyttsx3
# import keyboard


def sayFunc(phrase):
    # print(f"SAYING {phrase}")
    engine = pyttsx3.init()
    engine.setProperty("rate", 200)
    engine.setProperty("volume", 100)
    engine.say(phrase)
    engine.runAndWait()


class SayThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self._queue = queue.Queue()
        self._kill_event = threading.Event()

    def run(self):
        while not self._kill_event.is_set():
            try:
                phrase = self._queue.get(timeout=0.1)
                p = multiprocessing.Process(target=sayFunc, args=(phrase,))
                print(f"Starting process for: {phrase} {p}")
                p.start()
                p.join()
            except queue.Empty:
                time.sleep(0.01)


_say_thread = SayThread()
_say_thread.start()


def say(phrase):
    """Say the given phrase aloud."""
    _say_thread._queue.put(phrase)


if __name__ == "__main__":
    import time

    print("YO")
    # say("One")
    # time.sleep(.1)
    # say("Two")
    for index in range(10):
        say(f"{index}")
    time.sleep(10)
