"""imap.py / smtp.py 的冒烟测试：以子进程方式跑 accounts 子命令。

不连真实邮箱服务器——accounts 只读配置。用临时 .env 提供已知配置，
验证脚本能加载配置、输出合法 JSON、且邮箱地址被打码。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, 'scripts')


class TestAccountsCommand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env_file = tempfile.NamedTemporaryFile(
            'w', suffix='.env', delete=False, encoding='utf-8')
        cls.env_file.write('IMAP_HOST=imap.example.com\nIMAP_USER=zhangsan@example.com\n'
                           'IMAP_PASS=secret\nSMTP_HOST=smtp.example.com\n'
                           'SMTP_USER=zhangsan@example.com\nSMTP_PASS=secret\n')
        cls.env_file.close()

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.env_file.name)

    def run_accounts(self, script):
        env = dict(os.environ)
        env['EMAIL_CONFIG_MODE'] = 'env'
        env['EMAIL_ENV_PATH'] = self.env_file.name
        # 指到不存在的路径，防止读到本机真实的 accounts.json
        env['EMAIL_ACCOUNTS_PATH'] = os.path.join(tempfile.gettempdir(), 'pms-不存在的accounts.json')
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, script), 'accounts'],
            capture_output=True, text=True, env=env, cwd=ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def check_payload(self, payload):
        self.assertTrue(payload['success'])
        self.assertEqual(payload['source'], 'env')
        self.assertEqual(len(payload['accounts']), 1)
        account = payload['accounts'][0]
        self.assertEqual(account['imapHost'], 'imap.example.com')
        self.assertEqual(account['smtpHost'], 'smtp.example.com')
        # 邮箱必须打码：完整地址和明文密码都不许出现在输出里
        self.assertNotIn('zhangsan@example.com', json.dumps(payload))
        self.assertNotIn('secret', json.dumps(payload))
        self.assertIn('***', account['email'])

    def test_imap_accounts(self):
        self.check_payload(self.run_accounts('imap.py'))

    def test_smtp_accounts(self):
        self.check_payload(self.run_accounts('smtp.py'))


if __name__ == '__main__':
    unittest.main()
