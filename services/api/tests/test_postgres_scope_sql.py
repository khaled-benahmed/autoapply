import re
import unittest

from app.book_repository import _KEYWORD_SELECT


class KeywordScopeSqlTests(unittest.TestCase):
    def test_book_hash_scope_binds_to_the_whole_where_group(self) -> None:
        sql = _KEYWORD_SELECT + " AND book_hash = %s" + " ORDER BY score DESC, id LIMIT %s"
        where_part = sql.split("WHERE", 1)[1].split("ORDER BY", 1)[0]

        closing = where_part.rindex(")")
        scope_at = where_part.rindex("AND book_hash = %s")

        self.assertLess(closing, scope_at)
        self.assertNotIn("\nOR", where_part[closing:scope_at])

    def test_scoped_sql_sends_expected_placeholder_count(self) -> None:
        sql = _KEYWORD_SELECT + " AND book_hash = %s" + " ORDER BY score DESC, id LIMIT %s"
        escaped = sql.replace("%%", "")
        placeholders = len(re.findall(r"%s", escaped))

        self.assertEqual(placeholders, 9)


if __name__ == "__main__":
    unittest.main()