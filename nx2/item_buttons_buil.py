"""(hookshot) The game's UI layout files (the .buil files of UI/Layout2Archive/*.blarc) read into blocks and written again, with
panes added or copied, for nx2/item_buttons_layout.py.

A .buil is a "BFFH" container: a header, a table of two sections ("BFSI": Default, then StringPool), then one object graph of
type Nintendo.Ui.ResModels.LayoutResData whose root ("UIL", version 0xCE) starts the Default section. Every reference is a u64
offset from the file's start, and there is no relocation table: the game walks the graph by a fixed schema when it loads the
file (nx2/item_buttons_rules.py). So the file is read here by a schema too (Layout._root and the functions after it): each
struct or array becomes a Block, each pointer field is noted with what it points to, and write() lays the blocks out again in
their order, each at its alignment, then the string pool, and points every pointer at its target's new place.

The schema has to know every pointer. Reading checks that it does: every non-zero byte of the Default section must be in a
block, the fields the schema expects to be zero must be, each dictionary key's hash must be the key's, and the file must come
back byte for byte from write(). Anything else is a LayoutError, and the build step stops on it rather than guess.

The graph's rules: an array is {u64 offset, u32 count, u32 element size}, all zero when empty; a dictionary {u64 keys, u64
values, u64 hashes, u32 count, u32 value size}, the keys string offsets, the hashes CityHash64 of each key (in key order) and
0x20 zero bytes after them (an empty dictionary's three offsets all at those); strings NUL-terminated in the StringPool, shared
between fields. Panes are 0x44-byte records in tree order (depth first): `parent` an index, `end` the index after the pane's
last descendant, draw order index order.

A pane put in among the others moves the ones after it up an index, and with them every place that keeps a pane's index (read
in every layout of the game's: each is where its pane is): the panes' parents and ends, a Part's pane (+0x40) and the first
string of each of its string lists (that pane's index as a number: the path its overrides go by), a text box's pane (+0x8c), a
capture's (+4), an animation's part links (+0x18) and its targets' addresses (5 bytes in the pool: the pane's index in the low
4 bits of byte 1, from bit 3, and the low 5 of byte 2). Where slide lists and user data other than strings keep one is not
known: a layout with them is not renumbered.
"""
import bisect
import struct

ROOT_SIZE = 0x228
PANE_SIZE = 0x44
PART_SIZE = 0x48
TYPE_NAME = b"Nintendo.Ui.ResModels.LayoutResData"
VERSION = 0xCE
# a pane's record: four floats (zero in nearly every pane), scale x y, rotation (radians), translation x y (from the parent's
# centre, y up), alpha preset (an index into root+0x1e8), parent, size w h, end, flags, then u16 indices: drawable, text fit,
# user data, the pane's entry in its kind's dictionary (pictures, text boxes, aligns, parts, captures, slide lists); 0xffff none
PANE = struct.Struct("<3ff2ff2fIi2fII4H")
# flags: bit 0 visible, bits 3 and 4 what its bounds (an alignment pane lines its children up by theirs) take in: its own
# rect, its shown children's; bits 7-9 the kind (0 null, 1 picture, 2 text, 3 align, 4 scissor, 5 capture, 6 parts, 7 slide
# list)
VISIBLE = 1
KIND_NULL, KIND_PICTURE, KIND_TEXT, KIND_ALIGN, KIND_PARTS = 0, 1, 2, 3, 6
# the materials a text pane or a shape picture owns after its own, by their flags (material+0x60)
SUB_MATERIALS = (0xC00, 0xA00, 0x400, 0x600)
USER_STRING = 7   # (a user data entry's type, +8: a string)
NUL = b"\0"


class LayoutError(Exception):
    """a layout or archive not as this tooling knows it"""


# ---- CityHash64 (v1.1), the dictionaries' key hash. The game finds names by farmhashxo's Hash64, which is the same function
# for up to 32 bytes and another above, so longer keys are refused: a key the game could not find

_M = (1 << 64) - 1
_K0, _K1, _K2 = 0xC3A5C85C97CB3127, 0xB492B66FBE98F273, 0x9AE16A3B2F90404F


def _rotr(x, r):
    return ((x >> r) | (x << (64 - r))) & _M if r else x


def _mix(u, v, mul):
    a = ((u ^ v) * mul) & _M
    a ^= a >> 47
    b = ((v ^ a) * mul) & _M
    b ^= b >> 47
    return (b * mul) & _M


def key_hash(key):
    """CityHash64 of a key's bytes, at most 32 of them"""
    s, n = bytes(key), len(key)
    if n > 32:
        raise LayoutError(f"the name {s!r} is longer than 32 bytes: the game's hash of it is not CityHash64")

    def q(i):
        return struct.unpack_from("<Q", s, i)[0]

    mul = (_K2 + n * 2) & _M
    if n > 16:
        a, b, c, d = (q(0) * _K1) & _M, q(8), (q(n - 8) * mul) & _M, (q(n - 16) * _K2) & _M
        return _mix((_rotr((a + b) & _M, 43) + _rotr(c, 30) + d) & _M, (a + _rotr((b + _K2) & _M, 18) + c) & _M, mul)
    if n >= 8:
        a, b = (q(0) + _K2) & _M, q(n - 8)
        return _mix((_rotr(b, 37) * mul + a) & _M, ((_rotr(a, 25) + b) * mul) & _M, mul)
    if n >= 4:
        return _mix((n + (struct.unpack_from("<I", s, 0)[0] << 3)) & _M, struct.unpack_from("<I", s, n - 4)[0], mul)
    if n:
        y, z = s[0] + (s[n >> 1] << 8), n + (s[n - 1] << 2)
        v = (y * _K2 ^ z * _K0) & _M
        return ((v ^ (v >> 47)) * _K2) & _M
    return _K2


class Block:
    """a piece of the Default section: one struct, or one array of structs, values or offsets. ptrs: offset in the block ->
    (block, offset in it), ("str", offset in the string pool), or ("next", block): an offset at no data stays at the start of
    the block that followed it (None: the section's end). off is None for a block made here"""
    __slots__ = ("off", "data", "kind", "align", "ptrs", "at")

    def __init__(self, off, data, kind, align):
        self.off, self.data, self.kind, self.align = off, bytearray(data), kind, align
        self.ptrs = {}
        self.at = None

    def __repr__(self):
        return f"<{self.kind} at {self.off if self.off is None else hex(self.off)} +{len(self.data):#x}>"


class Layout:
    """a .buil read into blocks (see the module's docstring); LayoutError when it is not as the schema knows it"""

    def __init__(self, data):
        b = self.b = bytes(data)
        if len(b) < 0x100 or b[:4] != b"BFFH":
            raise LayoutError("not a BFFH file")
        size, = struct.unpack_from("<I", b, 8)
        sec, nsec, sec_size, root = struct.unpack_from("<QIIQ", b, 0x10)
        if size != len(b) or nsec != 2 or sec_size != 0x28 or b[0x28:0xA8].split(NUL)[0] != TYPE_NAME:
            raise LayoutError("the BFFH header is not a layout's")
        self.sec = sec
        found = []
        for i in range(2):
            o = sec + sec_size * i
            if b[o:o + 4] != b"BFSI":
                raise LayoutError("a section entry is not BFSI")
            off, n, align, off2 = struct.unpack_from("<IIIQ", b, o + 4)
            found.append((b[o + 0x18:o + 0x28].split(NUL)[0], off, n, align, off2))
        (n0, self.d0, dn, da, d2), (n1, self.s0, sn, sa, s2) = found
        self.d1, s1 = self.d0 + dn, self.s0 + sn
        if (n0, n1, da, sa) != (b"Default", b"StringPool", 8, 1) or d2 != self.d0 or s2 != self.s0 or \
                not (root == self.d0 and self.d1 == self.s0 and s1 == len(b)):
            raise LayoutError("the sections are not Default then StringPool, from the root to the file's end")
        self.pool = bytearray(b[self.s0:])
        self.blocks = {}       # (start offset -> Block, while reading)
        self._fields = []      # (field offset, target, "ptr" or "str"), as read
        self.curve_data = set()
        try:
            self._root()
        except (struct.error, ValueError, IndexError) as e:   # (an offset or a string past the file's end)
            raise LayoutError(f"the layout ends before its data does ({e})")
        self._resolve()
        self.pointers = {fo for fo, t, _ in self._fields if t}   # (every offset field that is not zero, in the file as read)
        if self.write() != b:
            raise LayoutError("the layout does not come back byte for byte: its schema is not the one known")

    # ---- reading ---------------------------------------------------------------------------------------------------
    def u32(self, o):
        return struct.unpack_from("<I", self.b, o)[0]

    def _claim(self, off, size, kind, align=8):
        """[off, off + size) as a block; the same range again is the same block (shared data)"""
        if size == 0:
            return None
        if not (self.d0 <= off and off + size <= self.d1):
            raise LayoutError(f"{kind}: {off:#x}+{size:#x} is outside the Default section")
        old = self.blocks.get(off)
        if old is not None:
            if len(old.data) != size:
                raise LayoutError(f"{kind}: {off:#x}+{size:#x} is already {old}")
            return old
        k = self.blocks[off] = Block(off, self.b[off:off + size], kind, align)
        return k

    def _zero(self, o, n, what):
        if any(self.b[o:o + n]):
            raise LayoutError(f"{what}: {self.b[o:o + n].hex()} where zero is expected")

    def _string(self, o):
        """a string field: its bytes, None for a null offset"""
        t = struct.unpack_from("<Q", self.b, o)[0]
        self._fields.append((o, t, "str"))
        if not t:
            return None
        if not (self.s0 <= t < len(self.b)):
            raise LayoutError(f"a string at {o:#x} is outside the string pool")
        return self.b[t:self.b.index(NUL, t)]

    def _pointer(self, o):
        t = struct.unpack_from("<Q", self.b, o)[0]
        self._fields.append((o, t, "ptr"))
        if t and not (self.d0 <= t <= self.d1):
            raise LayoutError(f"an offset at {o:#x} is outside the Default section")
        return t

    def _array(self, o, kind):
        """{offset, count, element size}: (offset, count, size); an empty one is all zero"""
        p = self._pointer(o)
        n, es = struct.unpack_from("<II", self.b, o + 8)
        if not n and (p or es):
            raise LayoutError(f"{kind}: an empty array with an offset or a size")
        return p, n, es

    def _values(self, o, kind, es_want, align=None):
        """an array of values"""
        p, n, es = self._array(o, kind)
        if n and es != es_want:
            raise LayoutError(f"{kind}: elements of {es} bytes, not {es_want}")
        self._claim(p, es * n, kind, align or (8 if es % 8 == 0 else 4 if es >= 4 else es))

    def _structs(self, o, kind, each):
        """an array of offsets to structs, each read by each()"""
        p, n, es = self._array(o, kind)
        if n and es != 8:
            raise LayoutError(f"{kind}: an array of offsets with elements of {es} bytes")
        self._claim(p, 8 * n, kind + ".offsets", 8)
        for i in range(n):
            each(self._pointer(p + 8 * i))

    def _strings(self, o, kind):
        """an array of strings"""
        p, n, es = self._array(o, kind)
        if n and es != 8:
            raise LayoutError(f"{kind}: an array of strings with elements of {es} bytes")
        self._claim(p, 8 * n, kind, 8)
        for i in range(n):
            self._string(p + 8 * i)

    def _dict(self, o, kind, each=None, run=None, align=4):
        """a dictionary: its values offsets to structs (each() reads one; run: of that size, one after another, as a block of
        their own: the panes, aligns, captures) or, with neither, values of the slot size inline"""
        keys, vals, hashes = self._pointer(o), self._pointer(o + 8), self._pointer(o + 16)
        n, es = struct.unpack_from("<II", self.b, o + 24)
        if (each or run) and es != 8:
            raise LayoutError(f"{kind}: values of {es} bytes, not offsets")
        self._claim(vals, es * n, kind + ".values", 8 if es >= 8 else 4)
        self._claim(keys, 8 * n, kind + ".keys", 8)
        self._claim(hashes, 8 * n + 0x20, kind + ".hashes", 8)
        self._zero(hashes + 8 * n, 0x20, kind + ": after the hashes")
        for i in range(n):
            key = self._string(keys + 8 * i)
            if key is None or struct.unpack_from("<Q", self.b, hashes + 8 * i)[0] != key_hash(key):
                raise LayoutError(f"{kind}: the hash of {key!r} is not CityHash64 of it")
        if each or run:
            at = [self._pointer(vals + 8 * i) for i in range(n)]
            if run and n:
                if any(at[i] != at[0] + run * i for i in range(n)):
                    raise LayoutError(f"{kind}: the values are not one run")
                self._claim(at[0], run * n, kind + "[]", align)
            for p in at if each else ():
                each(p)
        return n

    def _root(self):
        o = self.d0
        if self.b[o:o + 4] != b"UIL\0" or self.u32(o + 8) != VERSION:
            raise LayoutError(f"the root is not UIL version {VERSION:#x}")
        self._claim(o, ROOT_SIZE, "root")
        self._zero(o + 4, 4, "root+0x4")
        self._zero(o + 0xC, 0xC, "root+0xc")
        self._string(o + 0x18)
        self._dict(o + 0x20, "panes", run=PANE_SIZE)
        self._dict(o + 0x40, "drawables", self._drawable)
        self._dict(o + 0x60, "pictures", self._picture)
        self._dict(o + 0x80, "text boxes", self._textbox)
        self._dict(o + 0xA0, "aligns", run=8)
        self._dict(o + 0xC0, "parts", self._part)
        self._dict(o + 0xE0, "captures", run=0x10)
        self._dict(o + 0x100, "slide lists", self._slidelist)
        self._zero(o + 0x120, 0x10, "root+0x120")
        self._structs(o + 0x130, "materials", self._material)
        self._dict(o + 0x140, "animations", self._anim)
        self._dict(o + 0x160, "text fits", self._textfit)
        self._dict(o + 0x180, "pane user data", self._userdata_list)
        p = self._pointer(o + 0x1A0)   # (the layout's user data)
        if p:
            self._userdata_list(p)
        if self._dict(o + 0x1A8, "root+0x1a8"):
            raise LayoutError("the dictionary at root+0x1a8 is used")
        self._values(o + 0x1C8, "colours", 0x10)
        self._values(o + 0x1D8, "floats", 4)
        self._structs(o + 0x1E8, "alpha presets", lambda q: self._claim(q, 0x14, "alpha preset", 4))
        p = self._pointer(o + 0x1F8)   # (names from child parts this layout uses)
        if p:
            self._strlist(p, "part names")
        self._values(o + 0x208, "drawable words", 4)
        self._values(o + 0x218, "root+0x218", 1)

    def _strlist(self, o, kind):
        self._claim(o, 0x10, kind)
        self._strings(o, kind + " strings")

    def _drawable(self, o):
        self._claim(o, 0x40, "drawable")
        self._structs(o, "texture slots", self._texslot)
        p = self._pointer(o + 0x38)
        if p:   # (text and shape panes)
            self._claim(p, 0x30, "drawable extra")
            self._zero(p, 8, "drawable extra+0")
            for at, size in ((8, 0x10), (0x10, 0x18)):
                q = self._pointer(p + at)
                if q:
                    self._claim(q, size, f"drawable extra+{at:#x}")
            q = self._pointer(p + 0x18)
            if q:
                self._claim(q, 0x20, "drawable mask")
                self._string(q)

    def _texslot(self, o):
        self._claim(o, 0x30, "texture slot")
        self._strings(o, "texture slot names")

    def _picture(self, o):
        self._claim(o, 0x18, "picture")
        self._zero(o + 0x14, 4, "picture+0x14")
        p, q = self._pointer(o), self._pointer(o + 8)
        if p:
            self._claim(p, 0x30, "picture shape")
            c = self._pointer(p + 8)
            if c:
                self._claim(c, 0x20, "shape corners")
                for i in range(4):
                    self._claim(self._pointer(c + 8 * i), 8, "shape corner")
        if q:
            self._claim(q, 0x10, "picture+0x8")
            self._structs(q, "picture+0x8", lambda e: self._claim(e, 0x14, "picture+0x8 entry", 4))

    def _textbox(self, o):
        self._claim(o, 0xA8, "text box")
        for at in (0, 0x10, 0x18):   # (font, text, label)
            self._string(o + at)

    def _part(self, o):
        self._claim(o, PART_SIZE, "part")
        self._partref(o)
        self._zero(o + 0x44, 4, "part+0x44")

    def _partref(self, o):
        """a part's layout name, overrides, string lists, states and its 16-byte tail (a slide list's item has these too)"""
        self._string(o)
        self._structs(o + 8, "part overrides", lambda e: self._claim(e, 0x18, "part override", 4))
        self._structs(o + 0x18, "part string lists", lambda e: self._strlist(e, "part string list"))
        self._structs(o + 0x28, "part states", self._part_state)
        p = self._pointer(o + 0x38)
        if p:
            self._strlist(p, "part tail")

    def _part_state(self, o):
        self._claim(o, 0x10, "part state")
        self._string(o)

    def _slidelist(self, o):
        self._claim(o, 0x80, "slide list")
        self._string(o)
        p = self._pointer(o + 8)
        if p:
            self._claim(p, 0x40, "slide list item")
            self._partref(p)

    def _textfit(self, o):
        self._claim(o, 0x58, "text fit")
        self._strings(o, "text fit targets")
        self._strings(o + 0x10, "text fit targets 2")
        p = self._pointer(o + 0x48)
        if p:
            self._claim(p, 0x10, "text fit+0x48")

    def _userdata_list(self, o):
        self._claim(o, 0x10, "user data list")
        self._structs(o, "user data list", self._userdata)

    def _userdata(self, o):
        self._claim(o, 0x20, "user data")
        self._string(o)
        self._values(o + 0x10, "user data bytes", 1, align=8)

    def _material(self, o):
        self._claim(o, 0x88, "material")
        self._structs(o, "material textures", self._texref)
        self._structs(o + 0x10, "material+0x10", lambda e: self._claim(e, 0x34, "material+0x10 entry", 4))
        self._structs(o + 0x20, "material+0x20", self._mat_x18)
        self._structs(o + 0x30, "material texture coordinates", lambda e: self._claim(e, 0x20, "texture coordinates"))
        self._structs(o + 0x40, "material+0x40", lambda e: self._claim(e, 0xC8, "material+0x40 entry"))
        self._structs(o + 0x50, "material parameters", self._mat_params)
        self._zero(o + 0x64, 4, "material+0x64")
        self._values(o + 0x68, "material words", 4, align=8)
        self._string(o + 0x78)
        self._zero(o + 0x84, 4, "material+0x84")

    def _texref(self, o):
        self._claim(o, 0x10, "material texture")
        self._string(o + 8)

    def _mat_x18(self, o):
        self._claim(o, 0x18, "material+0x20 entry")
        self._structs(o + 8, "material+0x20 entry", lambda e: self._claim(e, 0x40, "material+0x20 record"))

    def _mat_params(self, o):
        self._claim(o, 0x30, "material parameters")
        self._values(o, "material parameter vectors", 0x10)
        self._dict(o + 0x10, "material parameter names")

    def _anim(self, o):
        self._claim(o, 0x30, "animation")
        self._zero(o + 0x2C, 4, "animation+0x2c")
        self._structs(o + 0x18, "animation part links", self._part_anim)
        p = self._pointer(o)
        if p:
            self._clip(p)
        for at in (8, 0x10):
            q = self._pointer(o + at)
            if q:
                self._claim(q, 0x28, f"animation+{at:#x}")
                self._zero(q, 0x28, f"animation+{at:#x}")

    def _part_anim(self, o):
        self._claim(o, 0x20, "animation part link")
        self._zero(o + 8, 0x10, "animation part link+0x8")
        self._string(o)

    def _clip(self, o):
        self._claim(o, 0x60, "clip")
        self._string(o)
        self._structs(o + 8, "clip targets", self._target)
        self._structs(o + 0x18, "clip curves", self._curve)
        self._values(o + 0x28, "clip curve components", 1)
        self._values(o + 0x38, "clip constants", 4)
        self._values(o + 0x48, "clip constant components", 1)

    def _target(self, o):
        """an animation target: its address (5 bytes, each below 0x80, then a NUL; zero bytes are part of it) in the pool"""
        self._claim(o, 0x20, "clip target")
        self._string(o)
        t = struct.unpack_from("<Q", self.b, o)[0]
        a = self.b[t:t + 6]
        if t and (len(a) < 6 or a[5] or any(x >= 0x80 for x in a)):
            raise LayoutError(f"an animation address at {t:#x} is {a.hex()}")
        self._strings(o + 0x10, "clip target strings")

    def _curve(self, o):
        """a curve: its key times and values, each {f32, f32, array of f32}. The game relocates the two arrays by handlers
        chosen by the curve's type, not by the walk nx2/item_buttons_rules.py repeats: their offsets are in curve_data"""
        self._claim(o, 0x18, "curve")
        for at, kind in ((0, "curve times"), (8, "curve values")):
            p = self._pointer(o + at)
            self._claim(p, 0x18, kind)
            self._values(p + 8, kind + " floats", 4)
            self.curve_data.add(p + 8)

    def _resolve(self):
        """each offset noted while reading as a link to its target block"""
        self.order = sorted(self.blocks.values(), key=lambda k: k.off)
        starts = [k.off for k in self.order]
        at = self.d0
        for k in self.order:   # (every byte not in a block is zero, and no two blocks overlap)
            if k.off < at:
                raise LayoutError(f"{k} overlaps the block before it")
            if any(self.b[at:k.off]):
                raise LayoutError(f"{at:#x}..{k.off:#x} holds bytes the schema does not know")
            at = k.off + len(k.data)
        if any(self.b[at:self.d1]):
            raise LayoutError(f"{at:#x}..{self.d1:#x} holds bytes the schema does not know")
        for fo, t, kind in self._fields:
            i = bisect.bisect_right(starts, fo) - 1
            if i < 0 or fo + 8 > self.order[i].off + len(self.order[i].data):
                raise LayoutError(f"the offset at {fo:#x} is in no block")
            src = self.order[i]
            if not t:
                continue
            if kind == "str":
                src.ptrs[fo - src.off] = ("str", t - self.s0)
                continue
            j = bisect.bisect_right(starts, t) - 1
            if j >= 0 and t < self.order[j].off + len(self.order[j].data):
                src.ptrs[fo - src.off] = (self.order[j], t - self.order[j].off)
            else:
                j = bisect.bisect_left(starts, t)
                src.ptrs[fo - src.off] = ("next", self.order[j] if j < len(self.order) else None)
        self.blocks = None
        self.root = self.order[0]

    # ---- writing ---------------------------------------------------------------------------------------------------
    def string(self, text):
        """the pool offset of a string, added when the pool does not have it"""
        enc = text.encode() + NUL
        if self.pool.startswith(enc):
            return 0
        at = self.pool.find(NUL + enc)
        if at >= 0:
            return at + 1
        self.pool += enc
        return len(self.pool) - len(enc)

    def write(self):
        """the file: the header, the blocks in order (each at its alignment), the string pool; every offset pointed at its
        target's place, the file's and the sections' sizes set"""
        at = self.d0
        for k in self.order:
            at = -(-at // k.align) * k.align
            k.at = at
            at += len(k.data)
        d1 = at
        out = bytearray(self.b[:self.d0]) + bytes(d1 - self.d0)
        for k in self.order:
            data = bytearray(k.data)
            for rel, (tgt, toff) in k.ptrs.items():
                if tgt == "str":
                    v = d1 + toff
                elif tgt == "next":
                    v = toff.at if toff is not None else d1
                else:
                    v = tgt.at + toff
                struct.pack_into("<Q", data, rel, v)
            out[k.at:k.at + len(data)] = data
        out += self.pool
        struct.pack_into("<I", out, 8, len(out))
        struct.pack_into("<IIIQ", out, self.sec + 4, self.d0, d1 - self.d0, 8, self.d0)
        struct.pack_into("<IIIQ", out, self.sec + 0x28 + 4, d1, len(self.pool), 1, d1)
        return bytes(out)

    def raw(self, data):
        """the pool offset of bytes that end in a NUL and may hold others (an animation's address), added when not there"""
        at = self.pool.find(data)
        if at >= 0:
            return at
        self.pool += data
        return len(self.pool) - len(data)

    def text(self, off):
        """the string at a pool offset"""
        return bytes(self.pool[off:self.pool.index(NUL, off)]).decode()

    # ---- panes -----------------------------------------------------------------------------------------------------
    def _dict_blocks(self, at, kind):
        """the keys, values and hashes blocks of the root's dictionary at root+at (it has entries), and its count"""
        got = []
        for i, part in enumerate(("keys", "values", "hashes")):
            link = self.root.ptrs.get(at + 8 * i)
            if not link or link[1] != 0 or not isinstance(link[0], Block) or link[0].kind != f"{kind}.{part}":
                raise LayoutError(f"the layout's {kind} are not as known (none yet?)")
            got.append(link[0])
        return got + [struct.unpack_from("<I", self.root.data, at + 24)[0]]

    def _count(self, at):
        return struct.unpack_from("<I", self.root.data, at + 24)[0]

    def _entries(self, at, kind):
        """the values of the root's dictionary at root+at, each (block, offset in it)"""
        if not self._count(at):
            return []
        _, vals, _, n = self._dict_blocks(at, kind)
        return [vals.ptrs[8 * i] for i in range(n)]

    def _add_key(self, at, kind, name, value, pos=None):
        """one more entry in the root's dictionary at root+at, at pos (None: the end): name, its hash, value (block, offset)"""
        keys, vals, hashes, n = self._dict_blocks(at, kind)
        if name in self.names(at, kind):
            raise LayoutError(f"the layout has {kind} named {name} already")
        pos = n if pos is None else pos
        for k, entry in ((keys, ("str", self.string(name))), (vals, value)):
            k.ptrs = {o + 8 if o >= 8 * pos else o: t for o, t in k.ptrs.items()}
            k.data[8 * pos:8 * pos] = bytes(8)
            k.ptrs[8 * pos] = entry
        hashes.data[8 * pos:8 * pos] = struct.pack("<Q", key_hash(name.encode()))   # (before the 0x20 zero bytes)
        struct.pack_into("<I", self.root.data, at + 24, n + 1)

    def names(self, at=0x20, kind="panes"):
        """the keys of the root's dictionary at root+at (the panes'), in order"""
        keys, _, _, n = self._dict_blocks(at, kind)
        out = []
        for i in range(n):
            tgt, toff = keys.ptrs[8 * i]
            if tgt != "str":
                raise LayoutError(f"a key of the {kind} is not a string")
            out.append(self.text(toff))
        return out

    def _panes(self):
        """the block of the pane records and their count"""
        _, vals, _, n = self._dict_blocks(0x20, "panes")
        run = vals.ptrs.get(0, (None,))[0]
        if not isinstance(run, Block) or run.kind != "panes[]" or len(run.data) != PANE_SIZE * n or \
                any(vals.ptrs.get(8 * i) != (run, PANE_SIZE * i) for i in range(n)):
            raise LayoutError("the pane records are not one run in order")
        return run, n

    def pane(self, i):
        """pane i's record as PANE's fields, by name"""
        run, n = self._panes()
        if not 0 <= i < n:
            raise LayoutError(f"no pane {i}")
        v = PANE.unpack_from(run.data, PANE_SIZE * i)
        return {"scale": v[4:6], "at": v[7:9], "alpha": v[9], "parent": v[10], "size": v[11:13], "end": v[13], "flags": v[14],
                "drawable": v[15], "text_fit": v[16], "user_data": v[17], "index": v[18]}

    @staticmethod
    def _linked(block, at):
        """the block an offset at block+at leads to the start of, None for none"""
        link = block.ptrs.get(at)
        return link[0] if link and isinstance(link[0], Block) and link[1] == 0 else None

    def _items(self, block, at):
        """the blocks the array of offsets at block+at leads to"""
        n = struct.unpack_from("<I", block.data, at + 8)[0]
        arr = self._linked(block, at) if n else None
        if n and (arr is None or len(arr.data) != 8 * n or any(self._linked(arr, 8 * k) is None for k in range(n))):
            raise LayoutError(f"the array at +{at:#x} of a {block.kind} is not as known")
        return [self._linked(arr, 8 * k) for k in range(n)]

    def _grow(self, at, kind, item, ptr=None):
        """one more element at the end of the root's array at root+at (the materials, the drawable words; it has elements): its
        index"""
        arr = self._linked(self.root, at)
        n, es = struct.unpack_from("<II", self.root.data, at + 8)
        if arr is None or arr.kind != kind or len(arr.data) != n * es or len(item) != es:
            raise LayoutError(f"the layout's {kind} are not as known")
        if ptr:
            arr.ptrs[len(arr.data)] = ptr
        arr.data += item
        struct.pack_into("<I", self.root.data, at + 8, n + 1)
        return n

    def _clone(self, block, made):
        """a copy of block and of every block it leads to (made: original -> copy, in the order made); strings stay shared"""
        if block in made:
            return made[block]
        k = made[block] = Block(None, bytes(block.data), block.kind, block.align)
        for rel, (tgt, toff) in block.ptrs.items():
            k.ptrs[rel] = (self._clone(tgt, made), toff) if isinstance(tgt, Block) else (tgt, toff)
        return k

    def _renumber(self, i, chain):
        """every pane index from i on that the layout keeps, one up, for a pane put in at i as the last child of chain[0]
        (chain: it and its ancestors, whose ends at i then take the new pane in; any other pane's end at i stays)"""
        run, n = self._panes()
        if i < n:
            if self._count(0x100):
                raise LayoutError("the layout has slide lists: where they keep pane indices is not known")
            user = self._linked(self.root, 0x1A0)
            for lst in [blk for blk, _ in self._entries(0x180, "pane user data")] + ([user] if user else []):
                if any(struct.unpack_from("<I", u.data, 8)[0] != USER_STRING for u in self._items(lst, 0)):
                    raise LayoutError("the layout has user data other than strings: whether it keeps pane indices is not known")

        def up(p):
            return p + 1 if p >= i else p
        for k in range(n):
            o = PANE_SIZE * k
            parent, = struct.unpack_from("<i", run.data, o + 0x28)
            end, = struct.unpack_from("<I", run.data, o + 0x34)
            struct.pack_into("<i", run.data, o + 0x28, up(parent))
            struct.pack_into("<I", run.data, o + 0x34, end + 1 if end > i or (end == i and k in chain) else end)
        for part, _ in self._entries(0xC0, "parts"):
            own, = struct.unpack_from("<I", part.data, 0x40)
            if own >= i:
                self._part_index(part, own, own + 1)
        for box, _ in self._entries(0x80, "text boxes"):
            struct.pack_into("<I", box.data, 0x8C, up(struct.unpack_from("<I", box.data, 0x8C)[0]))
        for cap, off in self._entries(0xE0, "captures"):
            struct.pack_into("<I", cap.data, off + 4, up(struct.unpack_from("<I", cap.data, off + 4)[0]))
        for anim, _ in self._entries(0x140, "animations"):
            for link in self._items(anim, 0x18):
                struct.pack_into("<I", link.data, 0x18, up(struct.unpack_from("<I", link.data, 0x18)[0]))
            clip = self._linked(anim, 0)
            for target in self._items(clip, 8) if clip else ():
                tgt, toff = target.ptrs[0]
                a = bytes(self.pool[toff:toff + 5])
                p = (a[2] & 0x1F) << 4 | a[1] >> 3
                if p >= i:
                    p += 1
                    if p > 0x1FF:
                        raise LayoutError(f"pane {p} is past what an animation's address holds")
                    target.ptrs[0] = ("str", self.raw(bytes((a[0], (p & 0xF) << 3 | (a[1] & 7), (a[2] & 0xE0) | p >> 4,
                                                             a[3], a[4], 0))))

    def _part_index(self, part, was, now):
        """a Part's pane from was to now, and with it the first string of each of its string lists (was, as a number)"""
        struct.pack_into("<I", part.data, 0x40, now)
        for lst in self._items(part, 0x18):
            strings = self._linked(lst, 0)
            link = strings.ptrs.get(0) if strings and struct.unpack_from("<I", lst.data, 8)[0] else None
            if not link or link[0] != "str" or self.text(link[1]) != str(was):
                raise LayoutError(f"a string list of the part at pane {was} does not start with its pane's index")
            strings.ptrs[0] = ("str", self.string(str(now)))

    def _place(self, parent):
        """room for a pane as the last child of pane parent, at its end: the indices from there on one up (_renumber), the
        parent's and its ancestors' ends past it. Its index"""
        _, n = self._panes()
        chain, p = [], parent
        while p >= 0:
            if p >= n or p in chain:
                raise LayoutError(f"pane {parent}'s ancestors are not a tree")
            chain.append(p)
            p = self.pane(p)["parent"]
        i = self.pane(parent)["end"]
        self._renumber(i, chain)
        return i

    def _put(self, i, name, rec):
        """the record rec at i (a place _place made), named name; i"""
        run, n = self._panes()
        run.data[PANE_SIZE * i:PANE_SIZE * i] = rec
        self._add_key(0x20, "panes", name, (run, 0), i)
        vals = self._dict_blocks(0x20, "panes")[1]
        for k in range(n + 1):
            vals.ptrs[8 * k] = (run, PANE_SIZE * k)
        return i

    def add_pane(self, name, parent, flags, at, size, scale, index=0):
        """a pane as the last child of pane `parent`; the panes after it move up an index (_renumber). Its index"""
        i = self._place(parent)
        return self._put(i, name, PANE.pack(0, 0, 0, 0, scale, scale, 0, at[0], at[1], 0, parent, size[0], size[1], i + 1,
                                            flags, 0xFFFF, 0xFFFF, 0xFFFF, index))

    def add_align(self, name, parent, flags, at, size, margin, align):
        """an alignment pane (flags of its kind) as the last child of pane `parent` (add_pane), and its entry in the aligns: the
        margin it leaves between the children it lines up and its own flags (bits 3-4: 0 left, 1 centred, 2 right-aligned).
        The layout has aligns already (their records one run, in order). Its index"""
        if flags >> 7 & 7 != KIND_ALIGN:
            raise LayoutError(f"{name}: flags {flags:#x} are not an alignment pane's")
        n = self._count(0xA0)
        _, vals, _, _ = self._dict_blocks(0xA0, "aligns")
        run = vals.ptrs.get(0, (None,))[0]
        if not isinstance(run, Block) or run.kind != "aligns[]" or len(run.data) != 8 * n or \
                any(vals.ptrs.get(8 * i) != (run, 8 * i) for i in range(n)):
            raise LayoutError("the layout's aligns are not one run in order")
        i = self.add_pane(name, parent, flags, at, size, 1.0, n)
        run.data += struct.pack("<fI", margin, align)
        self._add_key(0xA0, "aligns", name, (run, 8 * n))
        return i

    def _before_captures(self, blocks):
        """blocks laid out after the existing parts' (which end where the captures dictionary's begin)"""
        after = [self.root.ptrs.get(0xE0 + 8 * i) for i in range(3)]
        after = [lk[1] if lk[0] == "next" else lk[0] for lk in after if lk]
        if not after or not all(isinstance(k, Block) and k.kind.startswith("captures.") for k in after):
            raise LayoutError("the captures dictionary is not where the parts' blocks end")
        at_block = min(self.order.index(k) for k in after)
        self.order[at_block:at_block] = blocks

    def add_part(self, name, parent, flags, at, size, scale, layout):
        """a parts pane showing the layout `layout`, with no overrides and no states (add_pane), and its Part: the layout's
        name, three empty arrays, its own 16-byte tail, the pane's index; the Part goes after the existing parts' blocks"""
        index = self.add_pane(name, parent, flags, at, size, scale, self._count(0xC0))
        part, tail = Block(None, bytes(PART_SIZE), "part", 8), Block(None, bytes(0x10), "part tail", 8)
        part.ptrs[0] = ("str", self.string(layout))
        part.ptrs[0x38] = (tail, 0)
        struct.pack_into("<I", part.data, 0x40, index)
        self._before_captures([part, tail])
        self._add_key(0xC0, "parts", name, (part, 0))
        return index

    def copy_pane(self, src, name, parent, at=None, scale=None, flags=None):
        """a copy of pane src named name, as the last child of pane parent (add_pane's place): its record (at, scale, flags
        given: those instead of the original's) and copies of its own of what it shows: a picture's or a text pane's drawable
        with its materials (a text pane or a shape owns the four after its own too) and its picture or text box, a parts pane's
        Part with its overrides, string lists and states. The colours, the alpha preset and the strings stay shared. Its
        index"""
        run, _ = self._panes()
        p = self.pane(src)
        kind = p["flags"] >> 7 & 7
        dicts = {KIND_PICTURE: (0x60, "pictures"), KIND_TEXT: (0x80, "text boxes"), KIND_PARTS: (0xC0, "parts")}
        if kind not in (KIND_NULL,) + tuple(dicts) or p["text_fit"] != 0xFFFF or p["user_data"] != 0xFFFF or \
                (p["drawable"] == 0xFFFF) != (kind in (KIND_NULL, KIND_PARTS)):
            raise LayoutError(f"pane {src} is of a kind, or has a text fit or user data, that is not copied")
        rec = bytearray(run.data[PANE_SIZE * src:PANE_SIZE * (src + 1)])
        if at is not None:
            struct.pack_into("<2f", rec, 0x1C, *at)
        if scale is not None:
            struct.pack_into("<2f", rec, 0x10, scale, scale)
        if flags is not None:
            struct.pack_into("<I", rec, 0x38, flags)
        draw = self._entries(0x40, "drawables")[p["drawable"]][0] if p["drawable"] != 0xFFFF else None
        own = self._entries(*dicts[kind])[p["index"]][0] if kind in dicts else None
        i = self._place(parent)
        made = {}
        if draw is not None:
            d = self._clone(draw, made)
            mats = self._items(self.root, 0x130)
            m, = struct.unpack_from("<I", d.data, 0x14)
            mine = [mats[m]]
            while m + len(mine) < len(mats) and struct.unpack_from("<I", mats[m + len(mine)].data, 0x60)[0] in SUB_MATERIALS:
                mine.append(mats[m + len(mine)])
            first = [self._grow(0x130, "materials.offsets", bytes(8), (self._clone(x, made), 0)) for x in mine][0]
            struct.pack_into("<I", d.data, 0x14, first)
            self._grow(0x208, "drawable words", bytes(4))
            struct.pack_into("<H", rec, 0x3C, self._count(0x40))
            self._add_key(0x40, "drawables", name, (d, 0))
        if own is not None:
            k = self._clone(own, made)
            if kind == KIND_PICTURE:
                struct.pack_into("<I", k.data, 0x10, struct.unpack_from("<H", rec, 0x3C)[0])
            elif kind == KIND_TEXT:
                struct.pack_into("<II", k.data, 0x88, struct.unpack_from("<H", rec, 0x3C)[0], i)
            else:
                self._part_index(k, src if src < i else src + 1, i)
            struct.pack_into("<H", rec, 0x42, self._count(dicts[kind][0]))
            self._add_key(*dicts[kind], name, (k, 0))
        struct.pack_into("<i", rec, 0x28, parent)
        struct.pack_into("<I", rec, 0x34, i + 1)
        if kind == KIND_PARTS:
            self._before_captures(list(made.values()))
        else:
            self.order += list(made.values())
        return self._put(i, name, bytes(rec))
