"""Scoped checkpoints and explicit pushes through Git's existing credential manager."""
import subprocess
from urllib.parse import urlsplit

PATHS = ['app', 'docs', 'evaluations', 'records', 'skills', 'company', 'memory-map', 'routines', 'BRAIN.md', 'README.md',
         'AGENTS.md', '.gitignore', 'Start-Codex-Brain.ps1', 'INSTALLATION.md',
         'Start-Dashboard.ps1', 'Stop-Dashboard.ps1']

# Product deliverables belong in their own repositories, not the OS checkpoint.
PRODUCT_FORMATS = {'.doc', '.docx', '.pdf', '.ppt', '.pptx', '.xls', '.xlsx',
                   '.blend', '.blend1', '.blend2', '.uasset', '.umap', '.fbx',
                   '.mp4', '.mov', '.avi', '.wav', '.mp3', '.flac'}

def check_os_paths(paths):
    from pathlib import PurePosixPath
    blocked = [p for p in paths if PurePosixPath(p).suffix.lower() in PRODUCT_FORMATS]
    if blocked:
        raise ValueError('AI OS repository only. Keep product documents/media in their owning project and save links here: '+', '.join(blocked[:8]))

def run(brain, action='status'):
    if action in ('commit','push'):
        with brain.lock:return _run(brain,action)
    return _run(brain,action)

def _run(brain, action):
    def call(*args, optional=False):
        import os
        env=dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
        p=subprocess.run(['git', '-C', str(brain.root), *args], env=env,
                         capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
        if p.returncode and not optional:
            raise ValueError(p.stderr.strip() or 'Git command failed.')
        return p.stdout.strip() if not p.returncode else ''

    if action not in ('status', 'commit', 'push'):
        raise ValueError('Unsupported Git operation.')
    if action in ('commit', 'push'):
        brain.export()
        staged=call('diff', '--cached', '--name-only').splitlines()
        if any(p.split('/')[0] not in PATHS for p in staged):
            raise ValueError('Unrelated files are staged. Review them before saving a checkpoint.')
        check_os_paths(call('ls-files', '--cached', '--others', '--exclude-standard', '--', *PATHS).splitlines())
        call('add', '--', *[p for p in PATHS if (brain.root/p).exists()])
        if call('diff', '--cached', '--name-only'):
            call('commit', '-m', 'Save Company Brain configuration and implementation')
    branch=call('branch', '--show-current')
    remote=call('remote', 'get-url', 'origin', optional=True)
    if action=='push':
        if not branch or not remote:
            raise ValueError('A branch and origin remote are required before pushing.')
        # Only the configured branch is pushed; never force, delete, or mirror.
        call('push', '--set-upstream', 'origin', branch)
    remote_url=''
    if remote.startswith('git@github.com:'):
        remote_url='https://github.com/'+remote.split(':',1)[1].removesuffix('.git')
    elif remote:
        url=urlsplit(remote)
        if url.scheme=='https' and url.hostname=='github.com':
            remote_url='https://github.com/'+url.path.strip('/').removesuffix('.git')
    upstream=call('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}', optional=True)
    ahead=behind=None
    if upstream:
        count=call('rev-list', '--left-right', '--count', 'HEAD...'+upstream).split()
        ahead,behind=map(int,count)
    return {'status':call('status', '--short'), 'branch':branch,
            'remote_url':remote_url, 'remote_configured':bool(remote),
            'upstream':upstream, 'ahead':ahead, 'behind':behind,
            'head':call('rev-parse', '--short', 'HEAD', optional=True),
            'push_verified':action=='push',
            'note':'Ahead/behind compare with the last observed remote branch.'}
