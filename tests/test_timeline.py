from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from genvideo.audio import SR, mix_timeline, write_wav
from genvideo.errors import AudioError
from genvideo.schema import parse_episode
from genvideo.timeline import LEAD_IN, build_timeline

from .helpers import example_data


def build(language: str = "en", duration: float = 1.0, fps: int = 24):
    episode = parse_episode(example_data())
    clips = {
        line.id: np.full(int(duration * SR), 0.1, dtype=np.float32)
        for scene in episode.scenes
        for line in scene.lines
    }
    return episode, build_timeline(episode, language, clips, fps=fps)


class TimelineTests(unittest.TestCase):
    def test_lead_in_and_scene_transition(self) -> None:
        _, timeline = build()
        first = timeline.scenes[0].lines[0]
        self.assertAlmostEqual(first.show, 0.0, places=6)
        self.assertAlmostEqual(first.start, LEAD_IN, places=6)

        first_scene, second_scene = timeline.scenes[0], timeline.scenes[1]
        self.assertAlmostEqual(second_scene.show, first_scene.end + 0.6, places=6)
        second_first = second_scene.lines[0]
        self.assertAlmostEqual(second_first.show, second_scene.show, places=6)
        self.assertAlmostEqual(second_first.start, second_scene.show + 0.6, places=6)
        self.assertEqual(len(timeline.chimes), 4)
        self.assertAlmostEqual(timeline.chimes[1], second_scene.show, places=6)

    def test_audio_duration_drives_timeline(self) -> None:
        _, timeline = build(duration=1.25)
        for cue in timeline.lines:
            self.assertAlmostEqual(cue.duration, 1.25, places=4)
            self.assertAlmostEqual(cue.end - cue.start, 1.25, places=4)

        last = timeline.lines[-1]
        self.assertAlmostEqual(timeline.total, last.end + last.pause + 0.8, places=6)
        self.assertEqual(timeline.nframes, int(round(timeline.total * timeline.fps)))

    def test_item_reveal_order(self) -> None:
        _, timeline = build()
        cards = timeline.scenes[1]
        show_card_0 = timeline.item_show[(cards.scene.id, 0)]
        show_card_1 = timeline.item_show[(cards.scene.id, 1)]
        self.assertLessEqual(show_card_0, show_card_1)
        self.assertAlmostEqual(show_card_0, cards.lines[0].show, places=6)
        self.assertAlmostEqual(show_card_1, cards.lines[1].show, places=6)

    def test_mix_has_audio_and_expected_length(self) -> None:
        _, timeline = build()
        mix, tracks = mix_timeline(timeline)
        self.assertEqual(len(mix), int(round(timeline.total * SR)) + SR)
        self.assertGreater(float(np.max(np.abs(mix))), 0.01)
        self.assertEqual(set(tracks), {"teacher", "nam"})
        self.assertGreater(float(np.max(np.abs(tracks["teacher"]))), 0.01)

        with tempfile.TemporaryDirectory() as temp:
            path = write_wav(Path(temp) / "mix.wav", mix)
            with wave.open(str(path), "rb") as wav:
                self.assertEqual(wav.getframerate(), SR)
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getnframes(), len(mix))

    def test_silent_mix_is_rejected(self) -> None:
        episode = parse_episode(example_data())
        clips = {
            line.id: np.zeros(int(0.5 * SR), dtype=np.float32)
            for scene in episode.scenes
            for line in scene.lines
        }
        timeline = build_timeline(episode, "en", clips)
        with self.assertRaises(AudioError):
            mix_timeline(timeline)

    def test_vietnamese_fallback_text_and_voice(self) -> None:
        data = example_data()
        del data["scenes"][0]["lines"][0]["texts"]["vi"]
        episode = parse_episode(data)
        clips = {
            line.id: np.full(int(0.5 * SR), 0.1, dtype=np.float32)
            for scene in episode.scenes
            for line in scene.lines
        }
        timeline = build_timeline(episode, "vi", clips)
        cue = timeline.scenes[0].lines[0]
        self.assertEqual(cue.primary, "Hello everyone! Welcome to English Basics.")
        self.assertEqual(cue.resolved.spoken_language, "en")
        self.assertEqual(cue.resolved.voice.backend, "qwen")


if __name__ == "__main__":
    unittest.main()
