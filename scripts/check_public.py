"""检查发布文件中的凭据、个人路径和失效的本地 Markdown 链接。"""
from pathlib import Path
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.venv', '.runtime', 'vendor', 'dist', 'node_modules', '__pycache__', '.pytest_cache'}


def public_files():
    if (ROOT / '.git').exists():
        names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
        return [ROOT / name for name in names if name]
    files = []
    for folder, directories, names in os.walk(ROOT):
        directories[:] = [name for name in directories if name not in SKIP]
        files.extend(Path(folder)/name for name in names if name not in ('.env', 'models.json', '.DS_Store'))
    return files


def problems(files):
    issues = []
    rules = {
        '个人主目录': r'/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/',
        '模型密钥': r'\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}',
        'GitHub 凭据': r'\bgh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}',
        'JWT': r'\beyJ[A-Za-z0-9_-]{25,}\.eyJ[A-Za-z0-9_-]{25,}\.[A-Za-z0-9_-]+',
        '私有密钥块': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    }
    for path in files:
        rel = path.relative_to(ROOT)
        if set(rel.parts) & SKIP or path.name in ('.env', 'models.json', 'bridge.json'):
            issues.append(f'{rel}: 私有运行文件进入发布清单')
        try: text = path.read_text()
        except (UnicodeDecodeError, ValueError): continue
        for name, pattern in rules.items():
            if re.search(pattern, text): issues.append(f'{rel}: {name}')
        if path.suffix == '.md' and 'dify-overlay' not in path.parts:
            for target in re.findall(r'\]\(([^)]+)\)', text):
                target = target.strip('<>').split('#')[0]
                if not target or re.match(r'[a-z]+:', target): continue
                if not (path.parent / target).exists(): issues.append(f'{rel}: 链接不存在 {target}')
    return issues


def main():
    files = public_files()
    issues = problems(files)
    import yaml
    dsl = yaml.safe_load((ROOT / 'workflow/teacher-video.yml').read_text())
    for item in dsl['workflow']['environment_variables']:
        if item.get('value_type') == 'secret' and item.get('value'):
            issues.append('workflow/teacher-video.yml: 包含工具凭据')
    for issue in issues: print(issue)
    print(f'检查 {len(files)} 个发布文件，发现 {len(issues)} 项问题。')
    return 1 if issues else 0


if __name__ == '__main__': sys.exit(main())
