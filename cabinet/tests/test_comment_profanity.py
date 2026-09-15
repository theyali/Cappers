from django.test import SimpleTestCase

from cabinet.comments.services import (
    ModerationCode,
    contains_profanity,
    normalize_obfuscated_text,
    validate_comment_text,
)


class CommentProfanityModerationTests(SimpleTestCase):
    def test_normalize_obfuscated_text_joins_single_letter_masks(self):
        self.assertEqual(normalize_obfuscated_text("м.а.т"), "мат")
        self.assertEqual(normalize_obfuscated_text("m a t"), "мат")

    def test_profanity_detection_is_case_insensitive(self):
        self.assertTrue(contains_profanity("БЛЯДЬ"))

    def test_spaces_and_punctuation_between_letters_do_not_bypass_filter(self):
        samples = (
            "б л я д ь",
            "б.л.я.д.ь",
            "б_л_я_д_ь",
            "х-у-й",
            "с у к а",
        )

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(contains_profanity(sample))

    def test_latin_letters_and_translit_do_not_bypass_filter(self):
        samples = (
            "blyat",
            "suka",
            "huy",
            "x у й",
            "pizda",
            "dolboeb",
        )

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(contains_profanity(sample))

    def test_digit_replacements_do_not_bypass_filter(self):
        self.assertTrue(contains_profanity("p1zda"))

    def test_partial_masks_do_not_bypass_filter(self):
        samples = (
            "х*й",
            "п*здец",
            "бл*дь",
            "f.u.c.k",
        )

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(contains_profanity(sample))

    def test_regular_words_are_not_false_positives(self):
        samples = (
            "страхуй игрока на стандартах",
            "банан и яблоко",
            "сук дерева лежит на поле",
            "хей, хороший прогноз",
        )

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertFalse(contains_profanity(sample))

    def test_rejected_result_exposes_public_api_fields(self):
        result = validate_comment_text("п.и.з.д.е.ц")

        self.assertFalse(result.allowed)
        self.assertFalse(result.is_allowed)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.reason, "profanity")
        self.assertEqual(result.code, ModerationCode.PROFANITY)
        self.assertEqual(result.public_message, "Комментарий содержит запрещенные слова.")
