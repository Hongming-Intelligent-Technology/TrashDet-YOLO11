import os
import tempfile
import unittest

from config import load_yaml_runtime_overrides


class ConfigTestCase(unittest.TestCase):
    def test_load_yaml_runtime_overrides_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, 'runtime_config.yaml')
            with open(config_path, 'w', encoding='utf-8') as fp:
                fp.write(
                    'app:\n'
                    '  SECRET_KEY: "abc"\n'
                    '  MAX_CONTENT_LENGTH: 123\n'
                    'detect:\n'
                    '  YOLO_CONF_THRESHOLD: 0.45\n'
                    '  LEFT_HALF_ONLY: true\n'
                    '  CAMERA_TIMEOUT_MS: 4000\n'
                )

            old_env = os.environ.get('BUSINESS_CONFIG_PATH')
            os.environ['BUSINESS_CONFIG_PATH'] = config_path
            try:
                overrides = load_yaml_runtime_overrides(temp_dir)
            finally:
                if old_env is None:
                    os.environ.pop('BUSINESS_CONFIG_PATH', None)
                else:
                    os.environ['BUSINESS_CONFIG_PATH'] = old_env

            self.assertEqual(overrides.get('SECRET_KEY'), 'abc')
            self.assertEqual(overrides.get('MAX_CONTENT_LENGTH'), 123)
            self.assertEqual(overrides.get('YOLO_CONF_THRESHOLD'), 0.45)
            self.assertTrue(overrides.get('DETECT_LEFT_HALF_ONLY'))
            self.assertEqual(overrides.get('CAMERA_TIMEOUT_MS'), 4000)

    def test_load_yaml_runtime_overrides_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_env = os.environ.get('BUSINESS_CONFIG_PATH')
            os.environ['BUSINESS_CONFIG_PATH'] = os.path.join(temp_dir, 'not_found.yaml')
            try:
                overrides = load_yaml_runtime_overrides(temp_dir)
            finally:
                if old_env is None:
                    os.environ.pop('BUSINESS_CONFIG_PATH', None)
                else:
                    os.environ['BUSINESS_CONFIG_PATH'] = old_env
            self.assertEqual(overrides, {})


if __name__ == '__main__':
    unittest.main()
