import logging
import threading
from pathlib import Path
from typing import Iterable, List

log = logging.getLogger("sc.media")

BLACK_FILENAME = "__black__.jpg"


class MediaStore:
    def __init__(
        self,
        directory: str,
        allowed_ext: Iterable[str],
        generate_black_if_empty: bool = True,
    ) -> None:
        self.dir = Path(directory)
        self.allowed = {e.lower() for e in allowed_ext}
        self._lock = threading.Lock()
        self._index = 0
        self._files: List[Path] = []

        self.dir.mkdir(parents=True, exist_ok=True)
        self.refresh()

        if not self._files and generate_black_if_empty:
            self._write_black(self.dir / BLACK_FILENAME)
            self.refresh()

        if not self._files:
            raise FileNotFoundError(
                f"no media in {self.dir} matching {sorted(self.allowed)}"
            )

    def _write_black(self, path: Path) -> None:
        from PIL import Image

        img = Image.new("RGB", (1080, 1920), (0, 0, 0))
        img.save(path, "JPEG", quality=85)
        log.info("generated fallback black image at %s", path)

    def refresh(self) -> List[Path]:
        files = sorted(
            p for p in self.dir.iterdir()
            if p.is_file() and p.suffix.lower() in self.allowed
        )
        with self._lock:
            self._files = files
        return files

    def next(self) -> Path:
        with self._lock:
            if not self._files:
                self.refresh()
            if not self._files:
                raise FileNotFoundError(f"media dir {self.dir} is empty")
            path = self._files[self._index % len(self._files)]
            self._index += 1
            return path

    def __len__(self) -> int:
        with self._lock:
            return len(self._files)
