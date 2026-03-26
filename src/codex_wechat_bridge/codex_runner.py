from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path


@dataclass(frozen=True)
class CodexResult:
    thread_id: str
    response_text: str


class CodexRunner:
    def __init__(self, codex_bin: str, default_cwd: Path) -> None:
        self.codex_bin = codex_bin
        self.default_cwd = default_cwd

    def run_prompt(self, prompt: str, *, thread_id: str | None = None) -> CodexResult:
        with tempfile.NamedTemporaryFile(delete=False) as output_file:
            output_path = Path(output_file.name)
        try:
            if thread_id:
                cmd = [
                    self.codex_bin,
                    "exec",
                    "resume",
                    thread_id,
                    "-",
                    "--json",
                    "--output-last-message",
                    str(output_path),
                ]
                cwd = str(self.default_cwd)
            else:
                cmd = [
                    self.codex_bin,
                    "exec",
                    "-",
                    "-C",
                    str(self.default_cwd),
                    "--json",
                    "--output-last-message",
                    str(output_path),
                ]
                cwd = str(self.default_cwd)

            proc = subprocess.run(
                cmd,
                input=prompt.encode(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                check=False,
            )
            stdout = proc.stdout.decode(errors="replace").splitlines()
            stderr = proc.stderr.decode(errors="replace").strip()
            if proc.returncode != 0:
                tail = stderr or "\n".join(stdout[-10:])
                raise RuntimeError(f"codex failed: {tail}".strip())

            resolved_thread_id = thread_id
            for line in stdout:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("type") == "thread.started":
                    resolved_thread_id = event["thread_id"]
            if not resolved_thread_id:
                raise RuntimeError("codex did not report a thread id")
            response_text = output_path.read_text().strip()
            return CodexResult(thread_id=resolved_thread_id, response_text=response_text)
        finally:
            output_path.unlink(missing_ok=True)

    def find_latest_thread(self) -> str | None:
        state_db = Path.home() / ".codex" / "state_5.sqlite"
        if not state_db.exists():
            return None
        conn = sqlite3.connect(state_db)
        try:
            row = conn.execute(
                """
                select id
                from threads
                where cwd = ?
                order by updated_at desc
                limit 1
                """,
                (str(self.default_cwd),),
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            conn.close()
