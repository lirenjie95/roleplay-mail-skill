#!/usr/bin/env python3
"""roleplay-mail-skill 安装脚本（Python 3.7+，仅标准库）。

功能：
  1. 检查 Python 版本（要求 3.7+）。
  2. 若本目录还没有 .env，则从 .env.example 复制一份。
  3. 对 scripts/ 下的邮件脚本做语法检查。
  4. 把本 skill 安装到各 coding agent 的技能目录：
     自动探测常见 agent（Kimi Code / Claude Code / Codex / DeepSeek Harness /
     opencode / OpenClaw 等）的用户级技能目录，也可以用 --target 手动指定。

用法：
  python install.py                 # 交互式：探测到目录后询问是否安装
  python install.py --yes           # 免确认，安装到所有探测到的目录
  python install.py --target DIR    # 安装到指定的技能目录（可重复）
  python install.py --no-skill      # 只做本地初始化，不复制 skill
  python install.py --force         # 覆盖已存在的安装副本
"""

import argparse
import os
import py_compile
import shutil
import sys

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_NAME = 'roleplay-mail-skill'


def candidate_skill_dirs():
    """返回 [(agent 名称, 用户级技能目录), ...]，覆盖常见 coding agent。"""
    home = os.path.expanduser('~')
    codex_home = os.environ.get('CODEX_HOME') or os.path.join(home, '.codex')
    return [
        ('Kimi Code（Agent Skills 通用目录）', os.path.join(home, '.agents', 'skills')),
        ('Claude Code', os.path.join(home, '.claude', 'skills')),
        ('Codex CLI', os.path.join(codex_home, 'skills')),
        ('DeepSeek Harness', os.path.join(home, '.dsh', 'skills')),
        ('opencode', os.path.join(home, '.opencode', 'skills')),
        ('OpenClaw', os.path.join(home, '.openclaw', 'skills')),
        ('OpenClaw（workspace）', os.path.join(home, '.openclaw', 'workspace', 'skills')),
    ]


# 复制时要排除的内容：密钥配置、版本库、运行期产物
EXCLUDE_NAMES = {'.git', '.env', 'accounts.json', '__pycache__'}
EXCLUDE_DIRS = {os.path.join('.agent', 'downloads'), os.path.join('.claude', 'downloads')}


def info(message):
    print('[安装] %s' % message)


def check_python():
    if sys.version_info < (3, 7):
        info('错误：需要 Python 3.7+（当前：%s）' % sys.version.split()[0])
        sys.exit(1)
    info('Python %s，版本符合要求' % sys.version.split()[0])


def setup_env():
    """没有 .env 就从模板复制一份，已有则绝不动它。"""
    env_path = os.path.join(SKILL_DIR, '.env')
    example_path = os.path.join(SKILL_DIR, '.env.example')
    if os.path.exists(env_path):
        info('.env 已存在，保持原样不覆盖')
        return
    if not os.path.exists(example_path):
        info('警告：找不到 .env.example，跳过 .env 创建')
        return
    shutil.copyfile(example_path, env_path)
    info('已从 .env.example 创建 .env，请编辑填入你的邮箱配置')


def check_scripts():
    """语法检查邮件脚本，装之前先确认能跑。"""
    for name in ('config.py', 'imap.py', 'smtp.py'):
        path = os.path.join(SKILL_DIR, 'scripts', name)
        py_compile.compile(path, doraise=True)
    info('scripts/config.py、imap.py、smtp.py 语法检查通过')


def copy_tree(src, dst):
    def ignore(directory, names):
        rel = os.path.relpath(directory, src)
        skipped = []
        for name in names:
            if name in EXCLUDE_NAMES:
                skipped.append(name)
                continue
            full_rel = os.path.normpath(name if rel == '.' else os.path.join(rel, name))
            if full_rel in EXCLUDE_DIRS:
                skipped.append(name)
        return skipped

    shutil.copytree(src, dst, ignore=ignore)


def _canon(path):
    """路径规范化：解析符号链接 + 按平台归一大小写（Windows 下小写化）。"""
    return os.path.normcase(os.path.realpath(path))


def _same_path(a, b):
    """跨平台比较两个路径是否指向同一位置。"""
    if _canon(a) == _canon(b):
        return True
    # macOS 默认 APFS 也是大小写不敏感的，normcase 在 POSIX 上不动大小写，
    # 两边都存在时用 samefile（比 inode）兜底
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _is_inside(path, directory):
    """path 是否位于 directory 内部。casefold 版本照顾 macOS 大小写不敏感
    文件系统；在大小写敏感系统上最坏只是误拒（安全方向）。"""
    target_c = _canon(path)
    source_c = _canon(directory)
    return (target_c.startswith(source_c + os.sep)
            or target_c.casefold().startswith(source_c.casefold() + os.sep))


def install_skill(skills_dir, force=False):
    skills_dir = os.path.abspath(os.path.expanduser(skills_dir))
    target = os.path.join(skills_dir, SKILL_NAME)
    source = os.path.abspath(SKILL_DIR)
    if _same_path(source, target):
        info('本目录就是安装目标（%s），跳过复制' % target)
        return False
    # 目标嵌套在源码目录里也不行：copytree 会递归进自己刚创建的目录
    if _is_inside(target, source):
        info('安装目标（%s）在源码目录内部，拒绝安装' % target)
        return False
    if os.path.exists(target):
        if not force:
            info('%s 已存在安装副本，跳过（如需覆盖请加 --force）' % target)
            return False
        shutil.rmtree(target)
    os.makedirs(skills_dir, exist_ok=True)
    copy_tree(SKILL_DIR, target)
    info('已安装到 %s' % target)
    return True


def detect_skill_dirs():
    """只返回真实存在的候选目录（探测，不创建）。"""
    found = []
    for agent, path in candidate_skill_dirs():
        expanded = os.path.abspath(path)
        if os.path.isdir(expanded) and expanded not in [p for _, p in found]:
            found.append((agent, expanded))
    return found


def confirm(question, assume_yes):
    if assume_yes:
        return True
    try:
        answer = input('%s [y/N] ' % question)
    except EOFError:
        return False
    return answer.strip().lower() in ('y', 'yes')


def main():
    parser = argparse.ArgumentParser(description='安装 roleplay-mail-skill。')
    parser.add_argument('--target', action='append', default=[],
                        help='指定要安装到的技能目录（可重复）')
    parser.add_argument('--yes', action='store_true',
                        help='所有询问都回答"是"')
    parser.add_argument('--force', action='store_true',
                        help='覆盖已存在的安装副本')
    parser.add_argument('--no-skill', action='store_true',
                        help='只做本地初始化，不复制 skill')
    args = parser.parse_args()

    check_python()
    setup_env()
    check_scripts()

    if args.no_skill:
        targets = []
    elif args.target:
        targets = [('（手动指定）', t) for t in args.target]
    else:
        targets = detect_skill_dirs()
        if not targets:
            info('没有探测到任何 agent 的技能目录；'
                 '可用 --target DIR 手动指定，例如各 agent 的用户级技能目录')
        else:
            listing = '、'.join('%s（%s）' % (agent, path) for agent, path in targets)
            if not confirm('探测到以下技能目录：%s。要安装进去吗？' % listing, args.yes):
                targets = []

    installed = []
    for agent, path in targets:
        info('安装给 %s …' % agent)
        if install_skill(path, force=args.force):
            installed.append(path)

    info('完成。')
    print()
    print('接下来的步骤：')
    print('  1. 编辑 %s ，填入你的邮箱配置' % os.path.join(SKILL_DIR, '.env'))
    print('  2. 在需要值班的项目里，把 %s'
          % os.path.join(SKILL_DIR, 'roleplay.config.example'))
    print('     复制为 .agent/roleplay.config，按需填 watchFrom（缺省监控所有人）和 role')
    print('  3. 让你的 agent 使用 roleplay-mail-skill 这个 skill 即可')
    if installed:
        print()
        print('注意：每个安装副本有自己独立的 .env，需要分别配置；')
        print('也可以设 EMAIL_ENV_PATH 环境变量，让所有副本共用同一份 .env。')


if __name__ == '__main__':
    main()
