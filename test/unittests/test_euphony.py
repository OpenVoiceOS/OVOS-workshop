import unittest

from ovos_workshop.skills.ovos import _join_word_list_it


class TestJoinWordListIt(unittest.TestCase):

    def test_basic_conjunction_and(self):
        # Test without euphonic transformation for "and"
        result = _join_word_list_it(["mare", "montagna"], "and")
        self.assertEqual(result, "mare e montagna")

    def test_basic_conjunction_or(self):
        # Test without euphonic transformation for "or"
        result = _join_word_list_it(["mare", "montagna"], "or")
        self.assertEqual(result, "mare o montagna")

    def test_euphonic_conjunction_or(self):
        # Test euphonic transformation for "or" to "od"
        result = _join_word_list_it(["mare", "oceano"], "or")
        self.assertEqual(result, "mare od oceano")

    def test_euphonic_conjunction_and(self):
        # Test euphonic transformation for "and" to "ed"
        result = _join_word_list_it(["inverno", "estate"], "and")
        self.assertEqual(result, "inverno ed estate")

    def test_euphonic_conjunction_or_with_other_words(self):
        # Test euphonic transformation for "or" to "od" with different words
        result = _join_word_list_it(["libro", "orologio"], "or")
        self.assertEqual(result, "libro od orologio")

    def test_join_three_words(self):
        result = _join_word_list_it(["mare", "estate", "inverno"], "and")
        self.assertEqual(result, "mare, estate e inverno")

    def test_empty_list(self):
        result = _join_word_list_it([], "and")
        self.assertEqual(result, "")

    def test_single_word(self):
        result = _join_word_list_it(["mare"], "and")
        self.assertEqual(result, "mare")


if __name__ == "__main__":
    unittest.main()
