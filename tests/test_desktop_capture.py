import unittest

from desktop_capture import _signature, signature_difference


class QuestionChangeTests(unittest.TestCase):
    def test_answer_highlight_does_not_look_like_new_question(self):
        width, height = 200, 200
        base = bytearray(bytes((25, 25, 25, 255)) * width * height)
        lower_change = bytearray(base)
        upper_change = bytearray(base)
        timer_change = bytearray(base)
        for y in range(130, 170):
            for x in range(20, 180):
                lower_change[(y * width + x) * 4:(y * width + x) * 4 + 3] = b"\xff\xff\xff"
        for y in range(25, 65):
            for x in range(20, 180):
                upper_change[(y * width + x) * 4:(y * width + x) * 4 + 3] = b"\xff\xff\xff"
        for y in range(5, 25):
            for x in range(20, 180):
                timer_change[(y * width + x) * 4:(y * width + x) * 4 + 3] = b"\xff\xff\xff"
        original = _signature(base, width, height)
        self.assertEqual(signature_difference(original, _signature(lower_change, width, height)), 0)
        self.assertEqual(signature_difference(original, _signature(timer_change, width, height)), 0)
        self.assertGreater(signature_difference(original, _signature(upper_change, width, height)), 0.006)


if __name__ == "__main__":
    unittest.main()
