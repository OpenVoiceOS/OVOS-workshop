import unittest

from ovos_workshop.skills.ovos import _join_word_list_it, _join_word_list_es


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

    def test_multiple_euphonic_transformations(self):
        # Test multiple 'ed' transformations in the same list
        result = _join_word_list_it(["casa", "estate", "inverno", "autunno"], "and")
        self.assertEqual(result, "casa, estate, inverno e autunno")

    def test_mixed_conjunctions(self):
        # Test combining 'and' and 'or' conjunctions
        result = _join_word_list_it(["mare", "oceano", "isola"], "or")
        self.assertEqual(result, "mare, oceano o isola")


class TestJoinWordListEs(unittest.TestCase):

    def test_euphonic_conjunction_and(self):
        # Test euphonic transformation from "y" to "e"
        result = _join_word_list_es(["Juan", "Irene"], "and")
        self.assertEqual(result, "Juan e Irene")
        result = _join_word_list_es(["vaqueros", "indios"], "and")
        self.assertEqual(result, "vaqueros e indios")
        result = _join_word_list_es(["Manuel", "Hilario"], "and")
        self.assertEqual(result, "Manuel e Hilario")
        result = _join_word_list_es(["mujer", "hijos"], "and")
        self.assertEqual(result, "mujer e hijos")

    def test_euphonic_conjunction_exceptionsa_and(self):
        # When following word starts by (H)IA, (H)IE or (H)IO, then usual Y preposition is used
        result = _join_word_list_es(["frio", "hielo"], "and")
        self.assertEqual(result, "frio y hielo")
        result = _join_word_list_es(["cloro", "iodo"], "and")
        self.assertEqual(result, "cloro y iodo")
        result = _join_word_list_es(["Eta", "Iota"], "and")
        self.assertEqual(result, "Eta y Iota")
        result = _join_word_list_es(["paz", "hiógrafo"], "and")
        self.assertEqual(result, "paz y hiógrafo")

    def test_euphonic_conjunction_or(self):
        # Test euphonic transformation from "o" to "u"
        result = _join_word_list_es(["Manuel", "Óscar"], "or")
        self.assertEqual(result, "Manuel u Óscar")
        result = _join_word_list_es(["unos", "otros"], "or")
        self.assertEqual(result, "unos u otros")



if __name__ == "__main__":
    unittest.main()
