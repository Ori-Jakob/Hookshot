"""The item buttons' items with each save (host/oot_item_buttons.c, host/nn_fs.c): a save:/slot_NN/item_buttons.ini per
save folder, read when the game loads that slot, checked against the save in play, written only when the game saves.

The pure parts are cut out and compiled alone with the header's constants:
- the slot of a guest path: exactly save:/slot_NN/progress.sav (two digits) gives NN, every other path none (another
  file of the slot, another mount, a third digit, a path below it, a different case);
- an age's items kept where the walk found them valid, the others emptied and their buttons told, empty buttons and
  items out of the game's range handled;
- the new game: play with the title come up and no load since (none yet, or one before the title), not after a load
  from the title nor without a title.
Write-or-remove of the file is tests/test_item_buttons_ini.py's.

The rest is read as text:
- nn_fs.c's OpenFile tells the file opened, its path and whether for writing, once, after the open succeeded and its
  handle keeps the path, before it returns;
- that call reads a slot's file at a load and writes it at a save, through the save mount's folder, only once the hooks
  have run; the file is written nowhere else (an assignment changes the items in memory only, and asks for an age's items
  only once that age is checked);
- an age's items are answered only once checked for the last load; the check walks the pouch with the game's own calls
  (the quick-switch's test, the Magic Beans' exception found by the game's name for them), is dropped when a load came
  during it, and runs only with the feature on; a new game is seen with it off too; the title screen is the game's.
python -I -B tests/test_item_buttons_saves.py [--cc gcc]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    while text[end] in ";\n":
        end += 1
        if text[end - 1] == "\n":
            break
    return text[start:end]


def function(text, name):
    """a C function's body by its name (the line that defines it to its closing brace)"""
    m = re.search(r"^[^\n;]*\b%s\([^;{]*\)\s*\{" % re.escape(name), text, re.M)
    if not m:
        raise SystemExit("FAIL: no function %s" % name)
    return block(text, m.group(0))


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


FIXTURE = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
%s
%s
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %%d: %%s\n", __LINE__, #c); fails++; } } while (0)
int main(void) {
    /* the slot: exactly save:/slot_NN/progress.sav */
    CHECK(ib_slot_of("save:/slot_00/progress.sav") == 0);
    CHECK(ib_slot_of("save:/slot_03/progress.sav") == 3);
    CHECK(ib_slot_of("save:/slot_11/progress.sav") == 11);
    CHECK(ib_slot_of("save:/slot_99/progress.sav") == 99);
    static const char *const others[] = {
        "", "save:", "save:/slot_", "save:/slot_0", "save:/slot_03", "save:/slot_03/", "save:/slot_3/progress.sav",
        "save:/slot_003/progress.sav", "save:/slot_0a/progress.sav", "save:/slot_-1/progress.sav",
        "save:/slot_03/caption.sav", "save:/slot_03/item_buttons.ini", "save:/slot_03/progress.sav.tmp",
        "save:/slot_03/progress.savx", "save:/slot_03/progress.sa", "save:/slot_03/Progress.sav",
        "save:/SLOT_03/progress.sav", "save:/slot_03//progress.sav", "save://slot_03/progress.sav",
        "save:slot_03/progress.sav", "savt:/slot_03/progress.sav", "rom:/slot_03/progress.sav", "save:/option.sav",
        "save:/account.sav", "save:/x/slot_03/progress.sav", "save:/slot_03/progress.sav/item_buttons.ini",
        " save:/slot_03/progress.sav", "savt:/TemporaryGame.sav"};
    for (size_t i = 0; i < sizeof others / sizeof *others; i++)
        if (ib_slot_of(others[i]) != -1) printf("FAIL: \"%%s\" taken for a slot's progress.sav\n", others[i]), fails++;

    /* the valid kept, the others emptied and their buttons told */
    int items[IB_BUTTONS] = {3, IB_NONE, 30, 13};
    CHECK(ib_keep_valid(items, 1ULL << 3 | 1ULL << 13 | 1ULL << 7) == 1u << IB_X);
    CHECK(items[IB_A] == 3 && items[IB_B] == IB_NONE && items[IB_X] == IB_NONE && items[IB_Y] == 13);
    CHECK(ib_keep_valid(items, 1ULL << 3 | 1ULL << 13) == 0 && items[IB_A] == 3 && items[IB_Y] == 13);   /* again: none */
    /* nothing valid (a pouch with nothing in it for that age): all emptied */
    CHECK(ib_keep_valid(items, 0) == (1u << IB_A | 1u << IB_Y));
    for (int k = 0; k < IB_BUTTONS; k++) CHECK(items[k] == IB_NONE);
    /* all valid: kept as they are, the game's last item too */
    int all[IB_BUTTONS] = {0, IB_ITEMS - 1, IB_NONE, 46};
    CHECK(ib_keep_valid(all, ~0ULL) == 0 && all[0] == 0 && all[1] == IB_ITEMS - 1 && all[2] == IB_NONE && all[3] == 46);
    /* out of the game's range: emptied, whatever valid says */
    int odd[IB_BUTTONS] = {IB_ITEMS, 63, -5, 2};
    CHECK(ib_keep_valid(odd, ~0ULL) == (1u << IB_A | 1u << IB_B | 1u << IB_X));
    CHECK(odd[0] == IB_NONE && odd[1] == IB_NONE && odd[2] == IB_NONE && odd[3] == 2);
    /* empty buttons are none emptied */
    int empty[IB_BUTTONS] = {IB_NONE, IB_NONE, IB_NONE, IB_NONE};
    CHECK(ib_keep_valid(empty, 0) == 0);

    /* the new game: play with the title come up since it last ran, and no load since */
    CHECK(ib_new_game(1, 2000, 0) == 1);      /* no load yet */
    CHECK(ib_new_game(1, 2000, 1500) == 1);   /* the last load before the title (back to the title, then New Game) */
    CHECK(ib_new_game(1, 2000, 2500) == 0);   /* a load from the title */
    CHECK(ib_new_game(1, 2000, 2000) == 0);
    CHECK(ib_new_game(0, 2000, 0) == 0);      /* no title since play last ran (a pause menu, a load from it) */
    CHECK(ib_new_game(0, 2000, 1500) == 0);

    if (!fails) printf("PASS: the slot of a save's progress.sav, the valid items kept, the new game\n");
    return fails != 0;
}
"""


def pure_parts(core, head, cc, tmp):
    """the slot, the valid kept, the new game: compiled alone"""
    parts = [function(core, name) for name in ("ib_slot_of", "ib_keep_valid", "ib_new_game")]
    for part in parts:
        for guest in ("ib_peek", "GP(", "ib_guest", "recomp_", "hos_", "ib_lock", "__atomic"):
            check(guest not in part, "a part checked alone reaches into the game or the shared state (%s)" % guest)
    constants = "\n".join([block(head, "enum { IB_A"), block(head, "enum { IB_ADULT")] +
                          [line for line in head.splitlines() if line.startswith(("#define IB_NONE", "#define IB_ITEMS"))])
    c, exe = Path(tmp) / "saves.c", Path(tmp) / "saves.exe"
    c.write_text(FIXTURE % (constants, "\n".join(parts)), encoding="utf-8")
    subprocess.run([cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
    r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    print(r.stdout, end="")
    if r.returncode:
        raise SystemExit("test_item_buttons_saves: the pure parts failed")


def open_file(fs):
    """nn_fs.c's OpenFile tells each file opened, after the open succeeded"""
    hle = block(fs, "HLE(_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci)")
    call = "hos_oot_ib_save_file(fh->path, want_write);"
    check(hle.count(call) == 1 and fs.count("hos_oot_ib_save_file(") == 2,
          "nn_fs.c does not tell the item buttons each file opened, once, from OpenFile")
    check("int want_write = (ARG(2) & 6) != 0;" in hle, "OpenFile's write test is not the mode's write or append bit")
    failed = hle.index("if (h == INVALID_HANDLE_VALUE) {")
    failed_end = hle.index("return;", failed)
    kept = hle.index('snprintf(fh->path, sizeof fh->path, "%s", g);')
    handle = hle.index("G64(ARG(0)) = new_handle(fh);")
    at = hle.index(call)
    check(failed_end < kept < at and handle < at < hle.rindex("RET(0);"),
          "OpenFile tells the item buttons before the open succeeded, before its handle keeps the path, or after it returns")
    own = re.search(r"\n    \{ void hos_oot_ib_save_file\(const char \*guest, int write\);[^\n]*\n\s*" + re.escape(call) + r" \}",
                    hle)
    before = hle[:own.start()].rstrip().splitlines()[-1].split("/*")[0].rstrip() if own else ""
    check(own and before.endswith((";", "}")), "OpenFile's call is not a statement of its own (under the trace's if, say)")


def game_side(core):
    """the loads, the saves, the check and the new game, read as text"""
    observer = function(core, "hos_oot_ib_save_file")
    check(re.search(r"^void hos_oot_ib_save_file\(const char \*guest, int write\) \{", core, re.M),
          "hos_oot_ib_save_file is not what nn_fs.c declares")
    check("const int slot = ib_slot_of(guest);" in observer and "__atomic_load_n(&ib_hooked," in observer and
          "ib_save_slot(slot, path);" in observer and "else ib_load_slot(slot, path);" in observer,
          "a slot's progress.sav opened is not a load (read) or a save (written) of that slot, once the hooks have run")
    check("ib_enabled" not in observer, "a save does not carry the items with the feature off")
    path = function(core, "ib_slot_path")
    check('"save:/slot_%02d/item_buttons.ini"' in path and "hos_fs_host_path(guest, out, cap)" in path and
          "if (*p == '\\\\') *p = '/';" in path, "a slot's file is not save:/slot_NN/item_buttons.ini through the save mount, "
          "with / for fopen")
    check("hos_user_dir" not in core and "ib_path" not in core, "the one file of before, in the user folder, is still there")
    check(core.count("ib_ini_write(") == 2 and "ib_ini_write(path, ib_names, items)" in function(core, "ib_save_slot"),
          "the file is written somewhere else than at a save")
    check(core.count("ib_ini_read(") == 2 and "ib_ini_read(path, ib_names, items)" in function(core, "ib_load_slot"),
          "the file is read somewhere else than at a load")
    load = function(core, "ib_load_slot")
    check(re.search(r"AcquireSRWLockExclusive\(&ib_lock\);\s*memcpy\(ib_items, items, sizeof ib_items\);\s*"
                    r"__atomic_add_fetch\(&ib_load_gen, 1,", load) and "__atomic_store_n(&ib_load_ns, now," in load,
          "a load does not put its items in under the lock with a new load generation, or stamp its time")
    save = function(core, "ib_save_slot")
    check(re.search(r"AcquireSRWLockShared\(&ib_lock\);\s*memcpy\(items, ib_items, sizeof items\);\s*"
                    r"ReleaseSRWLockShared\(&ib_lock\);", save) and save.index("ReleaseSRWLockShared") < save.index("ib_ini_write"),
          "a save does not copy the items under the lock and write them after it")
    for name in ("ib_load_slot", "ib_save_slot"):
        body = function(core, name)
        check("hos_vcore_away()" in body and "hos_vcore_back()" in body, "%s holds the virtual core over its file" % name)
    put = function(core, "ib_put")
    for io in ("ib_ini_write", "ib_save_slot", "fopen", "remove(", "hos_vcore_away"):
        check(io not in put, "an assignment writes to disk (%s)" % io)
    check("__atomic_load_n(&ib_checked[age], __ATOMIC_ACQUIRE) == __atomic_load_n(&ib_load_gen, __ATOMIC_ACQUIRE)" in put,
          "an assignment changes an age's items before they are checked")
    answer = function(core, "ib_assignment")
    check("__atomic_load_n(&ib_checked[age], __ATOMIC_RELAXED) == __atomic_load_n(&ib_load_gen, __ATOMIC_RELAXED)" in answer
          and "checked ? ib_items[age][button] : IB_NONE" in answer and "AcquireSRWLockShared(&ib_lock);" in answer,
          "an age's items are answered before they are checked for the last load")
    walk = function(core, "ib_valid_items")
    calls = dict(re.findall(r"#define (IB_[A-Z_]+) (0x[0-9a-f]+)ULL", core))
    for name, address in (("IB_POUCH_ARRAY", "0x80a8f690"), ("IB_ARRAY_COUNT", "0x80021a20"), ("IB_SLOT_ACTOR", "0x80a8ef20"),
                          ("IB_ACTOR_SHORT", "0x8002a4c0"), ("IB_ITEM_OF_ACTOR", "0x833c6860"), ("IB_LISTABLE", "0x805b6af0"),
                          ("IB_IS_GET", "0x801a1160")):
        check(calls.get(name) == address and name in walk, "the walk does not call %s (%s)" % (name, address))
    check("ib_bottle(bottle) ? bottle :" in walk and "(uint64_t)age" in walk and
          "if (!a64_lookup(calls[i])) return 0;" in walk,
          "the walk does not take a bottle slot's own enum, ask for the age given, or stop when a call is missing")
    check('const int bean = ib_item_named(ib_names, "MagicBean");' in walk and
          "item == bean && age == IB_CHILD && (ib_guest(c, IB_IS_GET, 1, &name, 0, NULL) & 1)" in walk,
          "the Magic Beans are not found by the game's name for them, or not a child's on their IsGet alone")
    checked = function(core, "ib_check")
    check(re.search(r"if \(!ib_valid_items\(c, age, &valid\)\) return;", checked) and
          re.search(r"AcquireSRWLockExclusive\(&ib_lock\);\s*if \(__atomic_load_n\(&ib_load_gen, __ATOMIC_ACQUIRE\) == gen\) \{", checked)
          and "emptied = ib_keep_valid(ib_items[age], valid);" in checked and
          "__atomic_store_n(&ib_checked[age], gen, __ATOMIC_RELEASE);" in checked,
          "the check empties without a walk, or keeps a walk a load came during")
    check(checked.index("ReleaseSRWLockExclusive") < checked.index("hos_log") and
          checked.index("AcquireSRWLockExclusive") > checked.index("ib_valid_items"),
          "the check calls into the game or logs with the lock held")
    main = function(core, "hos_oot_ib_main")
    new, off, check_at = main.find("ib_new_game_seen();"), main.find("if (!ib_enabled()) return;"), main.find("ib_check(c);")
    check(0 <= new < off < check_at, "a new game is not seen with the feature off, or the check runs with it off")
    seen = function(core, "ib_new_game_seen")
    check("__atomic_exchange_n(&ib_title_open, 0," in seen and "if (ib_new_game(title," in seen and "ib_new_game_now();" in seen,
          "the title's coming up is not taken once, by play or a save, to tell a new game")
    check("if (write) ib_new_game_seen(), ib_save_slot(slot, path);" in observer,
          "a save before a new game's first tick of play (New Game's autosave) would take the last save's items")
    fresh = function(core, "ib_new_game_now")
    check("ib_items[age][k] = IB_NONE" in fresh and "__atomic_store_n(&ib_checked[age], gen," in fresh,
          "a new game does not start with no items, both ages checked")
    screen = function(core, "hos_oot_ib_screen")
    check(re.search(r"#define IB_TITLE_VTABLE 0x84c106e8ULL", core) and "else if (vt == IB_TITLE_VTABLE) ib_title();" in screen
          and "__atomic_store_n(&ib_hooked, 1," in screen, "the title screen is not UITitleScreen's, or hook 7 does not say "
          "the hooks run")
    title = function(core, "ib_title")
    check("!__atomic_load_n(&ib_title_open, __ATOMIC_ACQUIRE)" in title and "now - last > IB_LIVE_NS" in title,
          "the title comes up again without play since, or with each of its frames")
    print("PASS: OpenFile tells each file; a load reads, a save writes, an assignment stays in memory; the check, the new "
          "game and the title are the game's")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    core = (ROOT / "host" / "oot_item_buttons.c").read_text(encoding="utf-8")
    head = (ROOT / "host" / "oot_item_buttons.h").read_text(encoding="utf-8")
    fs = (ROOT / "host" / "nn_fs.c").read_text(encoding="utf-8")
    open_file(fs)
    game_side(core)
    with tempfile.TemporaryDirectory(prefix="item-buttons-saves-") as tmp:
        pure_parts(core, head, a.cc, tmp)


if __name__ == "__main__":
    main()
