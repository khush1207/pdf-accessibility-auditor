import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = Path(__file__).parent / "samples"


@pytest.fixture(scope="session", autouse=True)
def samples():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_samples.py"), str(SAMPLES)], check=True, cwd=ROOT)
    return SAMPLES
