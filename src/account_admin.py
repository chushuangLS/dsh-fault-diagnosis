"""Local account maintenance. Run as the OS account that owns the data."""
import argparse
import getpass
import secrets

import audit
import auth
import repair_log
from filelock import file_lock

OPERATOR = {'id': 'local-maintenance', 'name': '本机维护'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('show-invite', 'rotate-invite'):
        commands.add_parser(command).add_argument('role', choices=['admin', 'member'])
    commands.add_parser('reset-password').add_argument('name')
    migrate = commands.add_parser('migrate-reporters')
    migrate.add_argument('name')
    migrate.add_argument('record_ids', nargs='+')
    args = parser.parse_args()
    auth.initialize()

    if args.command == 'migrate-reporters':
        name = auth.normalize_name(args.name)
        if not name:
            parser.error('请输入上报人姓名')
        try:
            count = repair_log.backfill_reporters(name, set(args.record_ids), OPERATOR)
        except ValueError as error:
            parser.error(str(error))
        print(f'已补登记 {count} 条记录')
        return

    if args.command == 'reset-password':
        path = auth._path('users.json')
        name = auth.normalize_name(args.name)
        password = getpass.getpass('新密码：')
        if not 6 <= len(password) <= 128 or password != getpass.getpass('确认密码：'):
            parser.error('两次密码必须相同，且为 6 至 128 个字符')
        with file_lock(str(path)):
            users = auth._read(path)
            match = next(((uid, u) for uid, u in users.items() if u['name'] == name), None)
            if not match:
                parser.error('未找到该账号')
            uid, user = match
            user['salt'] = secrets.token_hex(16)
            user['hash'] = auth.password_hash(password, user['salt'])
            auth._write(path, users)
        event = audit.make_event(OPERATOR, 'reset_password', target_user_id=uid)
    else:
        path = auth._path('invites.json')
        key = args.role + '_code'
        with file_lock(str(path)):
            codes = auth._read(path)
            if args.command == 'show-invite':
                print(codes[key])
                return
            code = auth.new_invite(set(codes.values()))
            codes[key] = code
            auth._write(path, codes)
        event = audit.make_event(OPERATOR, 'rotate_invite', role=args.role)

    audit.append(audit.log_path(repair_log.RECORD_FILE), event)
    print('操作成功')


if __name__ == '__main__':
    main()
