from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from genvideo.audio import SR, load_clip, trim_silence, write_wav
from genvideo.errors import AudioError


class AudioTests(unittest.TestCase):
    def test_load_clip_trims_leading_and_trailing_silence(self) -> None:
        duration = 1.2
        t = np.arange(int(duration * SR), dtype=np.float32) / SR
        data = np.zeros_like(t)
        start = int(0.3 * SR)
        end = int(0.9 * SR)
        data[start:end] = 0.4 * np.sin(2 * np.pi * 440 * t[start:end])
        with tempfile.TemporaryDirectory() as temp:
            path = write_wav(Path(temp) / "clip.wav", data)
            loaded = load_clip(path)
        self.assertGreater(len(loaded), int(0.55 * SR))
        self.assertLess(len(loaded), int(0.75 * SR))
        self.assertGreater(float(np.max(np.abs(loaded))), 0.2)

    def test_silent_clip_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_wav(Path(temp) / "silent.wav", np.zeros(SR, dtype=np.float32))
            with self.assertRaises(AudioError):
                load_clip(path)

    def test_trim_silence_preserves_audio(self) -> None:
        data = np.concatenate(
            [
                np.zeros(int(0.2 * SR), dtype=np.float32),
                np.full(int(0.4 * SR), 0.2, dtype=np.float32),
                np.zeros(int(0.2 * SR), dtype=np.float32),
            ]
        )
        trimmed = trim_silence(data)
        self.assertGreater(len(trimmed), int(0.35 * SR))
        self.assertLess(len(trimmed), int(0.5 * SR))

    def test_missing_file_is_rejected(self) -> None:
        with self.assertRaises(AudioError):
            load_clip("/tmp/definitely-not-a-genvideo-clip.wav")


if __name__ == "__main__":
    unittest.main()
