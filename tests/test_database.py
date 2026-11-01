import unittest

from sqlalchemy.engine import make_url

from database import build_db_uri


class DatabaseUriTest(unittest.TestCase):
    def test_special_characters_in_credentials_survive(self):
        config = {'db_user': 'or/vo', 'db_pass': 'p@ss/w:rd %+ ?#', 'db_host': 'localhost', 'db_port': 5432, 'db_name': 'orvo_db'}
        url = make_url(build_db_uri(config))
        self.assertEqual(url.username, 'or/vo')
        self.assertEqual(url.password, 'p@ss/w:rd %+ ?#')
        self.assertEqual((url.host, url.port, url.database), ('localhost', 5432, 'orvo_db'))


if __name__ == '__main__':
    unittest.main()
