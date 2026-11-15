"""Join MP3 parts into one file with ffmpeg and tag it with ID3 metadata."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def concat_mp3(parts: list[bytes], output: Path, metadata: dict[str, str] | None = None) -> Path:
    if not parts:
        raise ValueError("no audio parts to join")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise FFmpegError("ffmpeg not found on PATH")

    workdir = output.parent / f".{output.stem}.parts"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        list_file = workdir / "list.txt"
        lines = []
        for i, data in enumerate(parts):
            part = workdir / f"{i:04d}.mp3"
            part.write_bytes(data)
            lines.append(f"file '{part.name}'")
        list_file.write_text("\n".join(lines) + "\n")

        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy"]
        for key, value in (metadata or {}).items():
            cmd += ["-metadata", f"{key}={value}"]
        cmd += ["-id3v2_version", "3", str(output)]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise FFmpegError(proc.stderr.strip() or f"ffmpeg exited with {proc.returncode}")
        return output
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
