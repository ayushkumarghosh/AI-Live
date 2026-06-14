import os
import unittest
from unittest.mock import patch

import azure_realtime


class AzureRealtimeConfigTests(unittest.TestCase):
    def test_vad_env_parsers_use_defaults_for_missing_or_invalid_values(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(azure_realtime.parse_int_env("AZURE_OPENAI_VAD_SILENCE_MS", 350), 350)
            self.assertEqual(azure_realtime.parse_float_env("AZURE_OPENAI_VAD_THRESHOLD", 0.5), 0.5)

        with patch.dict(
            os.environ,
            {
                "AZURE_OPENAI_VAD_SILENCE_MS": "-1",
                "AZURE_OPENAI_VAD_THRESHOLD": "bad",
            },
            clear=True,
        ):
            self.assertEqual(azure_realtime.parse_int_env("AZURE_OPENAI_VAD_SILENCE_MS", 350), 350)
            self.assertEqual(azure_realtime.parse_float_env("AZURE_OPENAI_VAD_THRESHOLD", 0.5), 0.5)

    def test_vad_env_parsers_accept_overrides(self):
        with patch.dict(
            os.environ,
            {
                "AZURE_OPENAI_VAD_SILENCE_MS": "400",
                "AZURE_OPENAI_VAD_THRESHOLD": "0.6",
            },
            clear=True,
        ):
            self.assertEqual(azure_realtime.parse_int_env("AZURE_OPENAI_VAD_SILENCE_MS", 350), 400)
            self.assertEqual(azure_realtime.parse_float_env("AZURE_OPENAI_VAD_THRESHOLD", 0.5), 0.6)


if __name__ == "__main__":
    unittest.main()
