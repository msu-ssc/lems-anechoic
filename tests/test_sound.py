import sys

import pytest

from msu_anechoic import sound


@pytest.mark.skipif(sys.platform == "win32", reason="Exercises the non-Windows fallback")
def test_sound_functions_are_noops_without_windows_text_to_speech():
    assert sound.say("This should not be spoken") is None
    assert sound.kill_speaker() is None
    assert not hasattr(sound, "_say_thread")
