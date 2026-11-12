#pragma once
#include <cstddef>
#include <cstdint>
#include <utility>
#include <vector>

/// An integer key's value, kept in one array: open addressing, linear probing, at most 3/4 full, the slot from a
/// multiplicative hash. For the replay's per-thread caches, searched on every draw: std::unordered_map divided by a prime
/// and followed a node pointer per lookup. No erase of one key (those caches are only cleared whole). A clear keeps a small
/// array and gives a large one back. An insert can move every entry: no reference or pointer is held across one.
template <class K, class V>
class FlatMap {
public:
    struct Slot {
        K first{};
        bool used = false;
        V second{};
    };

    Slot* find(K key) {
        if (!count_) return nullptr;
        for (size_t i = index(key);; i = (i + 1) & mask_) {
            Slot& s = slots_[i];
            if (!s.used) return nullptr;
            if (s.first == key) return &s;
        }
    }
    Slot* end() const { return nullptr; }

    V& operator[](K key) {
        if (Slot* s = find(key)) return s->second;
        if ((count_ + 1) * 4 > slots_.size() * 3) grow();
        return place(key).second;
    }

    size_t size() const { return count_; }

    void clear() {
        if (!count_) return;
        count_ = 0;
        if (slots_.size() > kKeptSlots) {   // (a cache cleared at its size limit: its memory goes back too)
            std::vector<Slot>().swap(slots_);
            mask_ = 0, shift_ = 64;
            return;
        }
        for (Slot& s : slots_)
            if (s.used) s = Slot{};
    }

private:
    static constexpr size_t kKeptSlots = 4096;

    size_t index(K key) const { return (size_t)((uint64_t)key * 0x9E3779B97F4A7C15ull >> shift_); }

    Slot& place(K key) {
        size_t i = index(key);
        while (slots_[i].used) i = (i + 1) & mask_;
        Slot& s = slots_[i];
        s.first = key, s.used = true;
        count_++;
        return s;
    }

    void grow() {
        std::vector<Slot> old(slots_.empty() ? 16 : slots_.size() * 2);
        old.swap(slots_);
        mask_ = slots_.size() - 1;
        shift_ = 64;
        for (size_t n = slots_.size(); n > 1; n >>= 1) shift_--;
        count_ = 0;
        for (Slot& s : old)
            if (s.used) place(s.first).second = std::move(s.second);
    }

    std::vector<Slot> slots_;
    size_t count_ = 0, mask_ = 0;
    unsigned shift_ = 64;
};
