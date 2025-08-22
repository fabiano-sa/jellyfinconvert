"""
Per-file reporting for conversions.

We keep a small CSV and JSON report so users can audit results later.
In Milestone 1, we fill basic fields (even if --dry-run).
"""

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.ffmpeg_utils import human_size


@dataclass
class FileReport:
    input_path: str
    output_path: str
    status: str  # "success" | "fail" | "dry-run"
    error: str
    duration_sec: float
    input_size: int
    output_size: int

    @property
    def input_size_human(self) -> str:
        return human_size(self.input_size) if self.input_size else "0 B"

    @property
    def output_size_human(self) -> str:
        return human_size(self.output_size) if self.output_size else "0 B"

    @property
    def size_diff(self) -> int:
        return (self.output_size or 0) - (self.input_size or 0)

    @property
    def size_diff_human(self) -> str:
        diff = self.size_diff
        sign = "+" if diff >= 0 else "-"
        return f"{sign}{human_size(abs(diff))}"


class Reporter:
    """
    Collects FileReport rows and writes them to CSV and JSON.
    """

    def __init__(self, csv_path: Path, json_path: Path) -> None:
        self.csv_path = csv_path
        self.json_path = json_path
        self.rows: list[FileReport] = []
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, row: FileReport) -> None:
        self.rows.append(row)

    def write(self) -> None:
        # CSV
        with self.csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "input_path",
                    "output_path",
                    "status",
                    "error",
                    "duration_sec",
                    "input_size",
                    "input_size_human",
                    "output_size",
                    "output_size_human",
                    "size_diff",
                    "size_diff_human",
                ]
            )
            for r in self.rows:
                w.writerow(
                    [
                        r.input_path,
                        r.output_path,
                        r.status,
                        r.error,
                        f"{r.duration_sec:.3f}",
                        r.input_size,
                        r.input_size_human,
                        r.output_size,
                        r.output_size_human,
                        r.size_diff,
                        r.size_diff_human,
                    ]
                )
        # JSON
        with self.json_path.open("w", encoding="utf-8") as f:
            json.dump(
                [
                    asdict(r)
                    | {
                        "input_size_human": r.input_size_human,
                        "output_size_human": r.output_size_human,
                        "size_diff_human": r.size_diff_human,
                    }
                    for r in self.rows
                ],
                f,
                indent=2,
                ensure_ascii=False,
            )
