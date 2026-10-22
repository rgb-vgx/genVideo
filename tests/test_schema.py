from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from genvideo.errors import ValidationError
from genvideo.schema import load_episode, parse_episode

from .helpers import EXAMPLE, ROOT, clone, example_data


class SchemaTests(unittest.TestCase):
    def test_example_lesson_is_valid(self) -> None:
        episode = load_episode(EXAMPLE)
        self.assertEqual(episode.title, "English Basics")
        self.assertEqual(episode.source_language, "en")
        self.assertEqual(episode.languages, ["en", "vi"])
        self.assertEqual(len(episode.characters), 2)
        self.assertEqual(len(episode.scenes), 4)
        self.assertEqual(
            [scene.board.type for scene in episode.scenes],
            ["title", "cards", "dialog", "repeat"],
        )
        self.assertEqual(sum(len(scene.lines) for scene in episode.scenes), 10)
        self.assertEqual(episode.teacher.id, "teacher")

    def test_unknown_character_is_rejected(self) -> None:
        data = clone(example_data())
        data["scenes"][0]["lines"][0]["character"] = "ghost"
        with self.assertRaises(ValidationError) as caught:
            parse_episode(data)
        self.assertIn("unknown character 'ghost'", str(caught.exception))

    def test_bad_board_type_is_rejected(self) -> None:
        data = clone(example_data())
        data["scenes"][0]["board"]["type"] = "video"
        with self.assertRaises(ValidationError) as caught:
            parse_episode(data)
        self.assertIn("scenes[0].board.type", str(caught.exception))
        self.assertIn("must be one of", str(caught.exception))

    def test_missing_source_text_is_rejected(self) -> None:
        data = clone(example_data())
        del data["scenes"][0]["lines"][0]["texts"]["en"]
        with self.assertRaises(ValidationError) as caught:
            parse_episode(data)
        self.assertIn("missing source_language 'en' text", str(caught.exception))

    def test_duplicate_line_ids_are_rejected(self) -> None:
        data = clone(example_data())
        data["scenes"][1]["lines"][0]["id"] = data["scenes"][0]["lines"][0]["id"]
        with self.assertRaises(ValidationError) as caught:
            parse_episode(data)
        self.assertIn("duplicate line id", str(caught.exception))

    def test_backend_language_mismatch_is_rejected(self) -> None:
        data = clone(example_data())
        data["characters"][0]["voices"]["vi"] = {
            "backend": "qwen",
            "voice_id": "Serena",
        }
        with self.assertRaises(ValidationError) as caught:
            parse_episode(data)
        self.assertIn("not 'vi'", str(caught.exception))

    def test_qwen_clone_requires_reference_audio(self) -> None:
        data = clone(example_data())
        data["characters"][0]["voices"]["en"] = {
            "backend": "qwen_clone",
            "ref_text": "Reference line.",
        }
        with self.assertRaises(ValidationError) as caught:
            parse_episode(data)
        self.assertIn("ref_audio", str(caught.exception))

    def test_invalid_json_reports_line_and_column(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken.json"
            path.write_text('{"title": "x", }', encoding="utf-8")
            with self.assertRaises(ValidationError) as caught:
                load_episode(path)
        message = str(caught.exception)
        self.assertIn("invalid JSON", message)
        self.assertIn("line 1", message)

    def test_cms_voice_list_and_character_id_are_accepted(self) -> None:
        data = clone(example_data())
        for character in data["characters"]:
            character["voices"] = [
                {"language": language, **profile}
                for language, profile in character["voices"].items()
            ]
        for scene in data["scenes"]:
            for line in scene["lines"]:
                line["character_id"] = line.pop("character")
        episode = parse_episode(data)
        self.assertEqual(episode.characters[0].voices["en"].backend, "qwen")

    def test_language_fallback_uses_source_text_and_voice(self) -> None:
        data = clone(example_data())
        line_data = data["scenes"][0]["lines"][0]
        del line_data["texts"]["vi"]
        episode = parse_episode(data)
        line = episode.scenes[0].lines[0]
        resolved = episode.resolve_line(line, "vi")
        self.assertEqual(resolved.primary, line_data["texts"]["en"])
        self.assertEqual(resolved.spoken_language, "en")
        self.assertEqual(resolved.voice.backend, "qwen")

    def test_unknown_language_is_rejected(self) -> None:
        data = clone(example_data())
        data["languages"] = ["en", "vi", "fr"]
        data["characters"][0]["voices"]["fr"] = {
            "backend": "qwen",
            "voice_id": "Ryan",
        }
        with self.assertRaises(ValidationError) as caught:
            parse_episode(data)
        self.assertIn("not 'fr'", str(caught.exception))

    def test_scene_needs_lines(self) -> None:
        data = clone(example_data())
        data["scenes"][0]["lines"] = []
        with self.assertRaises(ValidationError) as caught:
            parse_episode(data)
        self.assertIn("every scene needs narration", str(caught.exception))

    def test_json_round_trip_not_required(self) -> None:
        # A plain string board title means source-language text.
        data = clone(example_data())
        data["scenes"][0]["board"]["title"] = "Greetings"
        episode = parse_episode(data)
        self.assertEqual(episode.scenes[0].board.title["en"], "Greetings")

    def test_japanese_and_korean_lessons_are_valid(self) -> None:
        for filename, language in [
            ("lesson_ja.json", "ja"),
            ("lesson_ko.json", "ko"),
        ]:
            with self.subTest(filename=filename):
                episode = load_episode(ROOT / "examples" / filename)
                self.assertEqual(episode.source_language, "vi")
                self.assertIn(language, episode.languages)
                self.assertEqual(len(episode.scenes), 4)
                self.assertEqual(len(episode.scenes[0].title), 2)
                self.assertIn(language, episode.scenes[0].title)
                self.assertEqual(
                    episode.scenes[0].title[language],
                    "はじめに" if language == "ja" else "시작",
                )
                # Vietnamese explanation lines fall back to the source voice.
                self.assertEqual(
                    sum(
                        1
                        for scene in episode.scenes
                        for line in scene.lines
                        if language not in line.texts
                    ),
                    5,
                )


if __name__ == "__main__":
    unittest.main()
