#!/usr/bin/env python3
"""IMAP 命令（Python 3.7+，仅标准库）。

本文件移植自网易有道 LobsterAI 项目的 imap-smtp-email skill
（https://github.com/netease-youdao/LobsterAI/tree/main/SKILLs/imap-smtp-email），
原作 NetEase，Node.js 实现，MIT License。

用法：
  python scripts/imap.py accounts
  python scripts/imap.py check [--limit 10] [--mailbox INBOX] [--recent 2h] [--account id] [--all-accounts]
  python scripts/imap.py fetch <uid> [--mailbox INBOX] [--account id]
  python scripts/imap.py download <uid> [--mailbox INBOX] [--dir 目录] [--file 文件名] [--account id]
  python scripts/imap.py search [--unseen|--seen] [--from 地址] [--subject 关键字] [--recent 2h]
                                [--since YYYY-MM-DD] [--before YYYY-MM-DD] [--limit 20]
                                [--mailbox INBOX] [--account id] [--all-accounts]
  python scripts/imap.py mark-read <uid> [uid2 ...] [--account id]
  python scripts/imap.py mark-unread <uid> [uid2 ...] [--account id]
  python scripts/imap.py list-mailboxes [--account id] [--all-accounts]
"""

import argparse
import email
import email.header
import email.utils
import imaplib
import json
import os
import re
import socket
import ssl
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg  # noqa: E402

socket.setdefaulttimeout(30)


def fail(message):
    print(json.dumps({'success': False, 'error': str(message)}, ensure_ascii=False))
    sys.exit(1)


def decode_header_value(value):
    if not value:
        return ''
    parts = []
    try:
        for text, charset in email.header.decode_header(value):
            if isinstance(text, bytes):
                parts.append(text.decode(charset or 'utf-8', errors='replace'))
            else:
                parts.append(text)
    except Exception:
        return str(value)
    return ''.join(parts)


def parse_recent(value):
    match = re.match(r'^(\d+)([mhd])$', str(value or '').strip())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    seconds = amount * {'m': 60, 'h': 3600, 'd': 86400}[unit]
    return datetime.now() - timedelta(seconds=seconds)


def imap_date(dt):
    return dt.strftime('%d-%b-%Y')


def connect(account):
    if not account['email'] or not account['password']:
        raise RuntimeError('Missing IMAP credentials for account "%s"' % account['id'])
    host = account['imapHost'] or '127.0.0.1'
    port = account['imapPort'] or 1143
    if account['imapTls']:
        context = ssl.create_default_context()
        if not account['imapRejectUnauthorized']:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=context)
    else:
        conn = imaplib.IMAP4(host, port)
    conn.login(account['email'], account['password'])
    return conn


def open_mailbox(conn, mailbox, readonly=True):
    status, _ = conn.select(mailbox, readonly=readonly)
    if status != 'OK':
        raise RuntimeError('Cannot open mailbox "%s"' % mailbox)


def uid_search(conn, criteria):
    status, data = conn.uid('SEARCH', None, *criteria)
    if status != 'OK':
        raise RuntimeError('IMAP search failed')
    raw = data[0].decode('ascii', errors='replace') if data and data[0] else ''
    return [u for u in raw.split() if u]


def fetch_headers(conn, uids):
    """返回 {uid: {uid, from, subject, date, messageId}}，最新的排最后。"""
    result = {}
    if not uids:
        return result
    id_set = ','.join(uids)
    status, data = conn.uid('FETCH', id_set, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])')
    if status != 'OK':
        raise RuntimeError('IMAP header fetch failed')
    current_uid = None
    for item in data:
        if not isinstance(item, tuple):
            continue
        meta, blob = item
        match = re.search(rb'UID (\d+)', meta if isinstance(meta, bytes) else str(meta).encode())
        if match:
            current_uid = match.group(1).decode()
        if current_uid is None:
            continue
        msg = email.message_from_bytes(blob)
        result[current_uid] = {
            'uid': current_uid,
            'from': decode_header_value(msg.get('From')),
            'subject': decode_header_value(msg.get('Subject')),
            'date': msg.get('Date') or '',
            'messageId': (msg.get('Message-ID') or '').strip(),
        }
    return result


def fetch_message(conn, uid):
    status, data = conn.uid('FETCH', uid, '(BODY.PEEK[])')
    if status != 'OK' or not data or not isinstance(data[0], tuple):
        raise RuntimeError('Message uid %s not found' % uid)
    return email.message_from_bytes(data[0][1])


def extract_text(msg):
    """优先取 text/plain；没有则退化为去掉标签的 text/html。"""
    plain, html = [], []
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        if part.get_filename():
            continue
        ctype = part.get_content_type()
        try:
            payload = part.get_payload(decode=True) or b''
        except Exception:
            continue
        charset = part.get_content_charset() or 'utf-8'
        text = payload.decode(charset, errors='replace')
        if ctype == 'text/plain':
            plain.append(text)
        elif ctype == 'text/html':
            html.append(text)
    if plain:
        return '\n'.join(plain), 'plain'
    if html:
        stripped = re.sub(r'<[^>]+>', ' ', '\n'.join(html))
        return re.sub(r'\s+', ' ', stripped).strip(), 'html'
    return '', 'none'


def list_attachments(msg):
    result = []
    for part in msg.walk():
        filename = part.get_filename()
        if not filename:
            continue
        filename = decode_header_value(filename)
        payload = part.get_payload(decode=True)
        result.append({
            'filename': filename,
            'contentType': part.get_content_type(),
            'size': len(payload) if payload else 0,
        })
    return result


def safe_filename(name):
    name = os.path.basename(str(name or 'attachment')).strip().replace('\\', '_').replace('/', '_')
    name = re.sub(r'[\x00-\x1f<>:"|?*]', '_', name)
    return name or 'attachment'


def build_criteria(args):
    criteria = []
    if args.get('unseen'):
        criteria.append('UNSEEN')
    elif args.get('seen'):
        criteria.append('SEEN')
    else:
        criteria.append('ALL')
    if args.get('from'):
        criteria.extend(['FROM', '"%s"' % args['from'].replace('"', '')])
    since_dt = None
    if args.get('recent'):
        since_dt = parse_recent(args['recent'])
        if since_dt is None:
            raise RuntimeError('Invalid --recent value, use e.g. 30m, 2h, 7d')
    elif args.get('since'):
        since_dt = datetime.strptime(args['since'], '%Y-%m-%d')
    if since_dt:
        criteria.extend(['SINCE', imap_date(since_dt)])
    if args.get('before'):
        criteria.extend(['BEFORE', imap_date(datetime.strptime(args['before'], '%Y-%m-%d'))])
    return criteria


def cmd_accounts(_args):
    print(json.dumps(cfg.list_accounts_config(), ensure_ascii=False, indent=2))


def cmd_list_mailboxes(args):
    config, accounts, all_accounts = cfg.get_target_accounts(args)
    results = []
    for account in accounts:
        conn = None
        try:
            conn = connect(account)
            status, boxes = conn.list()
            names = []
            for box in boxes or []:
                line = box.decode('utf-8', errors='replace') if isinstance(box, bytes) else str(box)
                match = re.search(r'"[^"]*"\s+"?([^"]+)"?$', line)
                names.append(match.group(1) if match else line.split()[-1])
            results.append(cfg.with_account_result(account, {'mailboxes': names, 'count': len(names)}))
        finally:
            if conn:
                try:
                    conn.logout()
                except Exception:
                    pass
    print(json.dumps({'success': True, 'command': 'list-mailboxes', 'results': results}, ensure_ascii=False, indent=2))


def cmd_check(args):
    args = dict(args)
    args['unseen'] = True
    _run_search(args, command='check')


def cmd_search(args):
    _run_search(args, command='search')


def _run_search(args, command):
    config, accounts, all_accounts = cfg.get_target_accounts(args)
    limit = int(args.get('limit') or (10 if command == 'check' else 20))
    subject_filter = (args.get('subject') or '').lower()
    results = []
    for account in accounts:
        conn = None
        try:
            conn = connect(account)
            open_mailbox(conn, args.get('mailbox') or 'INBOX')
            uids = uid_search(conn, build_criteria(args))
            headers = fetch_headers(conn, uids)
            messages = sorted(headers.values(), key=lambda m: int(m['uid']), reverse=True)
            if subject_filter:
                messages = [m for m in messages if subject_filter in (m['subject'] or '').lower()]
            messages = messages[:limit]
            results.append(cfg.with_account_result(account, {'messages': messages, 'count': len(messages)}))
        finally:
            if conn:
                try:
                    conn.logout()
                except Exception:
                    pass
    print(json.dumps({'success': True, 'command': command, 'results': results}, ensure_ascii=False, indent=2))


def cmd_fetch(args):
    config, accounts, _ = cfg.get_target_accounts(args)
    account = accounts[0]
    conn = None
    try:
        conn = connect(account)
        open_mailbox(conn, args.get('mailbox') or 'INBOX')
        msg = fetch_message(conn, args['uid'])
        body, body_type = extract_text(msg)
        result = {
            'uid': str(args['uid']),
            'from': decode_header_value(msg.get('From')),
            'to': decode_header_value(msg.get('To')),
            'cc': decode_header_value(msg.get('Cc')),
            'subject': decode_header_value(msg.get('Subject')),
            'date': msg.get('Date') or '',
            'messageId': (msg.get('Message-ID') or '').strip(),
            'bodyType': body_type,
            'body': body,
            'attachments': list_attachments(msg),
        }
        print(json.dumps({'success': True, 'command': 'fetch', **cfg.with_account_result(account, result)},
                         ensure_ascii=False, indent=2))
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                pass


def cmd_download(args):
    config, accounts, _ = cfg.get_target_accounts(args)
    account = accounts[0]
    out_dir = args.get('dir') or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    only = args.get('file')
    saved = []
    conn = None
    try:
        conn = connect(account)
        open_mailbox(conn, args.get('mailbox') or 'INBOX')
        msg = fetch_message(conn, args['uid'])
        for part in msg.walk():
            filename = part.get_filename()
            if not filename:
                continue
            filename = decode_header_value(filename)
            if only and filename != only:
                continue
            payload = part.get_payload(decode=True) or b''
            safe = safe_filename(filename)
            path = os.path.join(out_dir, safe)
            base, ext = os.path.splitext(safe)
            n = 2
            while os.path.exists(path):
                path = os.path.join(out_dir, '%s-%d%s' % (base, n, ext))
                n += 1
            with open(path, 'wb') as fh:
                fh.write(payload)
            saved.append({'filename': filename, 'savedAs': os.path.basename(path),
                          'path': os.path.abspath(path), 'size': len(payload)})
        if only and not saved:
            raise RuntimeError('Attachment "%s" not found in message %s' % (only, args['uid']))
        print(json.dumps({'success': True, 'command': 'download',
                          **cfg.with_account_result(account, {'saved': saved, 'count': len(saved),
                                                              'dir': os.path.abspath(out_dir)})},
                         ensure_ascii=False, indent=2))
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                pass


def _mark(args, seen):
    config, accounts, _ = cfg.get_target_accounts(args)
    account = accounts[0]
    conn = None
    try:
        conn = connect(account)
        open_mailbox(conn, args.get('mailbox') or 'INBOX', readonly=False)
        uid_set = ','.join(str(u) for u in args['uids'])
        flag_cmd = '+FLAGS' if seen else '-FLAGS'
        status, _ = conn.uid('STORE', uid_set, flag_cmd, '(\\Seen)')
        if status != 'OK':
            raise RuntimeError('IMAP store failed')
        print(json.dumps({'success': True,
                          'command': 'mark-read' if seen else 'mark-unread',
                          **cfg.with_account_result(account, {'uids': [str(u) for u in args['uids']]})},
                         ensure_ascii=False, indent=2))
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                pass


def cmd_mark_read(args):
    _mark(args, True)


def cmd_mark_unread(args):
    _mark(args, False)


def main():
    parser = argparse.ArgumentParser(prog='imap.py')
    sub = parser.add_subparsers(dest='command', required=True)

    def common(p, account=True, mailbox=False):
        if account:
            p.add_argument('--account')
            p.add_argument('--all-accounts', action='store_true')
        if mailbox:
            p.add_argument('--mailbox')

    common(sub.add_parser('accounts'))
    common(sub.add_parser('list-mailboxes'), mailbox=False)

    p = sub.add_parser('check')
    common(p, mailbox=True)
    p.add_argument('--limit', type=int)
    p.add_argument('--recent')

    p = sub.add_parser('fetch')
    common(p, mailbox=True)
    p.add_argument('uid')

    p = sub.add_parser('download')
    common(p, mailbox=True)
    p.add_argument('uid')
    p.add_argument('--dir')
    p.add_argument('--file')

    p = sub.add_parser('search')
    common(p, mailbox=True)
    p.add_argument('--unseen', action='store_true')
    p.add_argument('--seen', action='store_true')
    p.add_argument('--from', dest='from_')
    p.add_argument('--subject')
    p.add_argument('--recent')
    p.add_argument('--since')
    p.add_argument('--before')
    p.add_argument('--limit', type=int)

    for name in ('mark-read', 'mark-unread'):
        p = sub.add_parser(name)
        common(p, mailbox=True)
        p.add_argument('uids', nargs='+')

    ns = parser.parse_args()
    args = vars(ns)
    args['all_accounts'] = args.pop('all_accounts', False)
    if 'from_' in args:
        args['from'] = args.pop('from_')

    handlers = {
        'accounts': cmd_accounts,
        'list-mailboxes': cmd_list_mailboxes,
        'check': cmd_check,
        'fetch': cmd_fetch,
        'download': cmd_download,
        'search': cmd_search,
        'mark-read': cmd_mark_read,
        'mark-unread': cmd_mark_unread,
    }
    try:
        handlers[ns.command](args)
    except (RuntimeError, imaplib.IMAP4.error, OSError, ValueError) as exc:
        fail(exc)


if __name__ == '__main__':
    main()
