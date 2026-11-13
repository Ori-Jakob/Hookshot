"""The item buttons' file, each save's save:/slot_NN/item_buttons.ini (host/oot_item_buttons.c: ib_ini_read,
ib_ini_write).

Its code is compiled alone with a made-up table of item names handed in (in the game the names come from the game's own
table at run time, so none are kept in the repository), and run on a folder of its own. Pinned here: the items written
are read back, a line per face button with an item, "<age>_<button>=<name>" after a first line that says what the file is;
an item without a name is left out; a file that is not there reads as none; lines it does not know (junk, another age or
button, a name that is no item, an item already on another button of that age, a second line for one button, the tail of
an overlong line) are passed over and gone from the file at the next write; a Notepad BOM, spaces and CRLF are taken; a
write goes through <file>.tmp, which takes the file's place and is not left behind; nothing is written when the file
holds those items already (its time stays); a write that cannot be made says so and leaves nothing; with no item (or only
items without a name) the file is removed, there is nothing to do when it is not there, and a removal that cannot be made
says so.
python -I -B tests/test_item_buttons_ini.py   (needs a C compiler)
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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


def between(text, first, last):
    """from the line that holds first to the end of the block that starts at last"""
    start = text.rindex("\n", 0, text.index(first)) + 1
    return text[start:text.index(last)] + block(text, last)


PRELUDE = r"""
#include <ctype.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <utime.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
/* (host/posix's: a rename) */
#define MOVEFILE_REPLACE_EXISTING 1
static int MoveFileExA(const char *from, const char *to, unsigned flags) { (void)flags; return rename(from, to) == 0; }
#endif
"""

MAIN = r"""
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
static const char *names[IB_ITEMS];
static char name_text[IB_ITEMS][16];
static int items[IB_AGES][IB_BUTTONS], back[IB_AGES][IB_BUTTONS];
static void none(int t[IB_AGES][IB_BUTTONS]) {
    for (int age = 0; age < IB_AGES; age++)
        for (int k = 0; k < IB_BUTTONS; k++) t[age][k] = IB_NONE;
}
static const char *slurp(const char *path) {
    static char buf[8192];
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    const size_t n = fread(buf, 1, sizeof buf - 1, f);
    fclose(f);
    buf[n] = 0;
    return buf;
}
static int exists(const char *path) { struct stat st; return stat(path, &st) == 0; }
static void put(const char *path, const char *text) {
    FILE *f = fopen(path, "wb");
    CHECK(f && fputs(text, f) >= 0 && fclose(f) == 0);
}
/* the file's lines after its first */
static const char *body(const char *text) { const char *nl = text ? strchr(text, '\n') : NULL; return nl ? nl + 1 : ""; }

int main(int argc, char **argv) {
    CHECK(argc == 3);
    for (int i = 0; i < IB_ITEMS; i++)   /* (made-up names; a few items have none) */
        if (i % 9 != 4) snprintf(name_text[i], sizeof name_text[i], "Item%02d", i), names[i] = name_text[i];
    char path[512], tmp[600], bad[600];
    snprintf(path, sizeof path, "%s/item_buttons.ini", argv[1]);
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    snprintf(bad, sizeof bad, "%s/no such folder/item_buttons.ini", argv[1]);
    const char *blocked = argv[2];   /* (a folder by the file's name, with a file in it: no removal takes it) */

    /* not there yet: none */
    back[0][0] = 7;
    CHECK(ib_ini_read(path, names, back) == -1 && back[0][0] == IB_NONE);

    /* written and read back; an item without a name left out */
    none(items);
    items[IB_CHILD][IB_A] = 3, items[IB_CHILD][IB_Y] = 30, items[IB_ADULT][IB_X] = 46, items[IB_ADULT][IB_B] = 4;
    CHECK(ib_ini_write(path, names, items) == 1 && !exists(tmp));
    const char *text = slurp(path);
    CHECK(text && text[0] == '#' && !strcmp(body(text), "child_a=Item03\nchild_y=Item30\nadult_x=Item46\n"));
    CHECK(ib_ini_read(path, names, back) == 3);
    CHECK(back[IB_CHILD][IB_A] == 3 && back[IB_CHILD][IB_Y] == 30 && back[IB_ADULT][IB_X] == 46);
    CHECK(back[IB_ADULT][IB_B] == IB_NONE && back[IB_CHILD][IB_B] == IB_NONE && back[IB_ADULT][IB_A] == IB_NONE);

    /* the same items again: nothing written, the file's time as it was */
    struct utimbuf old = {1000000000, 1000000000};
    struct stat st;
    CHECK(utime(path, &old) == 0);
    CHECK(ib_ini_write(path, names, items) == 0);
    CHECK(stat(path, &st) == 0 && st.st_mtime == 1000000000 && !exists(tmp));

    /* a change: through the temporary file (one left from before is written over), which takes the file's place */
    put(tmp, "stale\n");
    items[IB_ADULT][IB_X] = IB_NONE, items[IB_ADULT][IB_A] = 46;
    CHECK(ib_ini_write(path, names, items) == 1 && !exists(tmp));
    text = slurp(path);
    CHECK(text && !strcmp(body(text), "child_a=Item03\nchild_y=Item30\nadult_a=Item46\n"));
    CHECK(stat(path, &st) == 0 && st.st_mtime != 1000000000);

    /* lines it does not know, names that are no item, an item twice: passed over, and gone at the next write */
    char file[2048];
    int n = snprintf(file, sizeof file, "\xEF\xBB\xBF  child_a = Item05  \r\n"
                                        "# a comment\n"
                                        "; another\n"
                                        "child_q=Item01\n"
                                        "teen_a=Item01\n"
                                        "adult_b=Nothing\n"
                                        "garbage\n"
                                        "=Item02\n"
                                        "adult_a=item07\n"
                                        "adult_y=Item07\n"
                                        "child_a=Item09\n"
                                        "adult_x=Item04\n"
                                        "#");
    for (int i = 0; i < 400; i++) file[n++] = ' ';   /* (a comment longer than a line: its tail is no line of its own) */
    n += snprintf(file + n, sizeof file - (size_t)n, "adult_b=Item08\n"
                                                     "child_b=Item11");   /* (no line end at the end) */
    put(path, file);
    CHECK(ib_ini_read(path, names, back) == 3);
    CHECK(back[IB_CHILD][IB_A] == 5 && back[IB_ADULT][IB_A] == 7 && back[IB_CHILD][IB_B] == 11);
    CHECK(back[IB_ADULT][IB_Y] == IB_NONE && back[IB_ADULT][IB_X] == IB_NONE && back[IB_ADULT][IB_B] == IB_NONE);
    CHECK(back[IB_CHILD][IB_X] == IB_NONE && back[IB_CHILD][IB_Y] == IB_NONE);
    CHECK(ib_ini_write(path, names, back) == 1);
    text = slurp(path);
    CHECK(text && text[0] == '#' && !strcmp(body(text), "child_a=Item05\nchild_b=Item11\nadult_a=Item07\n"));
    none(items);
    CHECK(ib_ini_read(path, names, items) == 3 && !memcmp(items, back, sizeof items));

    /* nothing at all, or only items without a name: no file, and nothing to do when there is none */
    none(items);
    CHECK(ib_named(names, items) == 0);
    items[IB_ADULT][IB_B] = 4;   /* (no name) */
    CHECK(ib_named(names, items) == 0);
    CHECK(ib_ini_write(path, names, items) == 1 && !exists(path) && !exists(tmp));
    CHECK(ib_ini_write(path, names, items) == 0 && !exists(path));
    CHECK(ib_ini_read(path, names, back) == -1 && back[IB_ADULT][IB_B] == IB_NONE);
    CHECK(ib_ini_write(bad, names, items) == 0 && !exists(bad));   /* (no folder: no file either) */
    put(path, "# the first line alone\n");   /* (one made by hand: read as none, and removed) */
    CHECK(ib_ini_read(path, names, back) == 0 && ib_ini_write(path, names, items) == 1 && !exists(path));

    /* a file that cannot be removed: said, left as it was */
    CHECK(ib_ini_write(blocked, names, items) == -1 && exists(blocked));

    /* an item again: the file is back */
    items[IB_CHILD][IB_X] = 3;
    CHECK(ib_named(names, items) == 1);
    CHECK(ib_ini_write(path, names, items) == 1);
    text = slurp(path);
    CHECK(text && text[0] == '#' && !strcmp(body(text), "child_x=Item03\n"));

    /* a file that cannot be written: said, nothing left */
    CHECK(ib_ini_write(bad, names, items) == -1 && !exists(bad));

    if (!fails) printf("PASS\n");
    return fails != 0;
}
"""


class ItemButtonsIniTests(unittest.TestCase):
    def test_file(self):
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        source = (ROOT / "host" / "oot_item_buttons.c").read_text(encoding="utf-8")
        head = (ROOT / "host" / "oot_item_buttons.h").read_text(encoding="utf-8")
        code = between(source, "static const char *const ib_age_keys[", "static int ib_ini_write(")
        self.assertNotIn("ib_peek", code, "the file's code reads guest memory")
        constants = "\n".join([block(head, "enum { IB_A"), block(head, "enum { IB_ADULT")] +
                              [line for line in head.splitlines() if line.startswith(("#define IB_NONE", "#define IB_ITEMS"))])
        with tempfile.TemporaryDirectory(prefix="hookshot-item-buttons-ini-") as tmp:
            tmp = Path(tmp)
            (tmp / "t.c").write_text(PRELUDE + constants + "\n" + code + MAIN, encoding="utf-8")
            folder = tmp / "slot_03"
            folder.mkdir()
            blocked = tmp / "blocked" / "item_buttons.ini"
            blocked.mkdir(parents=True)
            (blocked / "kept").write_text("kept\n", encoding="utf-8")
            binary = tmp / ("t.exe" if sys.platform == "win32" else "t")
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                                    str(tmp / "t.c"), "-o", str(binary)], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary), str(folder), str(blocked)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["item_buttons.ini"], "files left behind")
            self.assertEqual(sorted(p.name for p in blocked.iterdir()), ["kept"], "a removal took a folder's file")


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
