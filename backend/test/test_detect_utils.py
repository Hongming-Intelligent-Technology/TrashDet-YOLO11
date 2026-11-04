import unittest

from flask import Flask

import api.detect_api as detect_api


class DetectUtilsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg'}

    def test_parse_helpers(self):
        self.assertEqual(detect_api.parse_optional_float('1.25'), 1.25)
        self.assertIsNone(detect_api.parse_optional_float('abc'))
        self.assertIsNone(detect_api.parse_optional_float(''))
        self.assertEqual(detect_api.parse_int('12', 5), 12)
        self.assertEqual(detect_api.parse_int('bad', 5), 5)

    def test_is_allowed_image_by_config(self):
        with self.app.app_context():
            self.assertTrue(detect_api.is_allowed_image('a.png'))
            self.assertFalse(detect_api.is_allowed_image('a.gif'))

    def test_resolve_location_with_empty_geo(self):
        self.assertEqual(detect_api.resolve_location(None, None), '未知地点')

    def test_json_helpers(self):
        with self.app.app_context():
            ok_resp = detect_api.json_success({'x': 1})
            err_resp, status_code = detect_api.json_error('bad', 400)
            self.assertEqual(ok_resp.get_json().get('ok'), True)
            self.assertEqual(ok_resp.get_json().get('x'), 1)
            self.assertEqual(err_resp.get_json().get('ok'), False)
            self.assertEqual(status_code, 400)


if __name__ == '__main__':
    unittest.main()
