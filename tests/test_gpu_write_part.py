"""A GPU buffer write into a texture's storage re-uploads the part it covers, not all of it (gpu/vk/vk_texture.cpp).

A buffer bound for writing marks its whole bound range written, though the shader may touch less of it, and the game's
transient scratch lands on the storage of a target the GPU drew and finalized: Castle Town after an area change took a
15 MB re-upload of a 2560x1440 target every frame of a burst, for a 1.75 MB bind (#2780: the fps of an area entered is
below that of the same area booted into, until the game is relaunched). The whole upload also copies, over what the GPU
drew, the memory of ranges nobody wrote. The statements of the marking and of the range it reports are cut from the
source and run against stand-ins for the map, the submissions and a texture:

  - a write inside the storage is reported as that part, in the image's own offsets;
  - a write spanning either end is clipped to the storage, and no range is reported outside it;
  - adjacent or overlapping writes come back as one range, in order;
  - a write of a submission the GPU has not finished is not reported, and is once it has;
  - the same write is not reported to the same texture twice (its seen value moves);
  - a write that does not reach the storage reports nothing and leaves no ranges;
  - the caller uploads the part (RX_VK_GPU_WRITE_WHOLE=1 asks for all of it again, as before), takes the CPU's writes
    since into the same part (the whole upload used to cover them, and upload_gen moves past them), and leaves the
    sparse images to the whole path.

python -I -B tests/test_gpu_write_part.py [--cxx g++]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    """the text from marker to the brace that closes its first '{'"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r"""
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <mutex>
#include <vector>

using Ranges = std::vector<std::pair<uint64_t, uint64_t>>;
struct Texture {
    uint64_t gpu = 0, guest_size = 0, gpu_wrote_seen = 0;
    uint32_t id = 0, width = 0, height = 0, nvn_format = 0;
};
uint64_t completed_value = 0, rec_value = 0, frame_no = 0, tl_watch_prog = 0;
std::map<uint64_t, std::pair<uint64_t, uint64_t>> gpu_wrote;
std::mutex gpu_wrote_mu;
static void logf(const char*, ...) {}

__CUTS__

static int fails;
static void check(bool ok, const char* what) {
    if (!ok) fails++, printf("FAIL: %s\n", what);
}
static std::pair<bool, Ranges> ask(Texture& t) {
    Ranges r;
    const bool d = gpu_wrote_into(t, &r);
    return {d, r};
}

int main() {
    {
        Texture t; t.gpu = 0x1000, t.guest_size = 0x1000;
        rec_value = 5; texture_gpu_wrote(0x1200, 0x100);
        completed_value = 5;
        auto [d, r] = ask(t);
        check(d && r.size() == 1 && r[0].first == 0x200 && r[0].second == 0x300, "a write inside reports its part");
        auto [d2, r2] = ask(t);
        check(!d2 && r2.empty(), "the same write is not reported twice");
    }
    {
        Texture u; u.gpu = 0x2000, u.guest_size = 0x100;
        rec_value = 6; texture_gpu_wrote(0x1F80, 0x200);
        completed_value = 6;
        auto [d, r] = ask(u);
        check(d && r.size() == 1 && r[0].first == 0 && r[0].second == 0x100, "a write over the ends is clipped");
    }
    {
        Texture v; v.gpu = 0x3000, v.guest_size = 0x1000;
        rec_value = 7; texture_gpu_wrote(0x3100, 0x100);
        rec_value = 8; texture_gpu_wrote(0x3200, 0x100);
        completed_value = 8;
        auto [d, r] = ask(v);
        check(d && r.size() == 1 && r[0].first == 0x100 && r[0].second == 0x300, "adjacent writes merge into one range");
    }
    {
        Texture w; w.gpu = 0x4000, w.guest_size = 0x100;
        rec_value = 9; texture_gpu_wrote(0x4010, 0x10);
        auto [d, r] = ask(w);
        check(!d && r.empty(), "an unfinished submission's write is not uploaded yet");
        completed_value = 9;
        auto [d2, r2] = ask(w);
        check(d2 && r2.size() == 1 && r2[0].first == 0x10 && r2[0].second == 0x20, "its part when the GPU is done with it");
    }
    {
        Texture x; x.gpu = 0x5000, x.guest_size = 0x10;
        rec_value = 10; texture_gpu_wrote(0x6000, 0x10);
        completed_value = 10;
        auto [d, r] = ask(x);
        check(!d && r.empty(), "a write elsewhere reports nothing");
    }
    return fails != 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()

    tex = (ROOT / "gpu" / "vk" / "vk_texture.cpp").read_text(encoding="utf-8")

    # (the calls the marking feeds: the part goes to the upload, with the CPU's writes since, and the whole path stays
    # for the sparse images and for RX_VK_GPU_WRITE_WHOLE)
    for needle, why in [
        ('static const bool gpu_write_whole = env_on("RX_VK_GPU_WRITE_WHOLE")',
         "asking for the whole image again on a GPU write has no switch"),
        ("const bool gpu_part = !no_partial && !gpu_write_whole && tex->uploaded && !tex->sparse;",
         "the GPU-write part does not say what it applies to (sparse images keep the whole path)"),
        ("gpu_wrote_into(*tex, gpu_part ? &dirty : nullptr)", "the GPU-write marking does not report the ranges it found"),
        ("if (gpu_partial) {", "the CPU's writes since a GPU write are not taken into the same part"),
        ("if (texture_dirty(*tex, since, cpu))", "the CPU's writes since a GPU write are not looked for"),
        ("const bool up_ok = upload(*tex, up_part ? &dirty : nullptr);", "the upload does not take the part"),
    ]:
        if needle not in tex:
            raise SystemExit("vk_texture.cpp no longer has: " + needle + "\n  (" + why + ")")

    cuts = block(tex, "void texture_gpu_wrote(uint64_t gpu, uint64_t size)") + "\n" + \
        block(tex, "bool gpu_wrote_into(Texture& tex, Ranges* out)")
    src = FIXTURE.replace("__CUTS__", cuts)

    with tempfile.TemporaryDirectory(prefix="gpu-write-part-") as tmp:
        p = Path(tmp) / "gpu_write_part.cpp"
        p.write_text(src, encoding="utf-8")
        exe = Path(tmp) / "gpu-write-part"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        # (_CRT_SECURE_NO_WARNINGS: the MSVC CRT's getenv deprecation, as the game's own Windows build passes)
                        "-D_CRT_SECURE_NO_WARNINGS", str(p), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("a GPU buffer write re-uploads the part of the storage it covers")


if __name__ == "__main__":
    main()
