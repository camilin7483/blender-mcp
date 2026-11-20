"""Rewrite Blender's extension ZIP with stable paths, ordering and metadata."""

import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def normalize(archive: Path) -> None:
    normalized = archive.with_suffix(".normalized.zip")
    try:
        with ZipFile(archive) as source, ZipFile(normalized, "w") as dest:
            for name in sorted(source.namelist()):
                if name.endswith("/") or "__pycache__" in Path(name).parts or name.endswith(".pyc"):
                    continue
                entry = ZipInfo(name)
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                dest.writestr(entry, source.read(name), compress_type=ZIP_DEFLATED, compresslevel=9)
        normalized.replace(archive)
    finally:
        normalized.unlink(missing_ok=True)


if __name__ == "__main__":
    normalize(Path(sys.argv[1]))
