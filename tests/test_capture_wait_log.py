"""A capture's late pages are copied on the GPU, and the CPU wait that is left is timed apart.

Before, the replay thread waited for the write-back and copied the pages again, inside "retires and stamps": with a small
mirror budget (RX_VK_MIRROR_MB=1024 on an 8 GB card) that part read 2.4-3 ms a capture, six captures a frame, and nothing
said it was the replay thread waiting for the GPU (issue 995). Now the copies are recorded in the submission that uses the
capture, after the write-back's submission (issue 2655); the CPU waits only where the GPU cannot take them, and both are
timed on their own.

python -I -B tests/test_capture_wait_log.py
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


class CaptureWaitLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mem = (ROOT / "gpu" / "vk" / "vk_memory.cpp").read_text(encoding="utf-8")
        cls.take = block(cls.mem, "bool take_capture(")

    def test_the_late_pages_go_to_the_gpu_first(self):
        late = block(self.take, "if (c->late_value && c->map)")
        plan = late.index("late_copy_plan(*c, value)")
        wait = late.index("vk_timeline_wait(c->late_value);")
        self.assertLess(plan, wait, "take_capture waits for the GPU before planning the GPU copy")
        self.assertRegex(late[:plan], r"const auto (\w+) = std::chrono::steady_clock::now\(\);")
        self.assertIn("st_tk_late_gpu +=", late[plan:wait])
        self.assertIn("st_tk_late_gpu_n++", late[plan:wait])

    def test_the_cpu_wait_is_left_as_the_fallback(self):
        late = block(self.take, "if (c->late_value && c->map)")
        wait = late.index("vk_timeline_wait(c->late_value);")
        self.assertIn("st_tk_late +=", late[wait:])
        self.assertIn("st_tk_late_n++", late[wait:])
        self.assertIn("guarded_copy(", late[wait:])
        self.assertIn("flush_mapped(", late[wait:])

    def test_the_plan_does_not_wait(self):
        plan = block(self.mem, "bool late_copy_plan(")
        self.assertNotIn("vk_timeline_wait(", plan)
        self.assertIn("late_plan.copies", plan)

    def test_retires_and_stamps_start_after_the_lock(self):
        lock = self.take.index("std::lock_guard lk(pools_mu);")
        self.assertIn("st_tk_lock +=", self.take[lock:lock + 300])
        self.assertRegex(self.take, r"st_tk_stamp \+= std::chrono::duration<double, std::milli>\(tk1 - tk_locked\)")

    def test_the_log_line_names_the_gpu_copies_and_the_wait(self):
        line = re.search(r'logf\("vk: a capture taken \(ms\):.*?\);', self.take, re.S).group(0)
        self.assertIn("late pages copied on the GPU", line)
        self.assertIn("GPU wait for them", line)
        self.assertIn("pools lock", line)
        self.assertIn("st_tk_late_gpu / 600", line)
        self.assertIn("st_tk_late / 600", line)
        self.assertRegex(self.take, r"st_tk_late_gpu = st_tk_lock = 0, st_tk_late_n = st_tk_late_gpu_n = 0;")

    def test_the_flush_is_recorded_before_the_uploads(self):
        begin = block(self.mem, "void memory_begin_submission()")
        self.assertIn("late_copy_flush();", begin[:begin.index("std::lock_guard")])


if __name__ == "__main__":
    unittest.main()
