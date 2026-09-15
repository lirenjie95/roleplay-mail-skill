#!/usr/bin/env python3
"""SMTP 命令（Python 3.7+，仅标准库）。

本文件移植自网易有道 LobsterAI 项目的 imap-smtp-email skill
（https://github.com/netease-youdao/LobsterAI/tree/main/SKILLs/imap-smtp-email），
原作 NetEase，Node.js 实现，MIT License。

用法：
  python scripts/smtp.py accounts
  python scripts/smtp.py send --to <邮箱> --subject <标题> --confirmed [选项]
  python scripts/smtp.py test [--account id]
"""

import argparse
import email.utils
import json
import mimetypes
import os
import smtplib
import socket
import ssl
import sys
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402

socket.setdefaulttimeout(30)


def fail(message):
    print(json.dumps({'success': False, 'error': str(message)}, ensure_ascii=False))
    sys.exit(1)


def split_addresses(value):
    if not value:
        return []
    return [item.strip() for item in str(value).split(',') if item.strip()]


def open_smtp(account):
    if not account['smtpHost'] or not account['email'] or not account['password']:
        raise RuntimeError('Missing SMTP configuration for account "%s"' % account['id'])
    port = account['smtpPort'] or 587
    context = ssl.create_default_context()
    if not account['smtpRejectUnauthorized']:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    if account['smtpSecure']:
        server = smtplib.SMTP_SSL(account['smtpHost'], port, context=context, timeout=30)
    else:
        server = smtplib.SMTP(account['smtpHost'], port, timeout=30)
        server.ehlo()
        try:
            server.starttls(context=context)
            server.ehlo()
        except smtplib.SMTPNotSupportedError:
            pass  # 内网明文中继（25/587 端口）不支持 STARTTLS 时直接跳过
    server.login(account['email'], account['password'])
    return server


def resolve_recipients(args, config):
    if args.get('to_account'):
        target = cfg.resolve_account(config, args['to_account'])
        return [target['email']]
    return split_addresses(args.get('to'))


def cmd_accounts(_args):
    print(json.dumps(cfg.list_accounts_config(), ensure_ascii=False, indent=2))


def cmd_send(args):
    config = cfg.load_accounts_config()
    account = cfg.resolve_account(config, args.get('account'))

    if account['requireSendConfirmation'] is not False and not args.get('confirmed'):
        fail('Sending requires --confirmed after the user confirms recipient, subject and body.')

    to_list = resolve_recipients(args, config)
    cc_list = split_addresses(args.get('cc'))
    bcc_list = split_addresses(args.get('bcc'))
    if not to_list and not cc_list and not bcc_list:
        fail('No recipients: pass --to, --to-account, --cc or --bcc.')

    if args.get('subject_file'):
        with open(args['subject_file'], 'r', encoding='utf-8') as fh:
            subject = fh.read().strip()
    else:
        subject = args.get('subject')
    if not subject:
        fail('Missing --subject or --subject-file.')

    body = args.get('body') or ''
    is_html = bool(args.get('html'))
    if args.get('body_file'):
        with open(args['body_file'], 'r', encoding='utf-8') as fh:
            body = fh.read()
    if args.get('html_file'):
        with open(args['html_file'], 'r', encoding='utf-8') as fh:
            body = fh.read()
        is_html = True

    msg = EmailMessage()
    sender = args.get('from') or account['smtpFrom'] or account['email']
    msg['From'] = sender
    if to_list:
        msg['To'] = ', '.join(to_list)
    if cc_list:
        msg['Cc'] = ', '.join(cc_list)
    msg['Subject'] = subject
    msg['Date'] = email.utils.formatdate(localtime=True)
    msg['Message-ID'] = email.utils.make_msgid('mail-tool')

    if is_html:
        msg.add_alternative(body, subtype='html')
    else:
        msg.set_content(body)

    for path in split_addresses(args.get('attach')):
        if not os.path.isfile(path):
            fail('Attachment not found: %s' % path)
        ctype, _ = mimetypes.guess_type(path)
        maintype, subtype = (ctype or 'application/octet-stream').split('/', 1)
        with open(path, 'rb') as fh:
            msg.add_attachment(fh.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(path))

    recipients = to_list + cc_list + bcc_list
    server = None
    try:
        server = open_smtp(account)
        refused = server.send_message(msg, from_addr=sender, to_addrs=recipients)
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass

    result = {
        'command': 'send',
        'to': to_list,
        'cc': cc_list,
        'bcc': ['[hidden]'] * len(bcc_list),
        'subject': subject,
        'from': cfg.redact_email(sender),
        'messageId': msg['Message-ID'],
        'note': 'SMTP server accepted the message; this does not guarantee inbox delivery.',
        'rejected': refused,
    }
    print(json.dumps({'success': True, **cfg.with_account_result(account, result)},
                     ensure_ascii=False, indent=2))


def cmd_test(args):
    config = cfg.load_accounts_config()
    account = cfg.resolve_account(config, args.get('account'))
    msg = EmailMessage()
    sender = account['smtpFrom'] or account['email']
    msg['From'] = sender
    msg['To'] = account['email']
    msg['Subject'] = 'mail-tool SMTP test'
    msg['Date'] = email.utils.formatdate(localtime=True)
    msg.set_content('This is a mail-tool SMTP connectivity test. If you received this, SMTP works.')
    server = None
    try:
        server = open_smtp(account)
        refused = server.send_message(msg, from_addr=sender, to_addrs=[account['email']])
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass
    print(json.dumps({'success': True, 'command': 'test',
                      **cfg.with_account_result(account, {
                          'to': cfg.redact_email(account['email']),
                          'note': 'Test email submitted to the SMTP server.',
                          'rejected': refused,
                      })}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(prog='smtp.py')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('accounts')
    p.add_argument('--account')
    p.add_argument('--all-accounts', action='store_true')

    p = sub.add_parser('send')
    p.add_argument('--account')
    p.add_argument('--to')
    p.add_argument('--to-account', dest='to_account')
    p.add_argument('--subject')
    p.add_argument('--subject-file', dest='subject_file')
    p.add_argument('--body')
    p.add_argument('--body-file', dest='body_file')
    p.add_argument('--html', action='store_true')
    p.add_argument('--html-file', dest='html_file')
    p.add_argument('--cc')
    p.add_argument('--bcc')
    p.add_argument('--attach')
    p.add_argument('--from', dest='from_')
    p.add_argument('--confirmed', action='store_true')

    p = sub.add_parser('test')
    p.add_argument('--account')

    ns = parser.parse_args()
    args = vars(ns)
    if 'from_' in args:
        args['from'] = args.pop('from_')

    handlers = {'accounts': cmd_accounts, 'send': cmd_send, 'test': cmd_test}
    try:
        handlers[ns.command](args)
    except (RuntimeError, smtplib.SMTPException, OSError, ValueError) as exc:
        fail(exc)


if __name__ == '__main__':
    main()
