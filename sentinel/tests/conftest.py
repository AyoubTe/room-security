import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HAS_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory):
    """A short H.264 clip that ffmpeg loops, standing in for the camera's RTSP stream."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "testsrc=size=320x240:rate=10", "-t", "6", "-c:v", "libx264",
         "-g", "10", "-pix_fmt", "yuv420p", str(path)],
        capture_output=True,
    )
    if r.returncode != 0:
        pytest.skip("ffmpeg cannot encode H.264 here: " + r.stderr.decode()[-200:])
    return path


@pytest.fixture
def fake_rclone(tmp_path):
    """A stand-in for rclone that 'uploads' by copying into a local folder."""
    dest = tmp_path / "cloud"
    dest.mkdir()
    script = tmp_path / "fake_rclone.sh"
    script.write_text(
        "#!/bin/sh\n"
        # args: copyto SRC REMOTE:path/to/file ...
        'src="$2"; dst="$3"\n'
        f'rel="${{dst#fake:}}"\n'
        f'mkdir -p "{dest}/$(dirname "$rel")" && cp "$src" "{dest}/$rel"\n'
    )
    script.chmod(0o755)
    return script, dest
