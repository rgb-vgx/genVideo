"""Command-line interface: validate, render, preview."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import GenVideoError, ValidationError
from .pipeline import prepare_episode
from .render import DEFAULT_FPS, Renderer
from .schema import Episode, load_episode

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = ROOT / "build" / "cache" / "tts"


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


@contextmanager
def _work_directory(
    episode_path: Path, language: str, work_dir: str | None, keep_work: bool
) -> Iterator[Path]:
    """Yield a work directory and keep it when requested."""
    if work_dir:
        path = Path(work_dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        yield path
        return

    stem = episode_path.stem or "episode"
    if keep_work:
        path = ROOT / "build" / "work" / f"{stem}_{language}"
        path.mkdir(parents=True, exist_ok=True)
        yield path
        return

    temp_root = ROOT / "build" / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"{stem}_{language}_", dir=temp_root
    ) as temp:
        yield Path(temp)


def _parse_times(value: str) -> list[float]:
    times: list[float] = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            times.append(float(chunk))
        except ValueError as exc:
            raise GenVideoError(
                f"invalid --at value '{chunk}'; use comma-separated seconds, "
                "e.g. --at 3,30"
            ) from exc
    if not times:
        raise GenVideoError("--at must contain at least one time in seconds")
    return times


def _check_reference_files(episode: Episode) -> list[str]:
    errors: list[str] = []
    for character in episode.characters:
        for language, voice in character.voices.items():
            if voice.backend == "qwen_clone" and voice.ref_audio:
                if not Path(voice.ref_audio).exists():
                    errors.append(
                        f"character '{character.id}' voice '{language}': "
                        f"reference audio not found: {voice.ref_audio}"
                    )
    return errors


def cmd_validate(args: argparse.Namespace) -> int:
    episode = load_episode(args.episode)
    extra_errors: list[str] = []
    if args.check_files:
        extra_errors.extend(_check_reference_files(episode))
    if extra_errors:
        raise ValidationError(extra_errors, str(Path(args.episode)))

    line_count = sum(len(scene.lines) for scene in episode.scenes)
    print(f"OK {args.episode}")
    print(f"title: {episode.title}")
    print(f"template: {episode.template}")
    print(f"languages: {', '.join(episode.languages)} (source: {episode.source_language})")
    print(f"characters: {len(episode.characters)}")
    print(f"scenes: {len(episode.scenes)}, lines: {line_count}")
    print(
        "boards: "
        + ", ".join(
            f"{scene.id}:{scene.board.type}({len(scene.lines)} line(s))"
            for scene in episode.scenes
        )
    )

    if args.language:
        language = args.language.strip().lower()
        if language not in episode.languages:
            raise GenVideoError(
                f"language '{language}' is not in episode.languages "
                f"({', '.join(episode.languages)})"
            )
        fallback = 0
        for scene in episode.scenes:
            for line in scene.lines:
                episode.resolve_line(line, language)
                if language not in line.texts:
                    fallback += 1
        print(f"language '{language}': OK ({fallback} line(s) fall back to source text)")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    started = time.monotonic()
    episode = load_episode(args.episode)
    language = args.language.strip().lower()
    if language not in episode.languages:
        raise GenVideoError(
            f"language '{language}' is not in episode.languages "
            f"({', '.join(episode.languages)})"
        )
    if args.fps <= 0:
        raise GenVideoError("--fps must be positive")

    cache_dir = Path(args.cache_dir).expanduser().resolve() if args.cache_dir else DEFAULT_CACHE
    episode_path = Path(args.episode)
    with _work_directory(episode_path, language, args.work_dir, args.keep_work) as work_dir:
        prepared = prepare_episode(
            episode,
            language,
            root=ROOT,
            cache_dir=cache_dir,
            work_dir=work_dir,
            force=args.force,
            mock=os.environ.get("GENVIDEO_TTS_MOCK") == "1",
            fps=args.fps,
            log=_log,
        )
        renderer = Renderer(episode, prepared.timeline, prepared.tracks, language)
        last_percent = -1

        def progress(done: int, total: int) -> None:
            nonlocal last_percent
            percent = int(done * 100 / max(total, 1))
            if percent >= last_percent + 5 or done == total:
                last_percent = percent
                _log(f"[render] {done}/{total} frame(s) ({percent}%)")

        output = Path(args.out)
        renderer.render_video(
            output,
            prepared.mix_path,
            crf=args.crf,
            preset=args.preset,
            progress=progress,
        )

    total = time.monotonic() - started
    report = prepared.tts_report
    print(f"output: {output}")
    print(f"duration: {prepared.timeline.total:.1f}s")
    print(f"frames: {prepared.timeline.nframes} @ {prepared.timeline.fps} fps")
    print(
        f"tts: {report.elapsed:.1f}s "
        f"({report.line_count} line(s), {report.unique_clips} clip(s), "
        f"{report.cached} cached, {report.synthesized} synthesized)"
    )
    print(f"total: {total:.1f}s")
    print(f"cache: {cache_dir}")
    if args.work_dir or args.keep_work:
        print(f"work: {work_dir}")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    started = time.monotonic()
    episode = load_episode(args.episode)
    language = args.language.strip().lower()
    if language not in episode.languages:
        raise GenVideoError(
            f"language '{language}' is not in episode.languages "
            f"({', '.join(episode.languages)})"
        )
    if args.fps <= 0:
        raise GenVideoError("--fps must be positive")
    times = _parse_times(args.at)

    cache_dir = Path(args.cache_dir).expanduser().resolve() if args.cache_dir else DEFAULT_CACHE
    episode_path = Path(args.episode)
    with _work_directory(episode_path, language, args.work_dir, args.keep_work) as work_dir:
        prepared = prepare_episode(
            episode,
            language,
            root=ROOT,
            cache_dir=cache_dir,
            work_dir=work_dir,
            force=args.force,
            mock=os.environ.get("GENVIDEO_TTS_MOCK") == "1",
            fps=args.fps,
            log=_log,
        )
        renderer = Renderer(episode, prepared.timeline, prepared.tracks, language)
        paths = renderer.preview(times, args.out_dir)

    for path in paths:
        print(path)
    print(f"preview: {len(paths)} frame(s) in {time.monotonic() - started:.1f}s")
    if args.work_dir or args.keep_work:
        print(f"work: {work_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="genvideo",
        description=(
            "Render a JSON-defined lesson video: TTS (cached) -> timeline -> "
            "PIL frames -> H.264/AAC MP4."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser(
        "validate", help="validate an episode JSON file without rendering"
    )
    validate.add_argument("episode", help="path to episode JSON")
    validate.add_argument(
        "--language",
        help="also resolve every line for this language (checks voice coverage)",
    )
    validate.add_argument(
        "--check-files",
        action="store_true",
        help="check qwen_clone reference audio files exist",
    )
    validate.set_defaults(func=cmd_validate)

    render = sub.add_parser("render", help="render an episode to MP4")
    render.add_argument("episode", help="path to episode JSON")
    render.add_argument("--language", required=True, help="target language code, e.g. en")
    render.add_argument("--out", required=True, help="output MP4 path")
    render.add_argument(
        "--work-dir",
        help="keep temporary TTS/mix files in this directory",
    )
    render.add_argument(
        "--keep-work",
        action="store_true",
        help="keep temporary files in build/work/<episode>_<language>",
    )
    render.add_argument(
        "--force",
        action="store_true",
        help="ignore existing TTS cache and synthesize every clip again",
    )
    render.add_argument(
        "--cache-dir",
        help=f"TTS cache directory (default: {DEFAULT_CACHE})",
    )
    render.add_argument(
        "--fps", type=int, default=DEFAULT_FPS, help=f"frame rate (default: {DEFAULT_FPS})"
    )
    render.add_argument("--crf", type=int, default=20, help="libx264 CRF (default: 20)")
    render.add_argument(
        "--preset", default="medium", help="libx264 preset (default: medium)"
    )
    render.set_defaults(func=cmd_render)

    preview = sub.add_parser(
        "preview", help="render PNG frames at selected timestamps"
    )
    preview.add_argument("episode", help="path to episode JSON")
    preview.add_argument("--language", required=True, help="target language code, e.g. en")
    preview.add_argument(
        "--at",
        default="3",
        help="comma-separated timestamps in seconds (default: 3)",
    )
    preview.add_argument(
        "--out-dir", default=str(ROOT / "build" / "preview"), help="PNG output directory"
    )
    preview.add_argument("--work-dir", help="keep temporary TTS/mix files here")
    preview.add_argument(
        "--keep-work",
        action="store_true",
        help="keep temporary files in build/work/<episode>_<language>",
    )
    preview.add_argument(
        "--force", action="store_true", help="ignore existing TTS cache"
    )
    preview.add_argument(
        "--cache-dir",
        help=f"TTS cache directory (default: {DEFAULT_CACHE})",
    )
    preview.add_argument(
        "--fps", type=int, default=DEFAULT_FPS, help=f"frame rate (default: {DEFAULT_FPS})"
    )
    preview.set_defaults(func=cmd_preview)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except GenVideoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return 130
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
