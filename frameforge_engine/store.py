from __future__ import annotations

import json
import re
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .errors import FrameForgeError
from .models import JobState, utc_now

JOB_ID = re.compile(r"^[0-9a-f]{32}$")


class JobStore:
    def __init__(self, root: Path):
        self.root = root / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def job_dir(self, job_id: str) -> Path:
        if not JOB_ID.fullmatch(job_id):
            raise FrameForgeError("JOB_NOT_FOUND", "Frame Forge job not found.", 404)
        return self.root / job_id

    def _state_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "state.json"

    def create(self, state: JobState) -> JobState:
        with self.lock:
            directory = self.job_dir(state.job_id)
            directory.mkdir(mode=0o700, parents=True, exist_ok=False)
            self._write(state)
        return state

    def _write(self, state: JobState) -> None:
        path = self._state_path(state.job_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    def get(self, job_id: str) -> JobState:
        with self.lock:
            path = self._state_path(job_id)
            if not path.is_file():
                raise FrameForgeError("JOB_NOT_FOUND", "Frame Forge job not found.", 404)
            try:
                return JobState.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise FrameForgeError("JOB_STATE_INVALID", "Stored job metadata is invalid.", 500) from exc

    def update(self, job_id: str, **changes) -> JobState:
        with self.lock:
            state = self.get(job_id)
            changes["updated_at"] = utc_now()
            updated = state.model_copy(update=changes)
            self._write(updated)
            return updated

    def output_path(self, state: JobState) -> Path:
        if not state.output_name:
            raise FrameForgeError("OUTPUT_NOT_READY", "Job output is not ready.", 409)
        path = self.job_dir(state.job_id) / state.output_name
        if not path.is_file():
            raise FrameForgeError("OUTPUT_MISSING", "Job output is unavailable.", 410)
        return path

    def cleanup(self, retention_hours: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
        removed = 0
        with self.lock:
            for directory in self.root.iterdir():
                if not directory.is_dir() or not JOB_ID.fullmatch(directory.name):
                    continue
                try:
                    state = self.get(directory.name)
                    created = datetime.fromisoformat(state.created_at)
                except Exception:
                    created = datetime.fromtimestamp(directory.stat().st_mtime, timezone.utc)
                if created < cutoff:
                    shutil.rmtree(directory)
                    removed += 1
        return removed

    def recover_interrupted(self) -> int:
        recovered = 0
        with self.lock:
            for directory in self.root.iterdir():
                if not directory.is_dir() or not JOB_ID.fullmatch(directory.name):
                    continue
                try:
                    state = self.get(directory.name)
                except FrameForgeError:
                    continue
                if state.status in {"queued", "processing"}:
                    self.update(
                        state.job_id,
                        status="failed",
                        stage="interrupted",
                        error={
                            "code": "ENGINE_RESTARTED",
                            "message": "The engine restarted before the provider result was confirmed. Check provider history before resubmitting to avoid duplicate cost.",
                        },
                    )
                    recovered += 1
        return recovered

