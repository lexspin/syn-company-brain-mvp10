import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'plugins/company-brain'
CANONICAL = Path('C:/Users/USER/OneDrive/SYN Company Brain/V2')


class ChatPluginTests(unittest.TestCase):
    def test_package_paths_and_local_read_only_contract(self):
        manifest = json.loads((PACKAGE / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], 'company-brain')
        self.assertEqual(manifest['version'], '0.7.0')
        self.assertEqual(manifest['interface']['displayName'], 'Company Brain')
        for field in ('skills', 'mcpServers'):
            target = (PACKAGE / manifest[field]).resolve()
            self.assertTrue(target.is_relative_to(PACKAGE.resolve()))
            self.assertTrue(target.exists())
        skill = PACKAGE / 'skills/company-brain/SKILL.md'
        self.assertTrue(skill.read_text().startswith('---\nname: company-brain\n'))
        config = json.loads((PACKAGE / '.mcp.json').read_text())['mcpServers']['company-brain']
        self.assertTrue(Path(config['command']).is_file())
        self.assertEqual(Path(config['args'][0]).resolve(), (CANONICAL / 'app/memory_mcp.py').resolve())
        self.assertEqual(config['args'][1:], ['--native-read-only'])
        self.assertEqual(config['env'], {'PYTHONUTF8': '1'})
        self.assertNotIn('8765', json.dumps(config))
        role = Path('C:/Users/USER/.codex/skills/company-brain-harness/references/roles.json')
        self.assertTrue(role.is_file())

    def test_exact_packaged_stdio_command_lists_only_read_tools(self):
        config = json.loads((PACKAGE / '.mcp.json').read_text())['mcpServers']['company-brain']
        requests = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'package-test', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'save', 'arguments': {}}}]
        completed = subprocess.run([config['command'], *config['args']], input=''.join(json.dumps(r) + '\n' for r in requests),
                                   capture_output=True, text=True, encoding='utf-8', timeout=10,
                                   env={**os.environ, **config['env'], 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, '')
        replies = {row['id']: row for row in map(json.loads, completed.stdout.splitlines())}
        self.assertEqual(replies[1]['result']['serverInfo']['name'], 'company_brain_memory')
        tools = replies[2]['result']['tools']
        self.assertEqual({t['name'] for t in tools}, {'search_knowledge', 'get_knowledge', 'get_project', 'get_skill', 'review_learning_candidates', 'review_skill_curation'})
        self.assertTrue(all(t['annotations']['readOnlyHint'] and not t['annotations']['destructiveHint'] for t in tools))
        self.assertTrue(replies[3]['result']['isError'])


if __name__ == '__main__':
    unittest.main()
