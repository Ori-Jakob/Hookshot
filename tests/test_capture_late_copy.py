"""The late pages' GPU copies (gpu/vk/vk_memory.cpp late_copy_runs): the runs in the capture's page order, from the pool
that holds each page, into its slot; the fallback: a page no imported pool holds has no GPU source, so the caller keeps
the CPU wait and copies it once the write-back landed (never a stale copy); and the seams the back end links through:
replay_burst_open and replay_burst_value at namespace scope, the parallel guard and the pending-pages cap.

Also the sweep's rules: a burst blocks a copy only for the write-backs tagged with its own value (an older one's is
already on the queue); a page is copied from the pool's write-back shadow, not the live guest buffer, and only when the
shadow holds it; the flush re-checks the shadow and the write-back, and falls back to the CPU wait when either moved.

python -I -B tests/test_capture_late_copy.py [--cxx clang++]
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

RUN_ALL_ARGS = ["--cxx", "{cxx}"]   # (a compiler the runner has: skipped where there is none)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def namespace_scope(text, needle):
    """True when the first line holding `needle` is not inside an anonymous namespace (internal linkage: the DLL's other
    objects could not call it, the llvm-mingw link check failed on mkwvk::replay_burst_open)."""
    stack = []
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"namespace\s*\{\s*$", s):
            stack.append("anon")
        elif re.match(r"namespace\s+\w+\s*\{\s*$", s):
            stack.append("named")
        elif re.match(r"\}\s*//\s*namespace\b", s):
            if stack:
                stack.pop()
        if needle in line:
            return "anon" not in stack
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--source", type=Path, default=ROOT / "gpu/vk/vk_memory.cpp")
    parser.add_argument("--replay-source", type=Path, default=ROOT / "gpu/vk/vk_replay.cpp")
    parser.add_argument("--internal-header", type=Path, default=ROOT / "gpu/vk/vk_internal.h")
    parser.add_argument("--emit", type=Path, help="write the fixture there and stop (to build it by hand)")
    args = parser.parse_args()
    source = args.source.read_text(encoding="utf-8")
    take = block(source, "bool take_capture(")
    plan = block(source, "bool late_copy_plan(")
    flush = block(source, "void late_copy_flush()")
    read = block(source, "bool memory_read_as_submitted(")
    if take.find("late_copy_plan(*c, value)") < 0 or take.find("late_copy_plan(*c, value)") > take.find("vk_timeline_wait(c->late_value);"):
        raise SystemExit("take_capture: the GPU copy is not planned before the CPU wait (the wait is the fallback)")
    if "vk_timeline_wait(" in plan:
        raise SystemExit("late_copy_plan waits for the GPU: the copy is deferred to the recording")
    if "upload_command_buffer()" not in flush or "late_merge_record(" not in flush:
        raise SystemExit("late_copy_flush: the copies are not recorded in the submission's upload command buffer")
    if "late_page_pending(" not in read:
        raise SystemExit("memory_read_as_submitted: a late page's slot is read before its GPU copy lands")
    replay = args.replay_source.read_text(encoding="utf-8")
    if not namespace_scope(replay, "bool replay_burst_open()"):
        raise SystemExit("replay_burst_open is defined in an anonymous namespace: internal linkage, the back end does not link")
    if not namespace_scope(replay, "uint64_t replay_burst_value()"):
        raise SystemExit("replay_burst_value is defined in an anonymous namespace: internal linkage, the back end does not link")
    header = args.internal_header.read_text(encoding="utf-8")
    if "bool replay_burst_open();" not in header:
        raise SystemExit("vk_internal.h does not declare replay_burst_open")
    if "uint64_t replay_burst_value();" not in header:
        raise SystemExit("vk_internal.h does not declare replay_burst_value")
    if "late_burst_blocks(c.late_value, replay_burst_open(), replay_burst_value())" not in plan or "replay_burst_open() ||" in plan:
        raise SystemExit("late_copy_plan: a burst refuses every copy: only the write-backs tagged with its own value need the CPU wait")
    if plan.find("p->shadow") < 0 or plan.find("shadow_known") < 0 or "late_shadow_eligible(" not in plan:
        raise SystemExit("late_copy_plan: the late pages are not copied from the pool's write-back shadow")
    if "p->buffer, {r.src" in plan:
        raise SystemExit("late_copy_plan: the late pages are copied from the live guest buffer (it changes under the copy)")
    if flush.find("late_copy_still_valid(") < 0 or flush.find("wb_page_value(") < 0 or flush.find("imported.find(") < 0:
        raise SystemExit("late_copy_flush: the shadow and the page's write-back are not checked again")
    if flush.find("vk_timeline_wait(") < 0 or flush.find("guarded_copy(") < 0:
        raise SystemExit("late_copy_flush: a page whose shadow moved has no CPU wait and copy")
    gpu_on = block(source, "bool gpu_late_on()")
    if gpu_on.find("RX_VK_PARALLEL") < 0 or gpu_on.find("RX_VK_PARALLEL") > gpu_on.find("RX_VK_CAPTURE_GPU_LATE"):
        raise SystemExit("gpu_late_on: RX_VK_CAPTURE_GPU_LATE=1 bypasses the parallel replay's guard")
    if "kLatePagesMax" not in plan or "late_pages_n" not in plan:
        raise SystemExit("late_copy_plan: no cap on the pending late pages")
    runs_fn = block(source, "bool late_copy_runs(")
    late_run = block(source, "struct LateRun {") + ";"
    burst_rule = block(source, "bool late_burst_blocks(")
    shadow_rule = block(source, "bool late_shadow_eligible(")
    valid_rule = block(source, "bool late_copy_still_valid(")
    fixture = (
        r'''
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <utility>
#include <vector>
constexpr uint64_t kPageShift = 12;   // (vk_memory.cpp's: 4 KB pages)
#define CHECK(ok) do { if (!(ok)) { std::fprintf(stderr, "failed line %d\n", __LINE__); std::exit(1); } } while (0)
'''
        + late_run
        + "\n"
        + runs_fn
        + "\n"
        + burst_rule
        + "\n"
        + shadow_rule
        + "\n"
        + valid_rule
        + r'''
int main() {
    const std::vector<uint32_t> pages = {0x100, 0x101, 0x102, 0x300, 0x500, 0x103};
    const std::vector<std::pair<uint64_t, uint64_t>> pools = {{0x100ull << 12, 0x103ull << 12},
                                                              {0x300ull << 12, 0x301ull << 12}};
    std::vector<LateRun> runs;
    // (a run a late page, in the order the capture lists them: page 0x102 first though it is not the lowest)
    CHECK(late_copy_runs({2, 0}, pages, pools, runs) && runs.size() == 2);
    CHECK(runs[0].pool == 0 && runs[0].src == 2 * 4096 && runs[0].dst == 2 * 4096);
    CHECK(runs[1].pool == 0 && runs[1].src == 0 && runs[1].dst == 0);
    // (each from the pool that holds it, at its offset there)
    CHECK(late_copy_runs({3}, pages, pools, runs) && runs.size() == 1);
    CHECK(runs[0].pool == 1 && runs[0].src == 0 && runs[0].dst == 3 * 4096);
    CHECK(late_copy_runs({3, 1}, pages, pools, runs) && runs.size() == 2);
    CHECK(runs[0].pool == 1 && runs[1].pool == 0 && runs[1].src == 4096 && runs[1].dst == 4096);
    // (a page in no imported pool: no GPU source, the CPU waits and copies it as before)
    CHECK(!late_copy_runs({4}, pages, pools, runs) && runs.empty());
    // (a page whose 4 KB runs past its pool's end: the pool does not hold it)
    CHECK(!late_copy_runs({5}, pages, pools, runs) && runs.empty());
    // (an index past the capture's pages, and no late pages at all)
    CHECK(!late_copy_runs({6}, pages, pools, runs) && runs.empty());
    CHECK(late_copy_runs({}, pages, pools, runs) && runs.empty());
    // (an older burst: the write-back is in a submission before this recording, the copy goes on the GPU)
    CHECK(!late_burst_blocks(7, true, 9));
    // (the write-back tagged with the burst's own value: its uploads run before its write-backs, the CPU waits)
    CHECK(late_burst_blocks(9, true, 9));
    CHECK(late_burst_blocks(10, true, 9));
    // (no burst: the copy is planned as before)
    CHECK(!late_burst_blocks(7, false, 0));
    // (no shadow for the pool, or a page its shadow does not know: no GPU source, the CPU waits)
    CHECK(!late_shadow_eligible(false, false));
    CHECK(!late_shadow_eligible(true, false));
    CHECK(late_shadow_eligible(true, true));
    // (at the flush: the shadow still there, its page known, the write-back it owed unchanged; else the CPU fallback)
    CHECK(late_copy_still_valid(true, true, 7, 7));
    CHECK(!late_copy_still_valid(false, true, 7, 7));
    CHECK(!late_copy_still_valid(true, false, 7, 7));
    CHECK(!late_copy_still_valid(true, true, 7, 8));
    std::puts("PASS: the late pages' runs in capture order, each pool's offsets and the fallback; the burst, shadow and "
              "flush rules");
}
'''
    )
    with tempfile.TemporaryDirectory(prefix="capture-late-copy-") as tmp:
        cpp = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / "fixture.exe"
        cpp.write_text(fixture, encoding="utf-8")
        if args.emit:
            args.emit.write_text(fixture, encoding="utf-8")
            return
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=60)


if __name__ == "__main__":
    main()
