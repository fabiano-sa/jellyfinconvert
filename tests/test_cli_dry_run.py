from pathlib import Path
import subprocess
import sys


def test_cli_dry_run(tmp_path: Path):
    # create a dummy "input file" (we don't play/parse it in M1)
    inp = tmp_path / "sample.mkv"
    inp.write_bytes(b"fake-video")

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # run the module with --dry-run (default is True in M1)
    cmd = [sys.executable, "-m", "src.app.main", "-i", str(tmp_path), "-o", str(out_dir), "--container", "mp4", "--title", "Hello", "--year", "2024"]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    assert proc.returncode == 0
    # It should mention ffmpeg command in stdout
    assert "ffmpeg" in proc.stdout.lower()
    # and save reports
    assert (Path("logs") / "report.csv").exists()
    assert (Path("logs") / "report.json").exists()
