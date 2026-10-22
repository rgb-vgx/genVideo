from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from genvideo.schema import parse_episode
from genvideo.tts import TTSRequest, build_requests, cache_key, synthesize

from .helpers import clone, example_data, tiny_data


class CacheKeyTests(unittest.TestCase):
    def test_cache_key_is_stable(self) -> None:
        first = cache_key("Hello!", "en", "qwen", "Serena")
        second = cache_key("Hello!", "en", "qwen", "Serena")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_cache_key_changes_with_each_field(self) -> None:
        base = cache_key("Hello!", "en", "qwen", "Serena")
        variants = [
            cache_key("Hello?", "en", "qwen", "Serena"),
            cache_key("Hello!", "vi", "qwen", "Serena"),
            cache_key("Hello!", "en", "qwen_clone", "Serena"),
            cache_key("Hello!", "en", "qwen", "Aiden"),
            cache_key("Hello!", "en", "qwen_clone", "", ref_audio="/a.wav"),
            cache_key("Hello!", "en", "qwen", "Serena", instruct="slow"),
        ]
        for variant in variants:
            self.assertNotEqual(base, variant)

    def test_ref_audio_and_text_affect_key(self) -> None:
        first = cache_key(
            "Hi", "en", "qwen_clone", "", ref_audio="/a.wav", ref_text="a"
        )
        second = cache_key(
            "Hi", "en", "qwen_clone", "", ref_audio="/a.wav", ref_text="b"
        )
        self.assertNotEqual(first, second)


class RequestTests(unittest.TestCase):
    def test_build_requests_for_both_languages(self) -> None:
        episode = parse_episode(example_data())
        english = build_requests(episode, "en")
        vietnamese = build_requests(episode, "vi")
        self.assertEqual(len(english), 10)
        self.assertEqual(len(vietnamese), 10)
        self.assertNotEqual(
            {request.key for request in english},
            {request.key for request in vietnamese},
        )
        self.assertEqual(english[0].backend, "qwen")
        self.assertEqual(vietnamese[0].backend, "vieneu")

    def test_group_order_puts_qwen_before_vieneu(self) -> None:
        from genvideo.tts import _group_requests

        requests = [
            TTSRequest("a", "xin chào", "vi", "vieneu", "Mai Anh", "", "", "", "k1"),
            TTSRequest("b", "hello", "en", "qwen", "Serena", "", "", "", "k2"),
            TTSRequest("c", "hello", "en", "qwen", "Aiden", "", "", "", "k3"),
        ]
        groups = _group_requests(requests)
        self.assertEqual(groups[-1][0][0], "vieneu")
        self.assertEqual([group[0][0] for group in groups[:2]], ["qwen", "qwen"])


class MockSynthesisTests(unittest.TestCase):
    def test_mock_synthesis_populates_and_reuses_cache(self) -> None:
        episode = parse_episode(example_data())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "cache"
            work = root / "work"
            first = synthesize(
                episode,
                "en",
                root=root,
                cache_dir=cache,
                work_dir=work,
                mock=True,
            )
            self.assertEqual(first.line_count, 10)
            self.assertEqual(first.unique_clips, 10)
            self.assertEqual(first.cached, 0)
            self.assertEqual(first.synthesized, 10)
            self.assertEqual(len(first.clips), 10)
            for clip in first.clips.values():
                self.assertTrue(clip.exists())
                with wave.open(str(clip), "rb") as wav:
                    self.assertGreater(wav.getnframes(), 0)
                self.assertEqual(clip.parent, cache / "mock")

            second = synthesize(
                episode,
                "en",
                root=root,
                cache_dir=cache,
                work_dir=work,
                mock=True,
            )
            self.assertEqual(second.cached, 10)
            self.assertEqual(second.synthesized, 0)

            forced = synthesize(
                episode,
                "en",
                root=root,
                cache_dir=cache,
                work_dir=work,
                mock=True,
                force=True,
            )
            self.assertEqual(forced.cached, 0)
            self.assertEqual(forced.synthesized, 10)

    def test_identical_lines_share_one_clip(self) -> None:
        data = clone(tiny_data())
        data["scenes"][1]["lines"][0]["texts"] = dict(
            data["scenes"][0]["lines"][0]["texts"]
        )
        data["scenes"][1]["lines"][0]["character"] = "teacher"
        episode = parse_episode(data)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = synthesize(
                episode,
                "en",
                root=root,
                cache_dir=root / "cache",
                work_dir=root / "work",
                mock=True,
            )
        self.assertEqual(report.line_count, 3)
        self.assertEqual(report.unique_clips, 2)
        clips = [request.line_id for request in build_requests(episode, "en")]
        self.assertEqual(len(clips), 3)
        self.assertEqual(
            report.clips["l1"],
            report.clips["l2"],
        )


if __name__ == "__main__":
    unittest.main()
