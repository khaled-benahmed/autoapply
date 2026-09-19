import unittest

from app.book_extraction import BookExtraction, CompanyExtraction, SubjectExtraction, _subject_title_from_text
from app.data_quality import (
    build_index_subjects,
    detect_boilerplate,
    quality_report,
    repair_mojibake,
    sanitize_subject_text,
    strip_dirty_characters,
)


def _extraction(*subjects: SubjectExtraction) -> BookExtraction:
    return BookExtraction(company=CompanyExtraction(), subjects=list(subjects))


class MojibakeTests(unittest.TestCase):
    def test_repairs_common_french_artifacts(self) -> None:
        self.assertEqual(repair_mojibake("DÃ©veloppement d'outils ├®"), "Développement d'outils é")
        self.assertEqual(repair_mojibake("COMMUNICATION 360┬░"), "COMMUNICATION 360°")
        self.assertEqual(repair_mojibake("stratÃ©giesÔÇÖ"), "stratégies'")

    def test_strips_control_and_exotic_symbols(self) -> None:
        text = "bon\njour\ufeff\x00\x07ok\tfin"
        cleaned = strip_dirty_characters(text)
        self.assertNotIn("\ufeff", cleaned)
        self.assertNotIn("\x00", cleaned)
        self.assertNotIn("\x07", cleaned)


class NumeryxLayoutTests(unittest.TestCase):
    def test_recovers_title_ignoring_bare_label_lines(self) -> None:
        raw = (
            "[PAGE 11]\n"
            "Plateforme de Sécurité IA pour la Détection d'Intrusions\n"
            "PROJET :\n"
            "P26-01\n"
            "REF :\n"
            "R&D\n"
            "PÔLE :\n"
            "Profils & Compétences Clés\n"
            "Concevoir et développer une plateforme IA\n"
        )
        indexed = build_index_subjects(
            _extraction(
                SubjectExtraction(title="Untitled subject", rawText=raw),
                SubjectExtraction(
                    title="Untitled subject",
                    rawText=raw.replace("Plateforme de Sécurité IA", "Moteur de recommandation IA"),
                ),
            )
        )

        self.assertEqual(len(indexed), 2)
        titles = sorted(subject.title for subject in indexed)
        self.assertEqual(
            titles,
            [
                "Moteur de recommandation IA pour la Détection d'Intrusions",
                "Plateforme de Sécurité IA pour la Détection d'Intrusions",
            ],
        )

    def test_strips_obfuscated_email_anywhere(self) -> None:
        text = "[PAGE 1]\nsujet\nblabla contenu\nj o b s @ n u m e r y x . f r\nplus de contenu"
        cleaned = sanitize_subject_text(text)

        self.assertNotIn("@", cleaned)
        self.assertIn("plus de contenu", cleaned)
        self.assertIn("blabla contenu", cleaned)

    def test_title_from_text_ignores_bare_projet_label(self) -> None:
        self.assertEqual(
            _subject_title_from_text("[PAGE 11]\nSujet Projet\nPROJET :\nP26-01"),
            "Sujet Projet",
        )


class GeneralizationTests(unittest.TestCase):
    def test_keeps_unseen_scripts_and_combining_marks(self) -> None:
        text = (
            "coeur œ croissance ñ ü ç résolution é\n"
            "s\u0301 decomposed accent + \u0301 combining\n"
            "архив данных\nعربي\nβεtas ß ¾\n«guillemets» — – …\n🎯 Emoji"
        )
        cleaned = strip_dirty_characters(text)

        for token in ["œ", "ñ", "ü", "é", "\u0301", "архив", "عربي", "β", "ß", "¾", "«", "🎯"]:
            self.assertIn(token, cleaned)

    def test_removes_only_known_junk_characters(self) -> None:
        self.assertEqual(strip_dirty_characters("ok\x00bad\x07"), "okbad")
        self.assertNotIn("\ufeff", strip_dirty_characters("a\ufeffb"))


class SanitizeSubectTests(unittest.TestCase):
    def test_strips_chrome_and_boilerplate(self) -> None:
        text = (
            "Reference: TLS001/26\n"
            "[PAGE 17]\n"
            "PwC\n"
            "PwC\n"
            "Les opérations sur le capital social\n"
            "Objectif du stage :\n"
            "Approfondir les connaissances\n"
            "91\n"
            "BU: Advisory\n"
        )
        cleaned = sanitize_subject_text(text, boilerplate=["PwC"])

        self.assertNotIn("[PAGE", cleaned)
        self.assertNotIn("BU: Advisory", cleaned)
        self.assertNotIn("\n91\n", cleaned)
        self.assertIn("Les opérations", cleaned)
        self.assertIn("Objectif du stage :", cleaned)
        self.assertIn("Approfondir les connaissances", cleaned)

    def test_keeps_semantic_labels_in_boilerplate_detection(self) -> None:
        texts = [
            "Durée :\n5 mois\nSpécialités :\nPython\nBOILERTXT",
            "Durée :\n6 mois\nSpécialités :\nDocker\nBOILERTXT",
            "Durée :\n4 mois\nSpécialités :\nKafka\nBOILERTXT",
        ]
        boilerplate = detect_boilerplate(texts, threshold=0.6)

        self.assertIn("BOILERTXT", boilerplate)
        self.assertNotIn("Durée :", boilerplate)
        self.assertNotIn("Spécialités :", boilerplate)

    def test_does_not_flag_standard_stack_lines_as_boilerplate(self) -> None:
        texts = [
            "Frontend : Angular, TypeScript, HTML, CSS\nsujet A\n6 mois",
            "Frontend : Angular, TypeScript, HTML, CSS\nsujet B\n6 mois",
            "Frontend : Angular, TypeScript, HTML, CSS\nsujet C\n6 mois",
        ]
        boilerplate = detect_boilerplate(texts, threshold=0.6)

        self.assertNotIn("Frontend : Angular, TypeScript, HTML, CSS", boilerplate)

    def test_does_not_flag_duration_or_numbered_lines_as_boilerplate(self) -> None:
        texts = [
            "Durée :\n6 mois\nsujet A\nPostuler",
            "Durée :\n6 mois\nsujet B\nPostuler",
            "Durée :\n6 mois\nsujet C\nPostuler",
        ]
        boilerplate = detect_boilerplate(texts, threshold=0.6)

        self.assertNotIn("6 mois", boilerplate)
        self.assertIn("Postuler", boilerplate)

    def test_keeps_repeated_facts_mid_block(self) -> None:
        text = "[PAGE 3]\nsujet A\nDurée :\n6 mois\nbinôme\ncontenu long\nencore\nPostuler"
        cleaned = sanitize_subject_text(text, boilerplate=["6 mois", "binôme", "Postuler"])

        self.assertIn("6 mois", cleaned)
        self.assertIn("binôme", cleaned)
        self.assertIn("sujet A", cleaned)
        self.assertNotIn("Postuler", cleaned)

    def test_strips_boilerplate_at_block_edges(self) -> None:
        text = "PwC\nsujet A\ncontenu\nPostuler"
        cleaned = sanitize_subject_text(text, boilerplate=["PwC", "Postuler"])

        self.assertNotIn("PwC", cleaned)
        self.assertNotIn("Postuler", cleaned)
        self.assertIn("contenu", cleaned)

    def test_is_idempotent(self) -> None:
        text = "[PAGE 5]\nAcme\nTitre du projet\nObjective :\nsomething\n5\nBOILER"
        once = sanitize_subject_text(text, boilerplate=["BOILER"])
        self.assertEqual(sanitize_subject_text(once, boilerplate=["BOILER"]), once)

    def test_falls_back_when_too_much_would_be_removed(self) -> None:
        text = "[PAGE 1]\n1\n[PAGE 2]\n2\n[PAGE 3]\n3\nkept line"
        cleaned = sanitize_subject_text(text)

        self.assertTrue(cleaned.strip())
        self.assertIn("kept line", cleaned)


class IndexBuildTests(unittest.TestCase):
    def test_dedups_by_reference_keeping_longest(self) -> None:
        short = SubjectExtraction(
            title="Search", rawText="Reference: ADV 016/26\n[PAGE 31]\nSearch engine\nshort"
        )
        long = SubjectExtraction(
            title="Search", rawText="Reference: ADV 016/26\n[PAGE 31]\nSearch engine\n" + ("longer content\n" * 5)
        )
        indexed = build_index_subjects(_extraction(short, long))

        self.assertEqual(len(indexed), 1)
        self.assertIn("longer content", indexed[0].text)

    def test_different_references_are_kept(self) -> None:
        a = SubjectExtraction(title="A", rawText="Reference: TLS001/26\n[PAGE 1]\nA project")
        b = SubjectExtraction(title="B", rawText="Reference: TLS002/26\n[PAGE 2]\nB project")
        indexed = build_index_subjects(_extraction(a, b))

        self.assertEqual(len(indexed), 2)

    def test_recovers_untitled_from_pwc_style_block(self) -> None:
        subject = SubjectExtraction(
            title="Untitled subject",
            rawText="Reference: TLS001/26\n[PAGE 17]\nPwC\nPwC\nLes opérations sur le capital social\nObjectif du stage :",
        )
        indexed = build_index_subjects(_extraction(subject))

        self.assertEqual(indexed[0].title, "Les opérations sur le capital social")
        self.assertEqual(indexed[0].reference, "TLS001/26")

    def test_generalizes_to_unknown_layout(self) -> None:
        invented = SubjectExtraction(
            title="Untitled subject",
            rawText=(
                "HSG-D-2026\n"
                "HeliSoft Digital\n"
                "[PG 3]\n"
                "TITLE: Realtime analytics pipeline\n"
                "ABOUT THE ROLE:\n"
                "Build streaming pipelines with Flink and Kafka\n"
                "3\n"
                "Apply now"
            ),
        )
        boilerplate = detect_boilerplate(["HSG-D-2026\nHeliSoft Digital\n[PG 3]\n3\nApply now"])
        indexed = build_index_subjects(_extraction(invented), boilerplate=boilerplate)

        self.assertEqual(indexed[0].title, "Realtime analytics pipeline")
        self.assertIn("Flink", indexed[0].text)
        self.assertTrue(indexed[0].text.strip())
        self.assertNotIn("[PG", indexed[0].text)


class QualityReportTests(unittest.TestCase):
    def test_flags_issues_and_recoverable_titles(self) -> None:
        subjects = [
            SubjectExtraction(title="", rawText="Reference: TLS001/26\n[PAGE 1]\nTitle one\n" + "x" * 100),
            SubjectExtraction(title="Untitled subject", rawText="Reference: TLS001/26\n[PAGE 2]\nTitle two\n" + "y" * 100),
            SubjectExtraction(title="Untitled subject", rawText="[PAGE 3]\nok"),
            SubjectExtraction(title="Nice", rawText="[PAGE 4]\n" + "z" * 200, pageStart=4, pageEnd=4),
        ]
        report = quality_report(_extraction(*subjects))

        self.assertEqual(report["subjects"], 4)
        self.assertEqual(report["untitled"], 3)
        self.assertEqual(report["untitled_recoverable"], 2)
        self.assertEqual(report["duplicate_references"], 1)
        self.assertEqual(report["too_short"], 1)
        self.assertEqual(report["no_page"], 3)
        self.assertEqual(report["floor_trips"], 1)