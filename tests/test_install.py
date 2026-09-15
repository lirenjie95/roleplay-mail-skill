"""install.py 的单元测试（纯标准库 unittest）。

重点测复制排除逻辑：密钥文件（.env / accounts.json）、版本库（.git）、
缓存（__pycache__）和下载目录绝不能被复制进安装目标。
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import install  # noqa: E402


def make_file(path, content='x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(content)


class CopyTreeTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='pms-test-')
        self.src = os.path.join(self.tmp, 'src')
        self.dst = os.path.join(self.tmp, 'dst')
        # 造一个假的 skill 目录，包含所有应被排除的内容
        make_file(os.path.join(self.src, 'SKILL.md'), '# skill')
        make_file(os.path.join(self.src, 'scripts', 'imap.py'), '# imap')
        make_file(os.path.join(self.src, '.env'), 'SECRET=1')
        make_file(os.path.join(self.src, 'accounts.json'), '{}')
        make_file(os.path.join(self.src, '.git', 'config'), 'git')
        make_file(os.path.join(self.src, '__pycache__', 'a.pyc'), 'pyc')
        make_file(os.path.join(self.src, 'scripts', '__pycache__', 'b.pyc'), 'pyc')
        make_file(os.path.join(self.src, '.agent', 'downloads', 'f.bin'), 'bin')
        make_file(os.path.join(self.src, '.claude', 'downloads', 'g.bin'), 'bin')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestCopyTreeExclusions(CopyTreeTestBase):
    def test_normal_files_copied(self):
        install.copy_tree(self.src, self.dst)
        self.assertTrue(os.path.exists(os.path.join(self.dst, 'SKILL.md')))
        self.assertTrue(os.path.exists(os.path.join(self.dst, 'scripts', 'imap.py')))

    def test_secrets_and_caches_excluded(self):
        install.copy_tree(self.src, self.dst)
        for rel in ('.env', 'accounts.json',
                    os.path.join('.git', 'config'),
                    os.path.join('__pycache__', 'a.pyc'),
                    os.path.join('scripts', '__pycache__', 'b.pyc'),
                    os.path.join('.agent', 'downloads', 'f.bin'),
                    os.path.join('.claude', 'downloads', 'g.bin')):
            self.assertFalse(os.path.exists(os.path.join(self.dst, rel)),
                             '%s 不应被复制' % rel)


class TestSetupEnv(CopyTreeTestBase):
    def setUp(self):
        super().setUp()
        self._orig_skill_dir = install.SKILL_DIR
        install.SKILL_DIR = self.src

    def tearDown(self):
        install.SKILL_DIR = self._orig_skill_dir
        super().tearDown()

    def test_creates_env_from_example(self):
        os.unlink(os.path.join(self.src, '.env'))  # 去掉 setUp 造的那个
        make_file(os.path.join(self.src, '.env.example'), 'IMAP_HOST=x')
        install.setup_env()
        with open(os.path.join(self.src, '.env'), encoding='utf-8') as fh:
            self.assertEqual(fh.read(), 'IMAP_HOST=x')

    def test_never_overwrites_existing_env(self):
        with open(os.path.join(self.src, '.env'), 'w', encoding='utf-8') as fh:
            fh.write('REAL=secret')
        make_file(os.path.join(self.src, '.env.example'), 'IMAP_HOST=x')
        install.setup_env()
        with open(os.path.join(self.src, '.env'), encoding='utf-8') as fh:
            self.assertEqual(fh.read(), 'REAL=secret')


class TestInstallSkill(CopyTreeTestBase):
    def test_refuses_self_copy(self):
        # 构造"源码目录本身就是安装目标"的场景：绝不能把自己删掉再复制
        skills_dir = os.path.join(self.tmp, 'skills')
        src = os.path.join(skills_dir, install.SKILL_NAME)
        make_file(os.path.join(src, 'SKILL.md'), '# 本体')
        orig = install.SKILL_DIR
        install.SKILL_DIR = src
        try:
            self.assertFalse(install.install_skill(skills_dir, force=True))
        finally:
            install.SKILL_DIR = orig
        # 目录必须原样还在
        self.assertTrue(os.path.exists(os.path.join(src, 'SKILL.md')))

    def test_no_overwrite_without_force(self):
        install.install_skill(self.dst_parent, force=False)
        marker = os.path.join(self.dst_parent, install.SKILL_NAME, 'SKILL.md')
        with open(marker, 'w', encoding='utf-8') as fh:
            fh.write('被别人改过的')
        self.assertFalse(install.install_skill(self.dst_parent, force=False))
        with open(marker, encoding='utf-8') as fh:
            self.assertEqual(fh.read(), '被别人改过的')

    def test_force_overwrites(self):
        install.install_skill(self.dst_parent, force=False)
        marker = os.path.join(self.dst_parent, install.SKILL_NAME, 'SKILL.md')
        with open(marker, 'w', encoding='utf-8') as fh:
            fh.write('旧版本')
        self.assertTrue(install.install_skill(self.dst_parent, force=True))
        with open(marker, encoding='utf-8') as fh:
            self.assertNotEqual(fh.read(), '旧版本')

    def test_refuses_nested_target(self):
        # 目标在源码目录内部：copytree 会递归进自己刚创建的目录，必须拒绝
        orig = install.SKILL_DIR
        install.SKILL_DIR = self.src
        try:
            nested = os.path.join(self.src, 'inner-skills')
            self.assertFalse(install.install_skill(nested, force=True))
        finally:
            install.SKILL_DIR = orig
        self.assertFalse(os.path.exists(
            os.path.join(self.src, 'inner-skills', install.SKILL_NAME)))

    @unittest.skipUnless(os.name == 'nt', '仅 Windows 的大小写不敏感文件系统')
    def test_refuses_self_copy_case_variant(self):
        # 同一路径、不同大小写写法：--force 绝不能把源码目录自己删掉
        skills_dir = os.path.join(self.tmp, 'skills')
        src = os.path.join(skills_dir, install.SKILL_NAME)
        make_file(os.path.join(src, 'SKILL.md'), '# 本体')
        orig = install.SKILL_DIR
        install.SKILL_DIR = src.upper()  # 同一目录的大写写法
        try:
            self.assertFalse(install.install_skill(skills_dir.lower(), force=True))
        finally:
            install.SKILL_DIR = orig
        self.assertTrue(os.path.exists(os.path.join(src, 'SKILL.md')))

    def setUp(self):
        super().setUp()
        self.dst_parent = os.path.join(self.tmp, 'skills')


class TestCandidateSkillDirs(unittest.TestCase):
    def test_covers_mainstream_agents(self):
        paths = [p for _, p in install.candidate_skill_dirs()]
        joined = os.pathsep.join(paths)
        for fragment in ('.agents', '.claude', '.codex', '.dsh', '.opencode', '.openclaw'):
            self.assertIn(fragment, joined)

    def test_respects_codex_home(self):
        old = os.environ.get('CODEX_HOME')
        os.environ['CODEX_HOME'] = os.path.join(tempfile.gettempdir(), 'fake-codex-home')
        try:
            paths = [p for _, p in install.candidate_skill_dirs()]
        finally:
            if old is None:
                del os.environ['CODEX_HOME']
            else:
                os.environ['CODEX_HOME'] = old
        self.assertTrue(any(p.startswith(os.environ.get('CODEX_HOME', '') + os.sep) or
                            'fake-codex-home' in p for p in paths))


class TestPathGuards(CopyTreeTestBase):
    """_same_path / _is_inside 的跨平台测试（不依赖文件系统大小写敏感性）。"""

    def test_same_path_with_dotdot(self):
        # 带 .. 的写法应被 realpath 归一化为同一路径
        other = os.path.join(self.tmp, 'other')
        os.makedirs(other)
        self.assertTrue(install._same_path(
            self.src, os.path.join(other, '..', 'src')))

    def test_same_path_via_hardlink(self):
        # 硬链接指向同一 inode，samefile 兜底应判定相同
        a = os.path.join(self.tmp, 'a.txt')
        b = os.path.join(self.tmp, 'b.txt')
        make_file(a, 'x')
        try:
            os.link(a, b)
        except OSError:
            self.skipTest('当前文件系统不支持硬链接')
        self.assertTrue(install._same_path(a, b))

    def test_same_path_nonexistent_not_crash(self):
        # 不存在的路径不能抛异常，按"不相同"处理
        self.assertFalse(install._same_path(
            os.path.join(self.tmp, '不存在甲'), os.path.join(self.tmp, '不存在乙')))

    def test_is_inside_basic(self):
        self.assertTrue(install._is_inside(
            os.path.join(self.src, 'inner', install.SKILL_NAME), self.src))
        self.assertFalse(install._is_inside(self.dst, self.src))
        # 相等不算"内部"（相等由 _same_path 处理）
        self.assertFalse(install._is_inside(self.src, self.src))

    def test_is_inside_casefold(self):
        # 大小写不同的嵌套写法在 macOS/Windows 上是同一个目录，必须视为内部
        upper_inner = os.path.join(self.src.upper(), 'inner')
        self.assertTrue(install._is_inside(upper_inner, self.src.lower()))

    def test_install_case_variant_inside_refused(self):
        # 大小写变体的嵌套目标：各平台都必须拒绝（不能只在 Windows 生效）
        orig = install.SKILL_DIR
        install.SKILL_DIR = self.src
        try:
            weird = os.path.join(self.src.upper(), 'Inner-Skills')
            self.assertFalse(install.install_skill(weird, force=True))
        finally:
            install.SKILL_DIR = orig


if __name__ == '__main__':
    unittest.main()
