"""scripts/config.py 的单元测试（纯标准库 unittest）。"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))

import config  # noqa: E402


class TestParseBool(unittest.TestCase):
    def test_none_and_empty_use_default(self):
        self.assertTrue(config.parse_bool(None, default=True))
        self.assertFalse(config.parse_bool('', default=False))

    def test_string_values(self):
        self.assertTrue(config.parse_bool('true'))
        self.assertTrue(config.parse_bool('TRUE'))
        self.assertFalse(config.parse_bool('false'))
        self.assertFalse(config.parse_bool('1'))  # 只认 'true'，其余都是 False

    def test_bool_passthrough(self):
        self.assertTrue(config.parse_bool(True))
        self.assertFalse(config.parse_bool(False))


class TestParsePort(unittest.TestCase):
    def test_valid_port(self):
        self.assertEqual(config.parse_port('993', 587), 993)
        self.assertEqual(config.parse_port(465, 587), 465)

    def test_invalid_or_nonpositive_uses_default(self):
        self.assertEqual(config.parse_port('abc', 587), 587)
        self.assertEqual(config.parse_port('', 587), 587)
        self.assertEqual(config.parse_port('0', 587), 587)
        self.assertEqual(config.parse_port('-1', 587), 587)


class TestSlugifyAccountId(unittest.TestCase):
    def test_email_becomes_local_part(self):
        self.assertEqual(config.slugify_account_id('Boss@Example.com'), 'boss')

    def test_special_chars_become_dash(self):
        self.assertEqual(config.slugify_account_id('my work!'), 'my-work')

    def test_no_ascii_chars_falls_back(self):
        self.assertEqual(config.slugify_account_id('我的工作邮箱'), 'default')

    def test_empty_uses_fallback(self):
        self.assertEqual(config.slugify_account_id(''), 'default')
        self.assertEqual(config.slugify_account_id(None, 'x'), 'x')


class TestRedactEmail(unittest.TestCase):
    def test_masks_local_part_keeps_domain(self):
        self.assertEqual(config.redact_email('zhangsan@example.com'), 'zh***@example.com')

    def test_short_local_part(self):
        self.assertEqual(config.redact_email('ab@example.com'), 'ab*@example.com')

    def test_non_email_untouched(self):
        self.assertEqual(config.redact_email('不是邮箱'), '不是邮箱')
        self.assertEqual(config.redact_email(''), '')


class TestLoadEnvFile(unittest.TestCase):
    def test_parses_keys_comments_and_quotes(self):
        with tempfile.NamedTemporaryFile('w', suffix='.env', delete=False, encoding='utf-8') as fh:
            fh.write('# 注释\nIMAP_HOST=mail.example.com\nEMPTY=\n'
                     'QUOTED="带=号的值"\n没有等号的行\n SMTP_USER = user@example.com \n')
            path = fh.name
        try:
            result = config.load_env_file(path)
        finally:
            os.unlink(path)
        self.assertEqual(result['IMAP_HOST'], 'mail.example.com')
        self.assertEqual(result['QUOTED'], '带=号的值')
        self.assertEqual(result['SMTP_USER'], 'user@example.com')
        self.assertIn('EMPTY', result)
        self.assertNotIn('没有等号的行', result)

    def test_missing_file_returns_empty(self):
        self.assertEqual(config.load_env_file('不存在的路径.env'), {})


class TestNormalizeAccounts(unittest.TestCase):
    def test_defaults(self):
        account = config.normalize_account({'email': 'a@b.com', 'password': 'p',
                                            'imapHost': 'h1', 'smtpHost': 'h2'}, 0)
        self.assertEqual(account['id'], 'a')
        self.assertEqual(account['imapPort'], 993)
        self.assertEqual(account['smtpPort'], 587)
        self.assertTrue(account['imapTls'])
        self.assertFalse(account['smtpSecure'])
        self.assertTrue(account['requireSendConfirmation'])
        self.assertEqual(account['mailbox'], 'INBOX')

    def test_duplicate_ids_get_suffix(self):
        raw = [{'email': 'a@b.com'}, {'email': 'a@c.com'}, {'id': 'a'}]
        accounts = config.normalize_accounts(raw)
        self.assertEqual([a['id'] for a in accounts], ['a', 'a-2', 'a-3'])

    def test_disabled_flag(self):
        account = config.normalize_account({'id': 'x', 'enabled': False}, 0)
        self.assertFalse(account['enabled'])


class TestResolveAccount(unittest.TestCase):
    def _config(self):
        return {
            'defaultAccountId': 'one',
            'accounts': [
                dict(config.normalize_account({'id': 'one', 'email': 'a@b.com'}, 0)),
                dict(config.normalize_account({'id': 'two', 'email': 'c@d.com', 'enabled': False}, 1)),
            ],
        }

    def test_default_resolution(self):
        self.assertEqual(config.resolve_account(self._config())['id'], 'one')

    def test_unknown_id_raises(self):
        with self.assertRaises(RuntimeError):
            config.resolve_account(self._config(), 'nobody')

    def test_disabled_raises(self):
        with self.assertRaises(RuntimeError):
            config.resolve_account(self._config(), 'two')

    def test_no_enabled_raises(self):
        with self.assertRaises(RuntimeError):
            config.resolve_account({'defaultAccountId': '', 'accounts': []})


if __name__ == '__main__':
    unittest.main()
