import unittest

from project_guide import diff


class GuideDiffTests(unittest.TestCase):
    def test_hunks_track_old_and_new_numbers_independently(self):
        rows = list(diff.diff_rows('--- a/f\n+++ b/f\n@@ -7,2 +7,3 @@\n same\n-old\n+new\n+extra\n'
                                   '@@ -30 +31 @@\n---literal\n+++literal\n'))
        self.assertEqual(rows[3:7], [(7, 7, ' ', 'same'), (8, '', '-', 'old'),
                                     ('', 8, '+', 'new'), ('', 9, '+', 'extra')])
        self.assertEqual(rows[-2:], [(30, '', '-', '--literal'), ('', 31, '+', '++literal')])

    def test_create_delete_and_no_final_newline(self):
        self.assertEqual(list(diff.diff_rows('@@ -0,0 +1,2 @@\n+one\n+\n'))[1:],
                         [('', 1, '+', 'one'), ('', 2, '+', '')])
        self.assertEqual(list(diff.diff_rows('@@ -1 +0,0 @@\n-last\n\\ No newline at end of file\n'))[1:],
                         [(1, '', '-', 'last'), ('', '', '', '\\ No newline at end of file')])

    def test_unknown_format_is_escaped_and_kept_readable(self):
        rendered = diff.render_guide_diff('<script>& bad patch', 'unknown.xyz')
        self.assertIn('&lt;script&gt;&amp; bad patch', rendered)
        self.assertNotIn('<script>', rendered)
