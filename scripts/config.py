"""配置加载（Python 3.7+，仅标准库）。

本文件移植自网易有道 LobsterAI 项目的 imap-smtp-email skill
（https://github.com/netease-youdao/LobsterAI/tree/main/SKILLs/imap-smtp-email），
原作 NetEase，Node.js 实现，MIT License。

解析顺序：
  1. EMAIL_CONFIG_MODE=env      -> 只用 .env / 环境变量
  2. skill 目录的 accounts.json -> 多账号配置
  3. skill 目录的 .env          -> 单账号（旧式）

路径可用 EMAIL_ACCOUNTS_PATH / EMAIL_ENV_PATH 环境变量覆盖。
"""

import json
import os
import re

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNTS_PATH = os.environ.get('EMAIL_ACCOUNTS_PATH') or os.path.join(SKILL_DIR, 'accounts.json')
ENV_PATH = os.environ.get('EMAIL_ENV_PATH') or os.path.join(SKILL_DIR, '.env')

EMAIL_RE = re.compile(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}', re.IGNORECASE)


def parse_bool(value, default=False):
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() == 'true'


def parse_port(value, default):
    try:
        port = int(str(value if value is not None else ''))
        return port if port > 0 else default
    except ValueError:
        return default


def slugify_account_id(value, fallback='default'):
    normalized = re.sub(r'[^a-z0-9_-]+', '-', re.sub(r'@.+$', '', str(value or '').strip().lower()))
    normalized = normalized.strip('-')
    return normalized or fallback


def redact_email(value):
    if not value:
        return value

    def _mask(match):
        local, _, domain = match.group(0).partition('@')
        if not domain:
            return '[redacted-email]'
        prefix = local[:2]
        return '%s%s@%s' % (prefix, '***' if len(local) > 2 else '*', domain)

    return EMAIL_RE.sub(_mask, str(value))


def load_env_file(path):
    """极简 .env 解析：KEY=VALUE 行，支持 '#' 注释和可选引号。"""
    result = {}
    if not os.path.exists(path):
        return result
    with open(path, 'r', encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                result[key] = value
    return result


def load_legacy_env():
    merged = load_env_file(ENV_PATH)
    merged.update(os.environ)
    return merged


def has_legacy_env(env):
    return bool(env.get('IMAP_USER') or env.get('SMTP_USER') or env.get('IMAP_HOST') or env.get('SMTP_HOST'))


def legacy_env_to_account(env, account_id='default'):
    email = env.get('IMAP_USER') or env.get('SMTP_USER') or env.get('SMTP_FROM') or ''
    return {
        'id': account_id,
        'name': email.split('@')[0] if email else 'Default',
        'enabled': True,
        'provider': '',
        'email': email,
        'password': env.get('IMAP_PASS') or env.get('SMTP_PASS') or '',
        'imapHost': env.get('IMAP_HOST') or '',
        'imapPort': parse_port(env.get('IMAP_PORT'), 993),
        'imapTls': parse_bool(env.get('IMAP_TLS'), True),
        'imapRejectUnauthorized': parse_bool(env.get('IMAP_REJECT_UNAUTHORIZED'), True),
        'smtpHost': env.get('SMTP_HOST') or '',
        'smtpPort': parse_port(env.get('SMTP_PORT'), 587),
        'smtpSecure': parse_bool(env.get('SMTP_SECURE'), False),
        'smtpRejectUnauthorized': parse_bool(env.get('SMTP_REJECT_UNAUTHORIZED'), True),
        'smtpFrom': env.get('SMTP_FROM') or env.get('SMTP_USER') or email,
        'mailbox': env.get('IMAP_MAILBOX') or 'INBOX',
        'requireSendConfirmation': parse_bool(env.get('EMAIL_REQUIRE_SEND_CONFIRMATION'), True),
    }


def normalize_account(raw, index):
    email = str(raw.get('email') or raw.get('IMAP_USER') or raw.get('SMTP_USER') or '').strip()
    account_id = slugify_account_id(raw.get('id') or email, 'account-%d' % (index + 1))
    return {
        'id': account_id,
        'name': str(raw.get('name') or (email.split('@')[0] if email else account_id)).strip(),
        'enabled': raw.get('enabled') is not False,
        'provider': str(raw.get('provider') or '').strip(),
        'email': email,
        'password': str(raw.get('password') or raw.get('IMAP_PASS') or raw.get('SMTP_PASS') or ''),
        'imapHost': str(raw.get('imapHost') or raw.get('IMAP_HOST') or ''),
        'imapPort': parse_port(raw.get('imapPort', raw.get('IMAP_PORT')), 993),
        'imapTls': parse_bool(raw.get('imapTls', raw.get('IMAP_TLS')), True),
        'imapRejectUnauthorized': parse_bool(
            raw.get('imapRejectUnauthorized', raw.get('IMAP_REJECT_UNAUTHORIZED')), True),
        'smtpHost': str(raw.get('smtpHost') or raw.get('SMTP_HOST') or ''),
        'smtpPort': parse_port(raw.get('smtpPort', raw.get('SMTP_PORT')), 587),
        'smtpSecure': parse_bool(raw.get('smtpSecure', raw.get('SMTP_SECURE')), False),
        'smtpRejectUnauthorized': parse_bool(
            raw.get('smtpRejectUnauthorized', raw.get('SMTP_REJECT_UNAUTHORIZED')), True),
        'smtpFrom': str(raw.get('smtpFrom') or raw.get('SMTP_FROM') or raw.get('SMTP_USER') or email),
        'mailbox': str(raw.get('mailbox') or raw.get('IMAP_MAILBOX') or 'INBOX'),
        'requireSendConfirmation': parse_bool(raw.get('requireSendConfirmation'), True),
    }


def normalize_accounts(raw_accounts):
    used = set()
    accounts = []
    for index, raw in enumerate(raw_accounts):
        account = normalize_account(raw, index)
        base = account['id']
        next_id = base
        suffix = 2
        while next_id in used:
            next_id = '%s-%d' % (base, suffix)
            suffix += 1
        used.add(next_id)
        account['id'] = next_id
        accounts.append(account)
    return accounts


def load_accounts_config():
    if os.environ.get('EMAIL_CONFIG_MODE') == 'env':
        env = load_legacy_env()
        return {
            'version': 1,
            'defaultAccountId': 'default',
            'accounts': [legacy_env_to_account(env)] if has_legacy_env(env) else [],
            'source': 'env',
        }

    if os.path.exists(ACCOUNTS_PATH):
        with open(ACCOUNTS_PATH, 'r', encoding='utf-8') as fh:
            parsed = json.load(fh)
        raw = parsed.get('accounts')
        accounts = normalize_accounts(raw) if isinstance(raw, list) else []
        return {
            'version': parsed.get('version') if isinstance(parsed.get('version'), int) else 1,
            'defaultAccountId': str(parsed.get('defaultAccountId') or (accounts[0]['id'] if accounts else '')),
            'accounts': accounts,
            'source': 'accounts',
        }

    env = load_legacy_env()
    return {
        'version': 1,
        'defaultAccountId': 'default',
        'accounts': [legacy_env_to_account(env)] if has_legacy_env(env) else [],
        'source': 'legacy-env',
    }


def list_enabled_accounts(config):
    return [a for a in config['accounts'] if a['enabled']]


def resolve_account(config, account_id=None):
    enabled = list_enabled_accounts(config)
    if not enabled:
        raise RuntimeError('No enabled email accounts configured')
    default = next((a for a in config['accounts'] if a['id'] == config['defaultAccountId']), None)
    target_id = account_id or (default['id'] if default and default['enabled'] else enabled[0]['id'])
    account = next((a for a in config['accounts'] if a['id'] == target_id), None)
    if not account:
        available = ', '.join(a['id'] for a in config['accounts']) or '(none)'
        raise RuntimeError('Email account "%s" not found. Available accounts: %s' % (target_id, available))
    if not account['enabled']:
        raise RuntimeError('Email account "%s" is disabled' % target_id)
    return account


def get_target_accounts(options):
    """options：含 'account' 和 'all_accounts' 两个键的字典。"""
    config = load_accounts_config()
    if options.get('all_accounts'):
        accounts = list_enabled_accounts(config)
        if not accounts:
            raise RuntimeError('No enabled email accounts configured')
        return config, accounts, True
    return config, [resolve_account(config, options.get('account'))], False


def redact_account(account):
    return {
        'id': account['id'],
        'name': redact_email(account['name']),
        'enabled': account['enabled'],
        'email': redact_email(account['email']),
        'imapHost': account['imapHost'],
        'imapPort': account['imapPort'],
        'smtpHost': account['smtpHost'],
        'smtpPort': account['smtpPort'],
        'hasPassword': bool(account['password']),
    }


def list_accounts_config():
    config = load_accounts_config()
    enabled = list_enabled_accounts(config)
    default = next((a for a in config['accounts'] if a['id'] == config['defaultAccountId']), None)
    effective_default = default if default and default['enabled'] else (enabled[0] if enabled else None)
    accounts = []
    for account in config['accounts']:
        entry = redact_account(account)
        entry.update({
            'isDefault': bool(effective_default and account['id'] == effective_default['id']),
            'hasImapConfig': bool(account['email'] and account['password'] and account['imapHost']),
            'hasSmtpConfig': bool(account['email'] and account['password'] and account['smtpHost']),
            'mailbox': account['mailbox'],
            'requireSendConfirmation': account['requireSendConfirmation'] is not False,
        })
        accounts.append(entry)
    return {
        'success': True,
        'source': config['source'],
        'defaultAccountId': effective_default['id'] if effective_default else '',
        'accounts': accounts,
    }


def with_account_result(account, result):
    merged = {
        'accountId': account['id'],
        'accountName': redact_email(account['name']),
        'email': redact_email(account['email']),
    }
    merged.update(result)
    return merged
