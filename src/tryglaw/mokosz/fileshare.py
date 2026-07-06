from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHUNK_SIZE = 65536


@dataclass
class RootConfig:
    name: str
    path: str
    writable: bool = False


@dataclass
class FileshareConfig:
    roots: list[RootConfig]
    max_file_size_mb: int = 100

    @classmethod
    def load(cls, config_path: str) -> FileshareConfig:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        roots = [RootConfig(**r) for r in data.get("roots", [])]
        return cls(roots=roots, max_file_size_mb=data.get("max_file_size_mb", 100))

    def get_root(self, name: str) -> RootConfig | None:
        for r in self.roots:
            if r.name == name:
                return r
        return None


def safe_resolve(root: RootConfig, rel_path: str) -> Path:
    root_real = Path(root.path).resolve()
    target = (root_real / rel_path).resolve()
    if not str(target).startswith(str(root_real)):
        raise PermissionError(f"path_traversal: {rel_path}")
    return target


def list_dir(root: RootConfig, rel_path: str) -> list[dict[str, Any]]:
    target = safe_resolve(root, rel_path)
    if not target.is_dir():
        raise FileNotFoundError(f"not_a_directory: {rel_path}")
    entries = []
    for item in sorted(target.iterdir()):
        try:
            st = item.stat()
            entries.append({
                "name": item.name,
                "is_dir": item.is_dir(),
                "size": st.st_size if not item.is_dir() else 0,
                "mtime": int(st.st_mtime),
            })
        except OSError:
            continue
    return entries


def stat_path(root: RootConfig, rel_path: str) -> dict[str, Any]:
    target = safe_resolve(root, rel_path)
    if not target.exists():
        raise FileNotFoundError(f"not_found: {rel_path}")
    st = target.stat()
    return {
        "name": target.name,
        "is_dir": target.is_dir(),
        "size": st.st_size if not target.is_dir() else 0,
        "mtime": int(st.st_mtime),
        "writable": root.writable,
    }


def mkdir(root: RootConfig, rel_path: str) -> None:
    if not root.writable:
        raise PermissionError("root_not_writable")
    target = safe_resolve(root, rel_path)
    target.mkdir(parents=True, exist_ok=True)


def delete_path(root: RootConfig, rel_path: str) -> None:
    if not root.writable:
        raise PermissionError("root_not_writable")
    target = safe_resolve(root, rel_path)
    if not target.exists():
        raise FileNotFoundError(f"not_found: {rel_path}")
    if target.is_dir():
        target.rmdir()
    else:
        target.unlink()


KIND_FILE = 0x02


async def stream_download(ws, root: RootConfig, rel_path: str, stream_id: int) -> None:
    target = safe_resolve(root, rel_path)
    if not target.is_file():
        raise FileNotFoundError(f"not_a_file: {rel_path}")

    with open(target, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            frame = struct.pack(">BI", KIND_FILE, stream_id) + chunk
            await ws.send(frame)

    from tryglaw.common.models import FileDataEnd
    await ws.send(FileDataEnd(stream_id=stream_id).model_dump_json())


async def receive_upload(
    ws_data_callback,
    root: RootConfig,
    rel_path: str,
    max_size_bytes: int,
) -> None:
    if not root.writable:
        raise PermissionError("root_not_writable")
    target = safe_resolve(root, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with open(target, "wb") as f:
        async for chunk in ws_data_callback:
            total += len(chunk)
            if total > max_size_bytes:
                f.close()
                target.unlink(missing_ok=True)
                raise PermissionError(f"file_too_large: max {max_size_bytes} bytes")
            f.write(chunk)
