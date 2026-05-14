"""MediaAgent — transcribe video/audio files to text via faster-whisper.
Optionally describes video keyframes via multimodal vision LLM.

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

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from agents.doc_agent import RawDocument

logger = logging.getLogger(__name__)

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


# ── Keyframe extraction + vision description ────────────────────────────────

def _extract_keyframes(video_path: str, interval_seconds: int) -> list[tuple[bytes, str]]:
    """Extract one JPEG frame every *interval_seconds* from *video_path*.

    Returns a list of ``(jpeg_bytes, timestamp_label)`` tuples.
    Requires ffmpeg in PATH.
    """
    import glob

    tmp_dir = tempfile.mkdtemp(prefix="omnikb_frames_")
    pattern = os.path.join(tmp_dir, "frame_%05d.jpg")
    vf_filter = f"fps=1/{interval_seconds}"
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf_filter,
        "-q:v", "4",   # JPEG quality (2=best, 31=worst); 4 is a good balance
        pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    frames: list[tuple[bytes, str]] = []

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")[:400]
        logger.warning("ffmpeg keyframe extraction failed: %s", stderr)
        return frames

    jpeg_files = sorted(glob.glob(os.path.join(tmp_dir, "frame_*.jpg")))
    for idx, fpath in enumerate(jpeg_files):
        ts_secs = idx * interval_seconds
        label = f"{ts_secs // 60:02d}:{ts_secs % 60:02d}"
        try:
            with open(fpath, "rb") as f:
                frames.append((f.read(), label))
        except OSError:
            pass
        finally:
            try:
                os.unlink(fpath)
            except OSError:
                pass

    try:
        os.rmdir(tmp_dir)
    except OSError:
        pass

    return frames


async def describe_video_frames(video_path: str, interval_seconds: int) -> str:
    """Extract keyframes from *video_path* and describe each with the vision LLM.

    Returns a concatenated string of timestamped frame descriptions,
    or an empty string if vision is disabled or no frames were extracted.
    """
    from agents.vision_agent import describe_frame, is_vision_enabled

    if not is_vision_enabled() or interval_seconds <= 0:
        return ""

    frames = await asyncio.get_event_loop().run_in_executor(
        None, _extract_keyframes, video_path, interval_seconds
    )
    if not frames:
        return ""

    descriptions: list[str] = []
    for jpeg_bytes, label in frames:
        try:
            desc = await describe_frame(jpeg_bytes, mime="image/jpeg")
            if desc.strip():
                descriptions.append(f"[{label}] {desc}")
        except Exception as exc:
            logger.warning("Frame vision description failed at %s: %s", label, exc)

    return "\n".join(descriptions)


async def transcribe_async(
    file_path: str | Path,
    model_size: str = "base",
) -> RawDocument:
    """Async transcription with optional vision keyframe descriptions for video.

    Combines Whisper transcript with per-frame visual descriptions when
    ``VISION_ENABLED=true`` and ``VISION_FRAME_INTERVAL > 0``.
    """
    from config import settings

    path = Path(file_path)
    ext = path.suffix.lower()

    # Run Whisper in thread pool (CPU-bound)
    raw_doc = await asyncio.get_event_loop().run_in_executor(
        None, transcribe, str(path), model_size
    )

    # Optionally append video frame descriptions
    if ext in VIDEO_EXTENSIONS and settings.vision_frame_interval > 0:
        frame_text = await describe_video_frames(str(path), settings.vision_frame_interval)
        if frame_text:
            combined = raw_doc.content + "\n\n--- 视频画面描述 ---\n" + frame_text
            raw_doc = RawDocument(
                content=combined,
                metadata={**raw_doc.metadata, "frame_descriptions": True},
            )

    return raw_doc

