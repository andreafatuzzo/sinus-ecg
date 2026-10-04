"""Writing files (architecture §8.2). Private: no public interface.

Every file that the package writes (downloaded files and checksum lists, reports, golden
vectors) is written by :func:`write_atomically`, so that a file under its final name is
always complete.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

#: Suffix of the temporary file of an atomic write: ``<name>.part~``. ``~`` cannot occur in a
#: path listed by a checksum list (architecture §8.3), so a temporary file never has the name
#: of a listed file.
PART_SUFFIX: Final = ".part~"


def write_atomically(path: Path, content: bytes) -> None:
    """Write ``content`` to ``path`` through a temporary file in the same folder.

    The folder of ``path`` and its parents are created if needed. ``content`` is written to
    ``<name>.part~`` in that folder, which then replaces ``<name>`` (:func:`os.replace`). A
    ``.part~`` file left by an interrupted run is overwritten by the next write of that file.

    Args:
        path: The file to write.
        content: Its bytes.

    Raises:
        OSError: If a folder cannot be created or the file cannot be written or replaced.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + PART_SUFFIX)
    part.write_bytes(content)
    os.replace(part, target)
