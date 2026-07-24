from __future__ import annotations

import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def _backup_single_db(source_path: Path, dest_path: Path) -> None:
    """Copy a live WAL-mode SQLite file via backup() into a separate temp file."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    dst = sqlite3.connect(str(dest_path))
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()


def backup_databases_to_staging(databases_dir: Path, staging_dir: Path) -> None:
    """Snapshot every .db file and copy asset subdirectories into staging."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    db_dir = staging_dir / "databases"
    db_dir.mkdir(parents=True, exist_ok=True)

    for db_file in sorted(databases_dir.glob("*.db")):
        _backup_single_db(db_file, db_dir / db_file.name)

    for sub in ("welcome_backgrounds", "leave_backgrounds"):
        src = databases_dir / sub
        if src.is_dir():
            shutil.copytree(src, db_dir / sub, dirs_exist_ok=True)

    for asset in (
        "welcomecard.png",
        "Bold.ttf",
        "Medium.ttf",
        "MAXWITHSTRAPON.jpg",
        "max.ttf",
    ):
        src = databases_dir / asset
        if src.is_file():
            shutil.copy2(src, db_dir / asset)


def build_backup_zip(staging_dir: Path, zip_path: Path) -> int:
    """Create a ZIP from staging; returns size in bytes."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(staging_dir.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(staging_dir))
    return zip_path.stat().st_size


def make_backup_filename() -> str:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"dopamine-backup-{date}.zip"


def rotate_old_backups(backup_dir: Path, keep: str) -> None:
    """Keep up to 10 recent backups and remove older ones."""
    backups = list(backup_dir.glob("dopamine-backup-*.zip"))

    backups.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    for old in backups[10:]:
        old.unlink(missing_ok=True)
