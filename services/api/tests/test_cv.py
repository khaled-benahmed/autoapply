import unittest

from app.cv import CvProfile, parse_cv

SAMPLE_CV = """Jean Dupont
Ingénieur logiciel

COMPÉTENCES
- Python,
- React,
- Machine learning

FORMATION
2019-2022 Master Informatique, Université Paris-Saclay

EXPÉRIENCE
- 2023 - 2025 Développeur backend chez Mediansys (Python, FastAPI)
- 2022 Stage BI chez un éditeur financier

PROJETS
- Projet de fin d'études : détection d'anomalies dans une chaîne logistique
- Dashboard BI pour le suivi d'indicateurs

CERTIFICATIONS
- Deep Learning Specialization — DeepLearning.AI
- Data Engineer Associate — DataCamp

STRONGLY REMOVED
- ceci ne doit pas apparaître (pas de section connue)
"""


class ParseCvTests(unittest.TestCase):
    def test_extracts_skills_education_experience_projects(self) -> None:
        profile = parse_cv(SAMPLE_CV)

        self.assertEqual(
            profile.skills, ["Python,", "React,", "Machine learning"]
        )
        self.assertEqual(profile.education, ["2019-2022 Master Informatique, Université Paris-Saclay"])
        self.assertEqual(len(profile.experience), 2)
        self.assertEqual(len(profile.projects), 2)
        self.assertTrue(profile.projects[0].startswith("Projet de fin d'études"))
        self.assertEqual(len(profile.certifications), 2)
        self.assertEqual(profile.certifications[0], "Deep Learning Specialization — DeepLearning.AI")

    def test_ignores_items_outside_known_sections(self) -> None:
        profile = parse_cv(SAMPLE_CV)

        self.assertNotIn("ceci ne doit pas apparaître", " ".join(profile.projects))
        self.assertNotIn("ceci ne doit pas apparaître", " ".join(profile.skills))

    def test_query_builds_from_profile(self) -> None:
        profile = CvProfile(skills=["python", "react", "machine learning"], projects=["dashboard"], experience=["bi"])

        query = profile.query

        self.assertIn("python", query)
        self.assertIn("dashboard", query)
        self.assertIn("bi", query)

    def test_repairs_broken_accent_encoding(self) -> None:
        cv = "COMP\xb4ETENCES\n- Python\n\nEXP\xb4ERIENCE\n- D\xb4eveloppement RAG avec Azure"
        profile = parse_cv(cv)

        self.assertEqual(profile.skills, ["Python"])
        self.assertEqual(profile.experience, ["Développement RAG avec Azure"])

    def test_all_caps_company_name_does_not_close_section(self) -> None:
        cv = "EXPÉRIENCE\nStagiaire Data Science\nFév. 2024 – Avr. 2024\nODDO BHF\nTunis, TN\n- Développement de pipelines RAG"
        profile = parse_cv(cv)

        self.assertGreater(len(profile.experience), 0)
        self.assertIn("Développement de pipelines RAG", profile.experience)

    def test_unknown_all_caps_heading_only_closes_when_bullets_follow(self) -> None:
        cv = "EXPÉRIENCE\n- RAG avec LangChain\n\nAUTRES INFORMATIONS\n- tennis\n\nODDO BHF\nville"
        profile = parse_cv(cv)

        self.assertNotIn("tennis", " ".join(profile.experience))
        self.assertIn("RAG avec LangChain", profile.experience)

    def test_substantive_lines_feed_query_signal(self) -> None:
        cv = "EXPÉRIENCE\n- Developer backend\nStack technique : Azure, Docker, Django"
        profile = parse_cv(cv)

        self.assertIn("Stack technique : Azure, Docker, Django", profile.experience)