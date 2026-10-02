"""bump-s3dgraphy.sh never opens a pager (dev29, C1).

Measured on 2 Oct 2026: run by `./em.sh release` (step 6), its `git diff`
opened `less` and the release stopped on «:» until somebody pressed q. Every
git command in the script that prints must say `--no-pager`.
"""
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bump-s3dgraphy.sh"


def test_every_printing_git_command_says_no_pager():
    lines = [ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines()
             if not ln.lstrip().startswith("#")]
    paged = [ln for ln in lines
             if re.search(r"\bgit\s+(diff|log|show|blame)\b", ln)]
    assert not paged, paged
    assert any("git --no-pager diff" in ln for ln in lines)
