"""(hookshot) What the game does with a layout archive (UI/Layout2Archive/*.blarc) when it loads it, repeated on the bytes, for
nx2/item_buttons_layout.py: the rules a generated archive has to keep. The checks (layout, builder, check_archive) return a list
of what breaks them, empty when nothing does. Addresses are the lifted ones (f_<address>).

The archive is a sead SharcArchiveRes, a SARC: "SARC", header 0x14, byte order mark 0xfeff, version 0x100; "SFAT" (header 0xc,
u16 count, u32 hash key) and its entries {u32 name hash, u32 name word (top byte: the entry's number among those of one hash,
1 for the first; low 24 bits: name offset / 4), u32 data start, u32 data end}, sorted by hash; "SFNT" (header 8) and the names;
the data, each file at a multiple of 0x10 from its start. prepareArchive_ (f_80459cc0) checks the magics, the byte order mark,
the version and the three header sizes, and that the names start before the data. A file is found (f_8034ade0) by a binary
search of the entries for its name's hash (hash * key + signed byte), then from the entry hit minus its number plus one,
forward, comparing names. The game keeps four entries of each layout, the same bytes, all numbered 1: the search returns
whichever it lands on.

When the archive is loaded its resource (f_807978c0) takes every entry in order and, for each name ending in ".buil",
relocates that file in place: f_80797c30 takes the root at file + [file+0x20], and f_8153e800 walks the whole object graph by
its fixed schema (Walk), adding the file's address to every offset that is not zero. Nothing marks what was done: two
entries on one range, or two offsets to one block that holds offsets, get the address added twice. The builder
(f_81545d60 buildPanes, f_81549620 Pane::build) then takes the panes by index (builder()). Animation curves' key arrays
are relocated by handlers chosen by the curve's type (f_815722e0), not followed here: nx2/item_buttons_buil.py knows them.
"""
import struct

import item_buttons_buil as buil

BASE = 0x7000000000   # (a stand-in for the address a file is loaded at)
KEY = 0x65


class Walk:
    """f_8153e800 and the functions it calls (f_8153e5e0 drawable, f_8153e720 picture shape, f_8153f900 part, f_81540000
    slide list, f_8153fb40 material, f_8153fec0 animation, f_815723e0 clip) on a copy of the file loaded at BASE. slots: the
    file offset of each offset relocated, and how many times"""

    def __init__(self, data):
        self.m = bytearray(data)
        self.slots = {}
        self.errors = []
        try:
            self.root(BASE + struct.unpack_from("<Q", self.m, 0x20)[0])
        except (ValueError, struct.error) as e:
            self.errors.append(str(e))

    def at(self, a, n):
        o = a - BASE
        if not (0 <= o and o + n <= len(self.m)):
            raise ValueError(f"a read at {o:#x}, outside the file")
        return o

    def i32(self, a):
        return struct.unpack_from("<i", self.m, self.at(a, 4))[0]

    def rel(self, a):
        """`if (*p) *p += base;` and the value after"""
        o = self.at(a, 8)
        v = struct.unpack_from("<Q", self.m, o)[0]
        if not v:
            return 0
        self.slots[o] = self.slots.get(o, 0) + 1
        if v >= BASE:
            self.errors.append(f"the offset at {o:#x} is reached twice: it would be relocated twice")
        elif v > len(self.m):
            self.errors.append(f"the offset at {o:#x} ({v:#x}) is past the file's end")
        struct.pack_into("<Q", self.m, o, v + BASE)
        return v + BASE

    def array(self, a):
        """{offset, i32 count, i32 element size}: the offset, then the first 8 bytes of each element"""
        p = self.rel(a)
        if not p:
            return []
        n, es = self.i32(a + 8), self.i32(a + 12)
        return [self.rel(p + i * es) for i in range(max(n, 0))]

    def dict_(self, d, each=None):
        k, v = self.rel(d), self.rel(d + 8)
        self.rel(d + 0x10)
        n, es = self.i32(d + 0x18), self.i32(d + 0x1C)
        for i in range(max(n, 0) if k else 0):
            self.rel(k + 8 * i)
        for i in range(max(n, 0) if v else 0):
            p = self.rel(v + i * es)
            if each and p:
                each(p)

    def strlist(self, a):
        p = self.rel(a)
        if p:
            self.array(p)

    def drawable(self, p):
        for e in self.array(p):
            if e:
                self.array(e)
        q = self.rel(p + 0x38)
        if q:
            self.rel(q), self.rel(q + 8), self.rel(q + 0x10)
            s = self.rel(q + 0x18)
            if s:
                self.rel(s)

    def picture(self, p):
        s = self.rel(p)
        if s:
            c = self.rel(s + 8)
            if c:
                for k in range(4):
                    self.rel(c + 8 * k)
            self.rel(s + 0x10), self.rel(s + 0x18)
            t = self.rel(s + 0x20)
            if t:
                for k in (8, 0x10, 0x18, 0x20):
                    self.rel(t + k)
            self.rel(s + 0x28)
        b = self.rel(p + 8)
        if b:
            self.array(b)

    def textbox(self, p):
        for k in (0, 0x10, 0x18, 0xA0):
            self.rel(p + k)

    def part(self, p):
        self.rel(p)
        self.array(p + 8)
        for e in self.array(p + 0x18):
            if e:
                self.array(e)
        for e in self.array(p + 0x28):
            if e:
                self.rel(e)
        self.strlist(p + 0x38)

    def slidelist(self, p):
        self.rel(p)
        for k in (8, 0x10, 0x18, 0x20):
            q = self.rel(p + k)
            if q:
                self.part(q)

    def material(self, p):
        for e in self.array(p):
            if e:
                self.rel(e + 8)
        self.array(p + 0x10)
        for e in self.array(p + 0x20):
            if e:
                self.array(e + 8)
        self.array(p + 0x30)
        self.array(p + 0x40)
        for e in self.array(p + 0x50):
            if e:
                self.rel(e)
                x = self.rel(e + 0x10)
                self.rel(e + 0x18), self.rel(e + 0x20)
                for j in range(max(self.i32(e + 0x28), 0) if x else 0):
                    self.rel(x + 8 * j)
        self.rel(p + 0x68), self.rel(p + 0x78)

    def clip(self, p):
        self.rel(p)
        for t in self.array(p + 8):
            if t:
                self.rel(t)
                self.array(t + 0x10)
        for c in self.array(p + 0x18):
            if c:   # (f_815722e0: the two offsets; what they point at goes by the curve's type)
                self.rel(c), self.rel(c + 8)
        self.rel(p + 0x28), self.rel(p + 0x38), self.rel(p + 0x48)

    def anim(self, p):
        c = self.rel(p)
        if c:
            self.clip(c)
        for k in (8, 0x10):
            q = self.rel(p + k)
            if q:
                self.rel(q), self.rel(q + 0x10)
        for e in self.array(p + 0x18):
            if e:
                self.rel(e), self.rel(e + 8)

    def textfit(self, p):
        self.array(p)
        self.array(p + 0x10)
        self.rel(p + 0x38), self.rel(p + 0x48)

    def userdata(self, p):
        for e in self.array(p):
            if e:
                self.rel(e), self.rel(e + 0x10)

    def root(self, r):
        self.rel(r + 0x18)
        self.dict_(r + 0x20)   # (the pane records hold no offsets)
        self.dict_(r + 0x40, self.drawable)
        self.dict_(r + 0x60, self.picture)
        self.dict_(r + 0x80, self.textbox)
        self.dict_(r + 0xA0)
        self.dict_(r + 0xC0, self.part)
        self.dict_(r + 0xE0)
        self.dict_(r + 0x100, self.slidelist)
        for e in self.array(r + 0x120):
            if e:
                self.strlist(e)
                self.rel(e + 8)
        for m in self.array(r + 0x130):
            if m:
                self.material(m)
        self.dict_(r + 0x140, self.anim)
        self.dict_(r + 0x160, self.textfit)
        self.dict_(r + 0x180, self.userdata)
        u = self.rel(r + 0x1A0)
        if u:
            self.userdata(u)
        self.dict_(r + 0x1A8, self.userdata)
        self.rel(r + 0x1C8), self.rel(r + 0x1D8)
        self.array(r + 0x1E8)
        self.strlist(r + 0x1F8)
        self.rel(r + 0x208), self.rel(r + 0x218)


def builder(data):
    """the builder's reads (f_81545d60, f_81549620, the counts f_8150f7f0 sizes the objects by) that a file can break"""
    out = []
    u16, u32, i32, u64 = (lambda o: struct.unpack_from("<H", data, o)[0]), (lambda o: struct.unpack_from("<I", data, o)[0]), \
        (lambda o: struct.unpack_from("<i", data, o)[0]), (lambda o: struct.unpack_from("<Q", data, o)[0])
    r = u64(0x20)
    count = {name: i32(r + at + 0x18) for name, at in (("panes", 0x20), ("drawables", 0x40), ("pictures", 0x60),
             ("text boxes", 0x80), ("aligns", 0xA0), ("parts", 0xC0), ("captures", 0xE0), ("slide lists", 0x100),
             ("animations", 0x140), ("text fits", 0x160), ("pane user data", 0x180))}
    alphas = i32(r + 0x1E8 + 8) if u64(r + 0x1E8) else 0
    n = count["panes"]
    if not 0 < n <= 0xFFFF:
        return [f"{n} panes: the instance keeps the count in 16 bits, and pane 0 is the root"]
    recs = [u64(u64(r + 0x28) + 8 * i) for i in range(n)]
    parent = [i32(p + 0x28) for p in recs]
    end = [u32(p + 0x34) for p in recs]
    # the tree is parent and end alone: the panes after i up to its end are exactly i's descendants
    below = [set() for _ in range(n)]
    for i in range(n):
        p, seen = parent[i], 0
        if (i == 0) != (p == -1) or not -1 <= p < i:
            out.append(f"pane {i}: parent {p} (the root's is -1, every other pane's an earlier pane)")
            continue
        while p >= 0 and seen <= n:
            below[p].add(i)
            p, seen = parent[p], seen + 1
    for i in range(n):
        if not (i < end[i] <= n) or below[i] != set(range(i + 1, end[i])):
            out.append(f"pane {i}: end {end[i]} is not the end of its descendants")
    kind_dict = {1: "pictures", 2: "text boxes", 3: "aligns", 5: "captures", 6: "parts", 7: "slide lists"}
    for i, p in enumerate(recs):
        flags = u32(p + 0x38)
        fields = [flags >> b & 7 for b in (11, 14, 17, 20)]
        if not (1 <= fields[0] <= 3 and 4 <= fields[1] <= 6 and 1 <= fields[2] <= 3 and 4 <= fields[3] <= 6):
            out.append(f"pane {i}: flags {flags:#x}: the builder aborts on bits 11-22 outside 1..3, 4..6, 1..3, 4..6")
        if u32(p + 0x24) >= alphas:
            out.append(f"pane {i}: alpha preset {u32(p + 0x24)} of {alphas}")
        for at, name in ((0x3C, "drawables"), (0x3E, "text fits"), (0x40, "pane user data")):
            if u16(p + at) != 0xFFFF and u16(p + at) >= count[name]:
                out.append(f"pane {i}: {name} index {u16(p + at)} of {count[name]}")
        kind = flags >> 7 & 7
        if kind in kind_dict and u16(p + 0x42) >= count[kind_dict[kind]]:
            out.append(f"pane {i}: index {u16(p + 0x42)} of {count[kind_dict[kind]]} {kind_dict[kind]}")
    # (each record that keeps a pane's index names a pane of its kind whose entry it is; a Part's string lists start with that
    # index as a number; a drawable is one pane's, its picture's or text box's, with a material)
    of_kind = {}
    for i, p in enumerate(recs):
        of_kind.setdefault((u32(p + 0x38) >> 7 & 7, u16(p + 0x42)), []).append(i)
    drawn = [u16(p + 0x3C) for p in recs if u16(p + 0x3C) != 0xFFFF]
    if len(set(drawn)) != len(drawn) or sorted(drawn) != list(range(count["drawables"])):
        out.append(f"the panes' drawables are not one each of {count['drawables']}")
    if (i32(r + 0x208 + 8) if u64(r + 0x208) else 0) != count["drawables"]:
        out.append("the drawable words are not one a drawable")
    materials = i32(r + 0x130 + 8) if u64(r + 0x130) else 0
    for j in range(max(count["drawables"], 0)):
        if u32(u64(u64(r + 0x48) + 8 * j) + 0x14) >= materials:
            out.append(f"drawable {j}: material {u32(u64(u64(r + 0x48) + 8 * j) + 0x14)} of {materials}")
    for name, at, kind, field, draw in (("pictures", 0x60, 1, None, 0x10), ("text boxes", 0x80, 2, 0x8C, 0x88),
                                        ("captures", 0xE0, 5, 4, None), ("parts", 0xC0, buil.KIND_PARTS, 0x40, None)):
        for j in range(max(count[name], 0)):
            rec = u64(u64(r + at + 8) + 8 * j)
            panes = of_kind.get((kind, j), [])
            if len(panes) != 1 or (field is not None and u32(rec + field) != panes[0]):
                out.append(f"{name} {j}: names pane {u32(rec + field) if field is not None else '-'}, its pane is {panes}")
            elif draw is not None and u32(rec + draw) != u16(recs[panes[0]] + 0x3C):
                out.append(f"{name} {j}: drawable {u32(rec + draw)}, its pane's {u16(recs[panes[0]] + 0x3C)}")
            elif kind == buil.KIND_PARTS:
                lists, nl = u64(rec + 0x18), i32(rec + 0x20)
                for k in range(max(nl, 0)):
                    lst = u64(lists + 8 * k)
                    first = u64(u64(lst)) if i32(lst + 8) > 0 else 0
                    if not first or bytes(data[first:data.index(0, first)]) != str(panes[0]).encode():
                        out.append(f"parts {j}: a string list does not start with its pane's index {panes[0]}")
    for j in range(max(count["animations"], 0)):   # (an animation's targets and part links address panes there are)
        anim = u64(u64(r + 0x148) + 8 * j)
        clip = u64(anim)
        for k in range(max(i32(clip + 0x10), 0) if clip else 0):
            a = data[u64(u64(u64(clip + 8) + 8 * k)):][:5]
            if ((a[2] & 0x1F) << 4 | a[1] >> 3) >= n:
                out.append(f"animation {j}: a target's pane {(a[2] & 0x1F) << 4 | a[1] >> 3} of {n}")
        links = u64(anim + 0x18)
        for k in range(max(i32(anim + 0x20), 0) if links else 0):
            pane = u32(u64(links + 8 * k) + 0x18)
            if pane >= n or u32(recs[pane] + 0x38) >> 7 & 7 != buil.KIND_PARTS:
                out.append(f"animation {j}: a part link's pane {pane} is not a parts pane")
    for name, at in (("panes", 0x20), ("drawables", 0x40), ("pictures", 0x60), ("text boxes", 0x80), ("aligns", 0xA0),
                     ("parts", 0xC0), ("captures", 0xE0), ("slide lists", 0x100), ("animations", 0x140),
                     ("text fits", 0x160), ("pane user data", 0x180)):   # (names are found by hash, then compared)
        keys, hashes, seen = u64(r + at), u64(r + at + 0x10), set()
        for i in range(max(count[name], 0)):
            s = u64(keys + 8 * i)
            key = bytes(data[s:data.index(0, s)])
            try:
                if buil.key_hash(key) != u64(hashes + 8 * i):
                    out.append(f"{name} {key!r}: the hash beside it is not its own")
            except buil.LayoutError as e:
                out.append(str(e))
            if key in seen:
                out.append(f"{name} {key!r}: twice (the second could not be found)")
            seen.add(key)
    return out


def shape(data):
    """what a layout's panes are and what its animations drive, by name (indices aside): {"panes": {name: (its parent's name,
    the record but its parent and end)}, "targets": [(animation, pane, the address but the pane)], "links": [(animation, the
    part's animation, pane)]}: a pane put in among the others changes none of it for the panes that were there"""
    u32, i32, u64 = (lambda o: struct.unpack_from("<I", data, o)[0]), (lambda o: struct.unpack_from("<i", data, o)[0]), \
        (lambda o: struct.unpack_from("<Q", data, o)[0])

    def text(o):
        return bytes(data[o:data.index(0, o)]).decode("utf-8", "replace")
    r = u64(0x20)
    n = i32(r + 0x38)
    names = [text(u64(u64(r + 0x20) + 8 * i)) for i in range(n)]
    recs = [u64(u64(r + 0x28) + 8 * i) for i in range(n)]
    out = {"panes": {}, "targets": [], "links": []}
    for i, p in enumerate(recs):
        rec = bytearray(data[p:p + buil.PANE_SIZE])
        rec[0x28:0x2C], rec[0x34:0x38] = bytes(4), bytes(4)
        out["panes"][names[i]] = (names[i32(p + 0x28)] if i32(p + 0x28) >= 0 else None, bytes(rec))
    for j in range(i32(r + 0x158)):
        anim = u64(u64(r + 0x148) + 8 * j)
        clip = u64(anim)
        name = text(u64(clip)) if clip else str(j)
        for k in range(i32(clip + 0x10) if clip else 0):
            a = data[u64(u64(u64(clip + 8) + 8 * k)):][:5]
            pane = (a[2] & 0x1F) << 4 | a[1] >> 3
            out["targets"].append((name, names[pane] if pane < n else pane, a[0], a[1] & 7, a[2] >> 5, a[3], a[4]))
        for k in range(i32(anim + 0x20) if u64(anim + 0x18) else 0):
            link = u64(u64(anim + 0x18) + 8 * k)
            out["links"].append((name, text(u64(link)), names[u32(link + 0x18)] if u32(link + 0x18) < n else u32(link + 0x18)))
    out["targets"].sort(key=str)
    out["links"].sort(key=str)
    return out


def layout(data):
    """the game's relocation of a .buil (every offset once, inside the file), checked against nx2/item_buttons_buil.py's
    reading of it (the two were worked out each on its own: the offsets the game relocates have to be the ones the schema
    knows, curve data aside), then builder()"""
    w = Walk(data)
    out = w.errors + [f"the offset at {o:#x} is relocated {n} times" for o, n in sorted(w.slots.items()) if n > 1]
    if out:
        return out
    try:
        known = buil.Layout(data)
    except buil.LayoutError as e:
        return [str(e)]
    slots = set(w.slots)
    out += [f"the offset at {o:#x} is relocated by the game but not known as one" for o in sorted(slots - known.pointers)]
    out += [f"the offset at {o:#x} is not relocated by the game" for o in sorted(known.pointers - slots - known.curve_data)]
    return out + builder(data)


def archive(b):
    """prepareArchive_'s checks, then the table: {"size", "data", "key", "nodes", "names", "entries": [(hash, name word, start,
    end)]}; ValueError when they fail"""
    if len(b) < 0x20 or b[:4] != b"SARC":
        raise ValueError("not a SARC")
    hl, bom, size, data, ver = struct.unpack_from("<HHIIH", b, 4)
    if bom != 0xFEFF or ver != 0x100 or hl != 0x14:
        raise ValueError("the SARC header is not version 0x100, little endian")
    if b[hl:hl + 4] != b"SFAT" or struct.unpack_from("<H", b, hl + 4)[0] != 0xC:
        raise ValueError("no SFAT")
    n, key = struct.unpack_from("<HI", b, hl + 6)
    nodes = hl + 0xC
    sfnt = nodes + 0x10 * n
    if b[sfnt:sfnt + 4] != b"SFNT" or struct.unpack_from("<H", b, sfnt + 4)[0] != 8 or sfnt + 8 > data or data > len(b):
        raise ValueError("no SFNT before the data")
    return {"size": size, "data": data, "key": key, "nodes": nodes, "sfnt": sfnt, "names": sfnt + 8,
            "entries": [struct.unpack_from("<IIII", b, nodes + 0x10 * i) for i in range(n)]}


def name_of(b, s, word):
    o = s["names"] + (word & 0xFFFFFF) * 4
    if not word or o >= s["data"] or b.find(0, o, s["data"]) < 0:
        return None
    return bytes(b[o:b.index(0, o)]).decode("utf-8", "replace")


def name_hash(name, key=KEY):
    h = 0
    for c in name.encode():
        h = (h * key + (c if c < 0x80 else c - 0x100)) & 0xFFFFFFFF
    return h


def lookup(b, s, name):
    """f_8034ade0: the entry the game opens for a name, -1 none"""
    ents = s["entries"]
    n, h = len(ents), name_hash(name, s["key"])
    if not n:
        return -1
    lo, hi, mid = 0, n, n // 2
    while ents[mid][0] != h:
        if ents[mid][0] < h:
            if lo == mid:
                return -1
            lo = mid
        else:
            if hi == mid:
                return -1
            hi = mid
        mid = (lo + hi) // 2
    word = ents[mid][1]
    if not word:
        return mid
    i = mid - (word >> 24) + 1
    while 0 <= i < n and ents[i][0] == h:
        if name_of(b, s, ents[i][1]) == name:
            return i
        i += 1
    return -1


def check_archive(b):
    """the archive as the game loads it: the header, the table, each entry's range, the relocation of each .buil entry
    (layout()), and the lookup of every name finding one of its own entries"""
    try:
        s = archive(b)
    except ValueError as e:
        return [str(e)]
    out, ents, data = [], s["entries"], s["data"]
    names = [name_of(b, s, w) for _h, w, _st, _en in ents]
    if s["size"] != len(b) or data % 0x10:
        out.append("the archive's size field or its data's alignment is not as the game's")
    for i, (h, w, st, en) in enumerate(ents):
        if names[i] is None or w >> 24 != 1 or name_hash(names[i], s["key"]) != h:
            out.append(f"entry {i} ({names[i]}): its name, its number or its hash is not as the game's")
        if i and ents[i - 1][0] > h:
            out.append(f"entry {i} ({names[i]}): not in hash order (the search would miss names)")
        if not (st <= en and data + en <= len(b)) or st % 0x10:
            out.append(f"entry {i} ({names[i]}): its range {st:#x}..{en:#x} is not a file's")
    spans = sorted((st, en, i) for i, (_h, _w, st, en) in enumerate(ents) if en > st)
    for (a0, a1, i), (b0, _b1, j) in zip(spans, spans[1:]):
        if b0 < a1:
            out.append(f"entries {i} ({names[i]}) and {j} ({names[j]}) share bytes: each is relocated on its own")
    done = {}
    for i, (_h, _w, st, en) in enumerate(ents):
        if (names[i] or "").endswith(".buil"):
            if st in done:
                continue   # (shared bytes, said above)
            done[st] = i
            out += [f"entry {i} ({names[i]}): {e}" for e in layout(bytes(b[data + st:data + en]))[:4]]
    for nm in sorted(set(names) - {None}):
        i = lookup(b, s, nm)
        if i < 0 or names[i] != nm:
            out.append(f"{nm}: the game's lookup does not find it")
    return out
