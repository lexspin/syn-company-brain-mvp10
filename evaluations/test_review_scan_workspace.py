import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from review_scan import inventory, ROOT


class ReviewWorkspaceTests(unittest.TestCase):
    def test_wrong_workspace_is_rejected_before_inventory(self):
        response = io.BytesIO(json.dumps({'root': 'D:/unrelated-brain', 'objects': []}).encode())
        with patch('review_scan.urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'workspace'):
                inventory(ROOT)

    def test_missing_workspace_identity_is_rejected(self):
        response = io.BytesIO(b'{"objects": []}')
        with patch('review_scan.urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'workspace'):
                inventory(ROOT)
