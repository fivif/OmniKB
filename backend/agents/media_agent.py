"""MediaAgent — transcribe video/audio files to text via faster-whisper.

Supported inputs
----------------
Video : .mp4, .mkv, .avi, .mov, .webm, .ts, .m4v  (requires ffmpeg in PATH)
Audio : .mp3, .wav, .m4a, .ogg, .flac, .aac, .opus  (direct)

Dependencies
------------
  pip install faster-whisper
  # Video: ffmpeg must be installed and on PATH
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from agents.doc_agent import RawDocument

AUDIO_EXTENSIONS = frozenset({
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus",
})
VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".m4v",
})
SUPPORTED_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


def is_media_file(ext: str) -> bool:
    """Return True when *ext* (including the dot, e.g. '.mp3') is a media format."""
    return ext.lower() in SUPPORTED_EXTENSIONS


def _extract_audio(video_path: str) -> str:
    """Extract audio track from *video_path* to a temp 16 kHz mono WAV.
    Returns the temp file path; caller must delete it.
    Raises RuntimeError if ffmpeg fails.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn",                  # no video
        "-acodec", "pcm_s16le", # raw PCM 16-bit
        "-ar", "16000",         # 16 kHz — matches Whisper's native rate
        "-ac", "1",             # mono
        tmp.name,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    if result.returncode != 0:
        os.unlink(tmp.name)
        stderr = result.stderr.decode("utf-8", errors="replace")[:600]
        raise RuntimeError(f"ffmpeg failed (code {result.returncode}): {stderr}")
    return tmp.name


def transcribe(file_path: str | Path, model_size: str = "base") -> RawDocument:
    """Transcribe an audio or video file and return a :class:`RawDocument`.

    Parameters
    ----------
    file_path:
        Path to the media file.
    model_size:
        faster-whisper model size: ``tiny``, ``base``, ``small``,
        ``medium``, ``large-v2``, etc.

    Returns
    -------
    RawDocument
        *content* — full transcript text.
        *metadata* — includes ``file_type``, ``original_file``,
        ``media_type``, ``language``, ``duration_seconds``.
    """
    from faster_whisper import WhisperModel  # lazy import — only required when used

    path = Path(file_path)
    ext = path.suffix.lower()
    audio_path = str(path)
    tmp_audio: str | None = None

    try:
        if ext in VIDEO_EXTENSIONS:
            tmp_audio = _extract_audio(str(path))
            audio_path = tmp_audio

        # Load model with int8 quantisation for CPU efficiency
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, info = model.transcribe(
            audio_path,
            language=None,   # auto-detect
            beam_size=5,
        )

        lines = [seg.text.strip() for seg in segments if seg.text.strip()]
        transcript = "\n".join(lines)

        return RawDocument(
            content=transcript,
            metadata={
                "file_type": "transcript",
                "original_file": path.name,
                "media_type": "video" if ext in VIDEO_EXTENSIONS else "audio",
                "language": getattr(info, "language", "unknown"),
                "duration_seconds": round(getattr(info, "duration", 0.0), 1),
            },
        )
    finally:
        if tmp_audio and os.path.exists(tmp_audio):
            os.unlink(tmp_audio)
