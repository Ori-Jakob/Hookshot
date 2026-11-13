"""Compile and run the rule that keeps the textures the GPU drew which the game samples again after finalizing them (gpu/vk/keep_resampled.h; no game/GPU)."""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]


def check_source():
    """The eviction pass still asks the rule, the flag is still set where a finalized texture is sampled again, and the switch is read"""
    src = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    for needle in ('#include "keep_resampled.h"',
                   "keep_resampled::candidate(overwritten, tex->gpu_written, tex->resampled, frame_no - last);",
                   "if (resampled_candidate && keep_resampled::keep(tex->bytes, resampled_total, keep_resampled_max)) {",
                   "keep_resampled::keep(tex->bytes, resampled_total, keep_resampled_max)",
                   "if (keep_resampled_max && tex->resampled && keep_resampled::recent(frame_no - tex->last_frame)) return false;",
                   "const bool finalized_after_resampled = keep_resampled_max && resampled_candidate && finalized_once(tex);",
                   "if (finalized_kept && (finalized_after_resampled || keep_finalized(tex))) {",
                   "if (tex->gpu_written && tex->released) tex->resampled = true;", 'getenv("RX_VK_KEEP_RESAMPLED_MB")'):
        if needle not in src:
            raise SystemExit("vk_texture.cpp no longer has: " + needle)
    if src.count("tex->resampled = false;") != src.count("tex->released = false;"):
        raise SystemExit("vk_texture.cpp: each place a texture is drawn again (released = false) must clear resampled too")
    if "bool resampled = false;" not in (ROOT / "gpu/vk/vk_texture.h").read_text(encoding="utf-8"):
        raise SystemExit("vk_texture.h no longer has the resampled flag")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="keep-resampled-") as tmp:
        exe = Path(tmp) / "keep-resampled"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/test_keep_resampled.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
