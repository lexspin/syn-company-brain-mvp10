"""Pinned catalogue data is discovery evidence, never executable authorization."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from harness_catalog import CATALOG, MAX_BYTES, read_catalog, search_catalog, validate_catalog


def fixture(count=1):
    commit = 'a'*40; repository = 'NousResearch/hermes-agent'; entries = []
    for i in range(count):
        path = f'skills/research/source-check-{i:03d}/SKILL.md'
        entries.append({'path': path, 'name': f'source-check-{i:03d}', 'description': 'Research exact source evidence.',
            'category': 'research', 'distribution': 'skills', 'size_bytes': 100,
            'source_url': f'https://github.com/{repository}/blob/{commit}/{path}',
            'raw_url': f'https://raw.githubusercontent.com/{repository}/{commit}/{path}',
            'git_blob_sha1': 'b'*40, 'sha256': 'c'*64, 'retrieval_status': 'retrieved-hash-verified', 'git_blob_hash_verified': True,
            'dependency_trust': {'status': 'not-installed-not-executed', 'signals': ['network-mentioned']},
            'brain_fit': {'classification': 'method-adaptation-candidate', 'validation_status': 'not-evaluated'},
            'support_files': [], 'support_file_count': 0})
    return {'schema_version': 1, 'repository': repository, 'commit': commit,
        'created_at': datetime.now(timezone.utc).isoformat(), 'tree_response_sha256': 'd'*64,
        'tree_api_url': f'https://api.github.com/repos/{repository}/git/trees/{commit}?recursive=1',
        'summary': {'tree_truncated': False, 'skill_md_entries': count, 'retrieved_hash_verified': count, 'retrieval_failed': 0},
        'skills': entries}


class HarnessCatalogTests(unittest.TestCase):
    def test_discovery_is_pinned_uninstalled_and_input_unchanged(self):
        data = fixture(); before = copy.deepcopy(data)
        result = search_catalog(data, 'source-check-000')
        card = result['skills'][0]
        self.assertEqual(card['commit'], 'a'*40); self.assertEqual(card['sha256'], 'c'*64)
        self.assertEqual(card['adoption_status'], 'catalogued-not-installed-not-executed')
        self.assertEqual(card['fit_validation'], 'not-evaluated'); self.assertTrue(card['dependency_gaps'])
        self.assertIn('not independently reread', result['source_check'])
        self.assertEqual(data, before)

    def test_missing_version_unpinned_or_wrong_source_rejected(self):
        for field, value in [('schema_version', None), ('schema_version', True), ('commit', 'main'), ('repository', 'Other/repo')]:
            data = fixture(); data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate_catalog(data)
        for field, value in [('source_url', 'https://github.com/NousResearch/hermes-agent/blob/main/skills/test/SKILL.md'),
                             ('raw_url', 'https://example.com/code'), ('sha256', 'missing'), ('git_blob_sha1', 'b'*39)]:
            data = fixture(); data['skills'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate_catalog(data)

    def test_false_verified_adoption_claims_rejected(self):
        for field, value in [('installed', True), ('executed', True), ('verified', 'yes'), ('adoption_status', 'tested-adapter'),
                             ('git_blob_hash_verified', False), ('retrieval_status', 'available')]:
            data = fixture(); data['skills'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate_catalog(data)
        data = fixture(); data['skills'][0]['brain_fit']['validation_status'] = 'verified'
        with self.assertRaises(ValueError): validate_catalog(data)
        data = fixture(); data['skills'][0]['dependency_trust']['status'] = 'installed'
        with self.assertRaises(ValueError): validate_catalog(data)

    def test_corrupt_metadata_and_duplicate_paths_rejected(self):
        for value in [[], None, 'unknown']:
            data = fixture(); data['skills'][0]['distribution'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): validate_catalog(data)
        data = fixture(2); data['skills'][1] = copy.deepcopy(data['skills'][0])
        with self.assertRaises(ValueError): validate_catalog(data)
        data = fixture(); data['skills'][0]['path'] = '../SKILL.md'
        with self.assertRaises(ValueError): validate_catalog(data)
        data = fixture(); data['summary']['tree_truncated'] = True
        with self.assertRaises(ValueError): validate_catalog(data)
        data = fixture(); data['summary']['retrieved_hash_verified'] = True
        with self.assertRaises(ValueError): validate_catalog(data)

    def test_query_category_before_cap_and_absent_matches(self):
        data = fixture(40); data['skills'][-1].update(name='specific-deployment', category='devops', description='Deploy checked artifact.')
        result = search_catalog(data, 'specific-deployment', limit=1)
        self.assertEqual(result['skills'][0]['name'], 'specific-deployment'); self.assertEqual(result['matches_total'], 1)
        self.assertEqual(search_catalog(data, category='devops', limit=1)['matches_total'], 1)
        self.assertEqual(search_catalog(data, query='no-unrelated-term')['skills'], [])
        self.assertEqual(search_catalog(data, category='unknown')['skills'], [])
        self.assertEqual(search_catalog(data, query='specific-deployment', category='research')['skills'], [])

    def test_name_collisions_preserve_every_exact_path_and_pinned_license(self):
        data = fixture(2); data['skills'][1]['name'] = data['skills'][0]['name']
        result = search_catalog(data, data['skills'][0]['name'])
        self.assertEqual(len(result['skills']), 2)
        self.assertNotEqual(result['skills'][0]['id'], result['skills'][1]['id'])
        data['license'] = {'spdx': 'MIT', 'path': 'HERMES-LICENSE.txt',
            'source_url': 'https://github.com/NousResearch/hermes-agent/blob/'+data['commit']+'/LICENSE',
            'raw_url': 'https://raw.githubusercontent.com/NousResearch/hermes-agent/'+data['commit']+'/LICENSE',
            'sha256': 'e'*64, 'git_blob_sha1': 'f'*40}
        self.assertEqual(search_catalog(data)['license_reference']['sha256'], 'e'*64)
        data['license']['source_url'] = 'https://github.com/NousResearch/hermes-agent/blob/main/LICENSE'
        with self.assertRaises(ValueError): validate_catalog(data)

    def test_result_metadata_and_support_paths_bounded(self):
        data = fixture(40); entry = data['skills'][0]; entry['description'] = 'x'*4000
        entry['support_files'] = [{'path': f'skills/research/source-check-000/references/{i}.md',
                                 'git_blob_sha1': 'e'*40, 'size_bytes': 10} for i in range(12)]
        entry['support_file_count'] = 12
        result = search_catalog(data, query=entry['name'], limit=1); card = result['skills'][0]
        self.assertEqual(len(card['description']), 600); self.assertTrue(card['description_truncated'])
        self.assertEqual(len(card['support_paths']), 8); self.assertTrue(card['support_paths_truncated'])
        result = search_catalog(data, limit=2)
        self.assertEqual(result['skills_total'], 40); self.assertEqual(result['matches_total'], 40)
        self.assertEqual(len(result['skills']), 2); self.assertTrue(result['truncated'])
        for kwargs in [{'limit': 33}, {'limit': True}, {'query': 'x'*1001}, {'category': 'x'*81}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): search_catalog(data, **kwargs)

    def test_cli_has_no_network_or_writes_and_returns_local_file_hash(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime') as folder:
            root = Path(folder); path = root/CATALOG; path.parent.mkdir(parents=True)
            path.write_text(json.dumps(fixture()), encoding='utf-8')
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            command = [sys.executable, '-X', 'utf8', str(Path(__file__).resolve().parents[1]/'app/harness_catalog.py'),
                       '--root', str(root), '--query', 'source-check-000', '--limit', '1']
            process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads(process.stdout); self.assertEqual(len(result['catalog_file']['sha256']), 64)
            self.assertEqual(result['catalog_file']['path'], str(path))
            with patch('socket.socket', side_effect=AssertionError('Network forbidden')):
                self.assertEqual(read_catalog(root)['skills_total'], 1)
            self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()})
            self.assertFalse((root/'runtime').exists()); self.assertFalse((root/'store').exists())

    def test_invalid_json_and_oversize_catalog_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'runtime') as folder:
            root = Path(folder); path = root/CATALOG; path.parent.mkdir(parents=True)
            path.write_bytes(b'{bad}')
            with self.assertRaises(ValueError): read_catalog(root)
            path.write_bytes(b' '* (MAX_BYTES+1))
            with self.assertRaises(ValueError): read_catalog(root)


if __name__ == '__main__': unittest.main()
