"""The replay's per-draw caches (handle_hits, picks, a thread's pipelines) answer as std::unordered_map did.

FlatMap (gpu/vk/flat_map.h) is checked against std::unordered_map on random keys shaped like the replay's, with the
values the caches hold, through growth and the whole clears the replay does. texture_view_of is cut out of the source
and built twice, once over FlatMap and once over std::unordered_map, and fed the same calls while slots are registered
anew, textures destroyed and submissions pass: the views, the stubs called and their order must match.

python -I -B tests/test_flat_map.py --cxx clang++
"""
import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"

STUBS = r'''
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>
#include "flat_map.h"

typedef struct VkImageView_T* VkImageView;
enum VkImageViewType { VK_IMAGE_VIEW_TYPE_1D, VK_IMAGE_VIEW_TYPE_2D, VK_IMAGE_VIEW_TYPE_3D, VK_IMAGE_VIEW_TYPE_CUBE };
enum VkFormat { VK_FORMAT_UNDEFINED = 0, VK_FORMAT_R8G8B8A8_UNORM = 37, VK_FORMAT_R32_UINT = 98 };
#define VK_NULL_HANDLE nullptr
enum class ViewUse { Sample, Attachment, Storage };
struct Texture { int id; };
struct nvn_tex {
    struct { int target, format; uint32_t width, height, depth, levels; } d;
    uint64_t gpu;
};
struct nvn_view { bool set_format, set_target; int format, target; uint32_t level; };

std::string trace;   // what the stubs were asked, in order
uint32_t versions[4096];
uint64_t destroy_gen = 1;
uint32_t epoch = 1;
Texture textures[4096];
void note(const char* what, uint64_t a, uint64_t b = 0) {
    char line[96];
    snprintf(line, sizeof line, "%s %llx %llx;", what, (unsigned long long)a, (unsigned long long)b);
    trace += line;
}
uint32_t texture_slot_version(int id) { return versions[id & 4095]; }
uint64_t texture_destroy_generation() { return destroy_gen; }
uint32_t texture_epoch() { return epoch; }
bool env_on(const char*) { return false; }
void logf(const char*, ...) {}
struct ParLock {};
bool texture_touch_quick(Texture* t, bool sampling) {
    note("touch_quick", (uint64_t)t->id, sampling);
    return (t->id + epoch) % 3 != 0;
}
void texture_touch(Texture* t, bool sampling) { note("touch", (uint64_t)t->id, sampling); }
bool texture_of(int id, nvn_tex* t, nvn_view* v, bool* has_view) {
    note("texture_of", (uint64_t)id, versions[id & 4095]);
    if (id % 17 == 0) return false;
    *t = {};
    t->d.width = 64, t->gpu = (uint64_t)id << 12;
    *v = {};
    v->level = id % 4;
    *has_view = id % 2;
    return true;
}
Texture* texture_get(const nvn_tex* t, bool for_sampling) {
    note("texture_get", t->gpu, for_sampling);
    const uint64_t id = t->gpu >> 12;
    if (id % 13 == 0) return nullptr;
    textures[id & 4095].id = (int)id;
    return &textures[id & 4095];
}
VkImageView texture_view(Texture* tex, const nvn_tex*, const nvn_view* v, VkImageViewType want, ViewUse use, VkFormat* last,
                         VkFormat storage_as) {
    note("texture_view", (uint64_t)tex->id, (uint64_t)want << 8 | (uint64_t)use << 4 | (v != nullptr));
    *last = storage_as;
    if ((tex->id + (int)want) % 11 == 0) return VK_NULL_HANDLE;
    return (VkImageView)(uintptr_t)(((uint64_t)tex->id << 16 | (uint64_t)want << 8 | (uint64_t)use << 4) + destroy_gen * 0x1000000 +
                                    (uint64_t)storage_as * 0x100000000ull + versions[tex->id & 4095] * 0x10000000000ull);
}
uint32_t view_level(const nvn_view* v) { return v->level; }
uint32_t image_level(Texture*, uint32_t level) { return level + 1; }
'''

MAIN = r'''
template <class A, class B>
void same_maps(A& a, B& b, uint64_t key, int line) {
    auto x = a.find(key);
    auto y = b.find(key);
    if ((x == a.end()) != (y == b.end()) || a.size() != b.size()) {
        fprintf(stderr, "maps differ at key %llx (line %d)\n", (unsigned long long)key, line);
        exit(1);
    }
    if (x != a.end() && !(x->second == y->second)) {
        fprintf(stderr, "values differ at key %llx (line %d)\n", (unsigned long long)key, line);
        exit(1);
    }
}

struct Pick {
    const void* p = nullptr;
    std::vector<uint32_t> handles;
    bool operator==(const Pick& o) const { return p == o.p && handles == o.handles; }
};

template <class V, class Make>
void map_against_std(std::mt19937_64& r, uint64_t (*key)(std::mt19937_64&), Make make, size_t cap, int ops) {
    std::unordered_map<uint64_t, V> a;
    FlatMap<uint64_t, V> b;
    for (int i = 0; i < ops; i++) {
        const uint64_t k = key(r);
        switch (r() % 8) {
        case 0: case 1: case 2:
            same_maps(a, b, k, __LINE__);
            break;
        case 3: {   // (texture_view_of: a search, then the entry written whether it was there or not)
            const V v = make(r);
            a[k] = v, b[k] = v;
            break;
        }
        case 4: {   // (program_for: the entry made empty on a miss, then filled in through the reference)
            V& x = a[k];
            V& y = b[k];
            if (!(x == y)) { fprintf(stderr, "operator[] differs\n"); exit(1); }
            const V v = make(r);
            x = v, y = v;
            break;
        }
        default: {
            auto x = a.find(k);
            auto y = b.find(k);
            if (x != a.end() && y != b.end()) {
                const V v = make(r);
                x->second = v, y->second = v;
            }
            break;
        }
        }
        if (a.size() > cap) a.clear();
        if (b.size() > cap) b.clear();
        same_maps(a, b, k, __LINE__);
    }
    if (a.size() != b.size()) { fprintf(stderr, "sizes differ\n"); exit(1); }
    for (const auto& [k, v] : a) same_maps(a, b, k, __LINE__);
}

uint64_t texture_key(std::mt19937_64& r) {
    return (r() % 3000) | (r() % 8) << 20 | (r() % 3) << 28 | (uint64_t)(r() % 4 ? 0 : 37 + r() % 70) << 32;
}
uint64_t hash_key(std::mt19937_64& r) { return r() % 4 ? (r() % 900) * 0x9E3779B97F4A7C15ull ^ 0x5EED : r(); }
uint64_t slot_key(std::mt19937_64& r) { return r() % 4096; }
uint64_t dense_key(std::mt19937_64& r) { return r() % 2 ? r() % 64 : (r() % 64) << 40; }   // (the same low bits)

int main() {
    std::mt19937_64 r(2107);
    map_against_std<uint64_t>(r, texture_key, [](std::mt19937_64& g) { return g(); }, 2048, 400000);
    map_against_std<uint64_t>(r, hash_key, [](std::mt19937_64& g) { return g(); }, 1 << 30, 200000);
    map_against_std<std::pair<uint32_t, uint8_t>>(r, slot_key, [](std::mt19937_64& g) {
        return std::pair<uint32_t, uint8_t>((uint32_t)g(), (uint8_t)g());
    }, 1 << 30, 200000);
    map_against_std<uint64_t>(r, dense_key, [](std::mt19937_64& g) { return g(); }, 1 << 30, 100000);
    map_against_std<Pick>(r, hash_key, [](std::mt19937_64& g) {
        Pick p;
        p.p = (const void*)(uintptr_t)(g() % 50 * 16);
        for (int i = (int)(g() % 6); i > 0; i--) p.handles.push_back((uint32_t)g());
        return p;
    }, 600, 200000);

    // the replay's own code, over each map
    for (int step = 0; step < 300000; step++) {
        const uint64_t what = r() % 1000;
        if (what < 6) {
            versions[r() % 4096]++;
        } else if (what < 8) {
            destroy_gen++;
        } else if (what < 12) {
            epoch++;
            if (old_impl::handle_hits().size() > 1024) old_impl::handle_hits().clear();
            if (new_impl::handle_hits().size() > 1024) new_impl::handle_hits().clear();
        } else {
            const uint32_t handle = (uint32_t)(r() % 3000 + 1) | (uint32_t)(r() % 8) << 20;
            const VkImageViewType want = (VkImageViewType)(r() % 4);
            const ViewUse use = (ViewUse)(r() % 3);
            const VkFormat as = r() % 4 ? VK_FORMAT_UNDEFINED : VK_FORMAT_R32_UINT;
            Texture* ta = nullptr;
            Texture* tb = nullptr;
            uint32_t la = 7, lb = 7;
            trace.clear();
            const VkImageView va = old_impl::texture_view_of(handle, want, use, as, &ta, &la);
            const std::string sa = trace;
            trace.clear();
            const VkImageView vb = new_impl::texture_view_of(handle, want, use, as, &tb, &lb);
            if (va != vb || ta != tb || la != lb || sa != trace) {
                fprintf(stderr, "texture_view_of(%#x) differs at step %d: [%s] against [%s]\n", handle, step, sa.c_str(), trace.c_str());
                return 1;
            }
        }
    }
    if (old_impl::handle_hits().size() != new_impl::handle_hits().size()) {
        fprintf(stderr, "handle_hits holds %zu against %zu\n", old_impl::handle_hits().size(), new_impl::handle_hits().size());
        return 1;
    }
    puts("same");
}
'''


def cut(source, start, end):
    first = source.index(start)
    return source[first:source.index(end, first)]


def harness():
    draw = (VK / "vk_draw.cpp").read_text(encoding="utf-8")
    shader = (VK / "vk_shader.cpp").read_text(encoding="utf-8")
    hits = cut(draw, "struct HandleHit {", "\n// (hookshot) RX_VK_TRACE_TEX")
    tls = re.search(r"TLS_OBJECT\(handle_hits, (.+)\)\s*$", hits, re.M)
    if not tls:
        raise SystemExit("handle_hits is no longer a TLS_OBJECT: update this check")
    hits = hits[:tls.start()] + "inline %s& handle_hits() { static %s m; return m; }\n" % (tls.group(1), tls.group(1))
    view_of = cut(draw, "VkImageView texture_view_of(", "/// A uniform buffer's descriptor range")
    for name, text in (("vk_draw.cpp", draw), ("vk_shader.cpp", shader)):
        if '#include "flat_map.h"' not in text:
            raise SystemExit(f"{name} does not include flat_map.h")
    for decl in ("TLS_OBJECT(handle_hits, FlatMap<", "static thread_local FlatMap<uint64_t, PipeEntry*> mine;"):
        if decl not in draw:
            raise SystemExit(f"vk_draw.cpp: {decl} is gone")
    if "thread_local FlatMap<uint64_t, Pick> picks;" not in shader:
        raise SystemExit("vk_shader.cpp: picks is no longer a FlatMap")
    body = "VkFormat last_view_format = VK_FORMAT_UNDEFINED;\n" + hits + view_of
    old = "namespace old_impl {\ntemplate <class K, class V> using FlatMap = std::unordered_map<K, V>;\n" + body + "}\n"
    new = "namespace new_impl {\n" + body + "}\n"
    return STUBS + old + new + MAIN


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default=shutil.which("clang++") or shutil.which("g++"))
    args = parser.parse_args()
    if not args.cxx:
        print("SKIP: no C++ compiler")
        return
    with tempfile.TemporaryDirectory(prefix="hookshot-flat-map-") as tmp:
        src = Path(tmp) / "flat_map_test.cpp"
        exe = Path(tmp) / "flat_map_test.exe"
        src.write_text(harness(), encoding="utf-8")
        build = subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Wno-unused-variable", "-Wno-unused-function",
                                "-I", str(VK), str(src), "-o", str(exe)], text=True, capture_output=True)
        if build.returncode:
            raise SystemExit(build.stderr[-4000:])
        run = subprocess.run([str(exe)], text=True, capture_output=True, timeout=120)
        if run.returncode or run.stdout.strip() != "same":
            raise SystemExit(run.stderr or run.stdout or f"exit {run.returncode}")
    print("PASS: FlatMap answers as std::unordered_map did, and texture_view_of does the same over either")


if __name__ == "__main__":
    main()
