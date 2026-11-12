"""The late pages' merge (gpu/vk/vk_memory.cpp, "the late copy's merge"): the fill pages of a write-back are snapshotted
from the shadow right after the fill and before the diff patches it; in the submission that uses the capture, the
write-back's own diff (shaders/wb_diff.comp, its word path) runs with that snapshot as its shadow and the capture's slot as
its guest. It writes the diff's words, and the capture's bytes at the words the diff did not change, stay.

Window (a): a CPU write between the capture and the write-back's fill lands in the fill (and so in the shadow the diff
compares) but not in the capture: the merge keeps the captured bytes there. Window (b): a page the write-back knew, with no
fill, has no snapshot: its post-diff shadow is no reference for the capture, and the plan sends it to the CPU wait.

python -I -B tests/test_capture_late_merge.py [--cxx g++]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--source", type=Path, default=ROOT / "gpu/vk/vk_memory.cpp")
    parser.add_argument("--shader", type=Path, default=ROOT / "gpu/vk/shaders/wb_diff.comp")
    parser.add_argument("--emit", type=Path, help="write the fixture there and stop (to build it by hand)")
    args = parser.parse_args()
    source = args.source.read_text(encoding="utf-8")
    record = block(source, "void memory_end_submission(")
    plan = block(source, "bool late_copy_plan(")
    flush = block(source, "void late_copy_flush()")
    merge = block(source, "bool late_merge_record(VkCommandBuffer cmd, const std::vector<LateCopy>& copies, VkBuffer dst, uint64_t value) {")
    snap = block(source, "void snap_record(")
    shadow = block(source, "bool shadow_make(")

    fill = record.find("vkCmdCopyBuffer(cmd, p->buffer, p->shadow")
    taken = record.find("snap_record(")
    dispatched = record.find("vkCmdDispatch(")
    if "snap_get(" not in record or "snap_record(" not in record:
        raise SystemExit("memory_end_submission: the write-back's fill pages are not snapshotted before the diff")
    if fill < 0 or taken < fill or dispatched < taken:
        raise SystemExit("memory_end_submission: the snapshot is not taken from the shadow after the fill and before the diff")
    barrier = record.find("transfer_barrier(cmd)", fill)
    if barrier < 0 or barrier > taken:
        raise SystemExit("memory_end_submission: no barrier between the fill and the snapshot (the copy may read the shadow unmade)")
    if "vkCmdCopyBuffer(cmd, p.shadow, e.buf" not in snap:
        raise SystemExit("snap_record: the snapshot is not copied from the pool's shadow")
    if "snap_lookup(" not in plan:
        raise SystemExit("late_copy_plan: a late page without a pre-diff snapshot is not sent to the CPU wait")
    if "late_merge_record(" not in flush:
        raise SystemExit("late_copy_flush: the kept pages are not merged with the write-back's diff")
    if "vkCmdCopyBuffer(cmd, src, late_plan.dst" in flush:
        raise SystemExit("late_copy_flush: the whole shadow page is copied over the capture (the merge is gone)")
    if "wbd_pipe.pipe" not in merge or "WbdChunk" not in merge or "vkCmdDispatch(" not in merge:
        raise SystemExit("late_merge_record: the write-back's diff is not run for the late pages")
    if "((uint64_t)1 << kPageShift) / 4" not in merge:
        raise SystemExit("late_merge_record: the chunks are not 4 KB of words (vecs = 0)")
    if "VK_BUFFER_USAGE_TRANSFER_SRC_BIT" not in shadow:
        raise SystemExit("shadow_make: the shadow cannot be a copy source (the snapshot reads it)")
    usage = source[source.index("constexpr VkBufferUsageFlags kCapBufferUsage"):]
    usage = usage[:usage.index(";")]
    if "VK_BUFFER_USAGE_STORAGE_BUFFER_BIT" not in usage or "VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT" not in usage:
        raise SystemExit("kCapBufferUsage: the diff cannot write a capture slot (storage, device address)")
    shader = args.shader.read_text(encoding="utf-8")
    if "const uint v = m.w[i];" not in shader or "if (v != s.w[i])" not in shader or "g.w[i] = v;" not in shader:
        raise SystemExit("wb_diff.comp: its word path is not the merge (the post-diff word over the guest where it differs)")

    fixture = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#define CHECK(ok) do { if (!(ok)) { std::fprintf(stderr, "failed line %d\n", __LINE__); std::exit(1); } } while (0)
// (the write-back's diff, wb_diff.comp's word path: the shadow, after, has the mirror's words where they differed, and
// guest memory is written back the same)
void wb_diff_words(const uint32_t* mirror, uint32_t* shadow, uint32_t* guest, size_t words) {
    for (size_t i = 0; i < words; i++) {
        const uint32_t v = mirror[i];
        if (v != shadow[i]) shadow[i] = v, guest[i] = v;
    }
}
// (the late merge: the same diff from the pre-diff snapshot, the capture's slot as the guest; a word is written only where
// the post-diff shadow differs from the snapshot, which is exactly where the diff wrote)
void late_merge_words(uint32_t* slot, const uint32_t* post_shadow, const uint32_t* snap, size_t words) {
    for (size_t i = 0; i < words; i++) {
        const uint32_t v = post_shadow[i];
        if (v != snap[i]) slot[i] = v;
    }
}
int main() {
    // (window (a): the CPU writes words 1 and 2 after the capture, before the write-back reads guest memory; word 0 is the
    // GPU's. The fill has the later writes; the diff leaves them; the merge keeps the capture's bytes there and the GPU's 0.)
    const uint32_t capture[4] = {10, 20, 30, 40};   // (the slot: guest memory at the capture)
    uint32_t fill[4] = {10, 21, 31, 40};            // (guest memory at the write-back's fill: the CPU's later writes in it)
    uint32_t snap[4], shadow[4], guest[4];
    std::memcpy(snap, fill, sizeof fill), std::memcpy(shadow, fill, sizeof shadow), std::memcpy(guest, fill, sizeof guest);
    const uint32_t mirror[4] = {99, 21, 31, 40};    // (the GPU wrote word 0)
    wb_diff_words(mirror, shadow, guest, 4);
    uint32_t slot[4];
    std::memcpy(slot, capture, sizeof slot);
    late_merge_words(slot, shadow, snap, 4);
    CHECK(slot[0] == 99);                        // (the GPU's word)
    CHECK(slot[1] == 20 && slot[2] == 30);       // (the capture's bytes: the later writes do not land in it)
    CHECK(slot[3] == 40);
    // (the fill's later writes did land in guest memory: the whole-page shadow copy the merge replaces would have put them
    // over the capture)
    CHECK(guest[1] == 21 && guest[2] == 31);
    // (window (b): the page was known (no fill, no snapshot); the CPU wrote word 1 before the capture and the GPU word 0.
    // The CPU wait copies guest memory after the write-back: the GPU's word 0, the capture's word 1, the rest.)
    uint32_t after[4] = {10, 21, 30, 40};        // (guest memory: the CPU's word 1, the GPU about to write word 0)
    uint32_t stale[4] = {10, 20, 30, 40};        // (the shadow the page was known with)
    const uint32_t mirror_b[4] = {99, 21, 30, 40};
    wb_diff_words(mirror_b, stale, after, 4);
    CHECK(after[0] == 99 && after[1] == 21 && after[2] == 30 && after[3] == 40);
    // (no snapshot: the plan must not merge from the post-diff shadow, whose words at 1 and 2 are the stale 20 and 30; the
    // CPU wait's guest copy is the exact result)
    std::puts("PASS: the late merge with the pre-diff snapshot: the capture's bytes at the diff's unchanged words, the GPU's "
              "where it wrote; the no-fill page waits on the CPU");
}
'''
    with tempfile.TemporaryDirectory(prefix="capture-late-merge-") as tmp:
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
