from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from .helpers import ROOT, EXAMPLE


def run_cli(*args: str, env_extra: dict | None = None, timeout: int = 180):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "genvideo", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class CLITests(unittest.TestCase):
    def test_help(self) -> None:
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("render", result.stdout)
        self.assertIn("validate", result.stdout)
        self.assertIn("preview", result.stdout)

    def test_validate_example(self) -> None:
        result = run_cli("validate", str(EXAMPLE))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)
        self.assertIn("dialog", result.stdout)

    def test_validate_language(self) -> None:
        result = run_cli("validate", str(EXAMPLE), "--language", "vi")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("language 'vi': OK", result.stdout)

    def test_validate_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken.json"
            path.write_text('{"title": ', encoding="utf-8")
            result = run_cli("validate", str(path))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid JSON", result.stderr)

    def test_bad_language_exits_nonzero(self) -> None:
        result = run_cli(
            "render",
            str(EXAMPLE),
            "--language",
            "fr",
            "--out",
            "/tmp/never-created.mp4",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not in episode.languages", result.stderr)

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"),
        "ffmpeg/ffprobe are required",
    )
    def test_render_and_preview_with_mock_tts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "out.mp4"
            cache = root / "cache"
            work = root / "work"
            preview = root / "preview"
            env = {"GENVIDEO_TTS_MOCK": "1"}

            first = run_cli(
                "render",
                str(EXAMPLE),
                "--language",
                "en",
                "--out",
                str(output),
                "--fps",
                "6",
                "--cache-dir",
                str(cache),
                "--work-dir",
                str(work),
                env_extra=env,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("output:", first.stdout)
            self.assertNotIn("espeak", (first.stdout + first.stderr).lower())
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 10_000)

            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            metadata = json.loads(probe.stdout)
            video = [s for s in metadata["streams"] if s["codec_type"] == "video"]
            audio = [s for s in metadata["streams"] if s["codec_type"] == "audio"]
            self.assertEqual(len(video), 1)
            self.assertEqual(len(audio), 1)
            self.assertEqual(video[0]["codec_name"], "h264")
            self.assertEqual(video[0]["width"], 1280)
            self.assertEqual(video[0]["height"], 720)
            self.assertEqual(audio[0]["codec_name"], "aac")
            self.assertGreater(float(metadata["format"]["duration"]), 0.0)

            volume = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-i",
                    str(output),
                    "-af",
                    "volumedetect",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
            )
            match = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", volume.stderr)
            self.assertIsNotNone(match, volume.stderr[-1000:])
            self.assertGreater(float(match.group(1)), -60.0)

            second = run_cli(
                "render",
                str(EXAMPLE),
                "--language",
                "en",
                "--out",
                str(output),
                "--fps",
                "6",
                "--cache-dir",
                str(cache),
                "--work-dir",
                str(work),
                env_extra=env,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("0 to synthesize", second.stderr)
            self.assertIn("10 cached", second.stderr)

            preview_result = run_cli(
                "preview",
                str(EXAMPLE),
                "--language",
                "en",
                "--at",
                "3,15",
                "--fps",
                "6",
                "--out-dir",
                str(preview),
                "--cache-dir",
                str(cache),
                "--work-dir",
                str(work),
                env_extra=env,
            )
            self.assertEqual(preview_result.returncode, 0, preview_result.stderr)
            pngs = sorted(preview.glob("*.png"))
            self.assertEqual(len(pngs), 2)
            for png in pngs:
                with Image.open(png) as image:
                    self.assertEqual(image.size, (1280, 720))


if __name__ == "__main__":
    unittest.main()
