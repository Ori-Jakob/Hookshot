// Which textures the GPU drew and the game samples again after finalizing them the eviction pass keeps (vk_texture.cpp).
// tests/test_keep_resampled.py
#pragma once
#include <algorithm>
#include <cstdint>

#include "vram_compact.h"

namespace keep_resampled {

// A texture the GPU drew, that the game finalized and then sampled again (Texture::resampled), with nothing drawn over its
// storage since: a cache the game keeps, such as the 12288 x 12288 shadow map it draws once and samples for many frames. It is
// depth, so its texels cannot be written back into its memory; evicted over the budget, it was made again over storage the GPU
// rendered, not uploaded, and sampled EMPTY until the game drew it again some 40 frames later (Dodongo's Cavern at a 512 MB
// budget, issue 2209's dark ground in Hyrule Field).
//
// Only while used in the last kMaxUnused presents (unused for fewer), the compaction reserve's own line (#2198): one from an
// area left behind goes as before, and a texture this rule keeps is never one the reserve may take. The 12288 x 12288 map went
// unused 400 presents before the eviction took it.
constexpr uint64_t kMaxUnused = vram_compact::kReserveUnused;
inline bool recent(uint64_t unused) { return unused < kMaxUnused; }
inline bool candidate(bool overwritten, bool gpu_written, bool resampled, uint64_t unused) {
    return !overwritten && gpu_written && resampled && recent(unused);
}

// The candidates' bytes are summed before the pass (total); the pass walks the textures least recently used first, so a candidate
// is kept while the total left is within max, and beyond it this one, the oldest, goes and leaves the total: the cap is spent on
// the most recently used, as keep_finalized does. max 0: none kept
inline bool keep(uint64_t bytes, uint64_t& total, uint64_t max) {
    if (!max) return false;
    if (total <= max) return true;
    total -= std::min(total, bytes);
    return false;
}

} // namespace keep_resampled
