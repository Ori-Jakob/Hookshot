// keep_resampled (gpu/vk/keep_resampled.h): the textures the GPU drew that the game samples again after finalizing them, used
// recently, stay through an eviction pass over the budget, up to a cap spent on the most recently used. tests/test_keep_resampled.py
#include "../gpu/vk/keep_resampled.h"

#include <cstdio>
#include <cstdlib>

static int failures = 0;
static void expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        failures++;
    }
}

int main() {
    const uint64_t MB = 1ull << 20, max = 512 * MB;
    using keep_resampled::candidate;
    using keep_resampled::keep;
    using keep_resampled::kMaxUnused;

    expect(candidate(false, true, true, 400), "the 12288 x 12288 shadow map, sampled again, unused 400 presents: a candidate");
    expect(!candidate(true, true, true, 0), "drawn over since: nothing left to keep");
    expect(!candidate(false, false, true, 0), "uploaded from the game's memory: made again from there");
    expect(!candidate(false, true, false, 0), "never sampled again after finalizing: goes as before");
    expect(kMaxUnused == vram_compact::kReserveUnused, "the age limit is the compaction reserve's line");
    expect(candidate(false, true, true, kMaxUnused - 1), "unused one present short of 1,800: still one");
    expect(!candidate(false, true, true, kMaxUnused), "unused 1,800 presents: the reserve's, not kept here");
    expect(!candidate(false, true, true, kMaxUnused + 1), "unused longer (an area left behind): goes, as #2198's reserve lets it");

    // within the cap: every candidate kept, the total unchanged
    uint64_t total = 288 * MB + 32 * MB;
    expect(keep(288 * MB, total, max) && keep(32 * MB, total, max) && total == 320 * MB, "both shadow maps fit: kept");
    total = max;
    expect(keep(1, total, max), "exactly the cap: kept");

    // over the cap, oldest first: the oldest go until the rest fit, then the most recently used are kept
    total = 288 * MB + 288 * MB + 32 * MB;   // (608 MB: oldest 288, then 288, then the newest 32)
    expect(!keep(288 * MB, total, max) && total == 320 * MB, "the oldest 288 MB one goes, leaving 320 MB");
    expect(keep(288 * MB, total, max), "the next fits now: kept");
    expect(keep(32 * MB, total, max), "the newest: kept");
    expect(total == 320 * MB, "kept ones leave the total");

    uint64_t drift = 2;
    expect(!keep(8, drift, 1) && drift == 0, "a total below a texture's bytes clamps at 0, not wraps");

    uint64_t none = 64 * MB;
    expect(!keep(1, none, 0), "RX_VK_KEEP_RESAMPLED_MB=0: evicted as before");
    if (failures) return EXIT_FAILURE;
    std::printf("keep resampled: all checks passed\n");
    return EXIT_SUCCESS;
}
