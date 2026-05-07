from __future__ import annotations
import shutil
from pathlib import Path

import aiofiles

from config import settings


def _files_dir() -> Path:
    return Path(settings.data_dir) / "files"


def init_file_store() -> None:
    _files_dir().mkdir(parents=True, exist_ok=True)


async def save_file(file_id: str, filename: str, content: bytes) -> Path:
    dest_dir = _files_dir() / file_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)
    return dest


def get_file_path(file_id: str, filename: str) -> Path:
    return _files_dir() / file_id / filename


def delete_file(file_id: str) -> None:
    dest_dir = _files_dir() / file_id
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
