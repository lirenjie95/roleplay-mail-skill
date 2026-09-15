---
name: roleplay-mail-skill
description: 自包含的"角色扮演邮件值班"服务，agent 类型无关（Kimi Code、Claude Code、Codex、DeepSeek Harness、opencode 等任意支持 SKILL.md 标准的 coding agent 均可使用）：内置 IMAP/SMTP 收发脚本（纯 Python 3 标准库），轮询指定发件人发来的、标题含「【LLM服务请求】」的未读邮件，下载附件到项目 .agent/downloads，以配置的角色人格（技术专家、日本牛郎、科比、张雪峰、东北雨姐、领导、算命大师、秘书、丁真、姜萍）执行正文任务并回信，产出文件作为附件回传。全程不询问用户，有疑问直接回信提问。当用户要求检查/处理服务请求邮件、跑邮件值班服务，或单纯收发邮件时使用。
version: 4.0.0
---

# Roleplay Mail Skill（自包含版）

一个"邮件值班"服务：内置邮件收发能力（`scripts/imap.py` / `smtp.py`，
**纯 Python 3 标准库，3.7+ 即可，零依赖零安装**），检查未读的
**服务请求邮件**，扮演配置的角色完成任务并回信。

**agent 类型无关**：本 skill 遵循开放的 Agent Skills（SKILL.md）标准，不依赖
任何特定 agent 运行时，只要求 agent 能读本文档、执行 shell 命令、读写项目
文件。已验证可用于 Kimi Code、Claude Code、Codex、DeepSeek Harness、
opencode、OpenClaw 等支持该标准的 coding agent。

本文档中的相对路径都相对**本 SKILL.md 所在目录**（即 skill 根目录）。
路径统一用正斜杠书写：Windows 的 Python 和 shell 同样接受 `scripts/imap.py`
这种写法，macOS/Linux 则必须使用正斜杠。

## 第一部分：邮箱配置

把 `.env.example` 复制为本目录下的 `.env` 并修改：

```bash
# IMAP（收邮件）
IMAP_HOST=mail.intranet.local     # 服务器地址
IMAP_PORT=993                     # 993=TLS，143=明文
IMAP_USER=your@email.com
IMAP_PASS=your_password
IMAP_TLS=true
IMAP_REJECT_UNAUTHORIZED=false    # 内网自签名证书设 false
IMAP_MAILBOX=INBOX

# SMTP（发邮件）
SMTP_HOST=mail.intranet.local
SMTP_PORT=465                     # 465=SSL，587=STARTTLS，25=明文
SMTP_SECURE=true                  # 465 用 true，其余 false
SMTP_USER=your@email.com
SMTP_PASS=your_password
SMTP_FROM=your@email.com
SMTP_REJECT_UNAUTHORIZED=false    # 内网自签名证书设 false
```

多账号：在本目录建 `accounts.json`（`{"defaultAccountId": "...", "accounts": [{...}]}`，
字段名同 `.env` 的对应小驼峰形式），优先于 `.env`；`EMAIL_CONFIG_MODE=env`
可强制只用 `.env`。

不要在回复中展示 `.env` / `accounts.json` 内容；脚本输出中的账号信息已打码，
引用时用打码后的形式。不要让用户在对话里发密码，让他自己改配置文件。

## 第二部分：服务配置（两层）

**全局配置**：本目录的 `service.config.json`——角色库和默认行为：

| 字段 | 含义 |
|---|---|
| `subjectKeyword` | 标题必须包含的关键字，默认 `【LLM服务请求】` |
| `attachmentRoot` | 附件/产物保存目录（相对项目根目录），默认 `.agent/downloads` |
| `defaultRole` | 各级配置都没指定角色时使用的人格 id |
| `markReadAfterReply` | 回信后把邮件标记为已读（防重复处理） |
| `pollIntervalMinutes` | 值班轮询间隔（分钟），`0` 或缺省 = 不自动轮询，只在用户要求时跑一轮 |
| `signatureTemplate` | 所有回信末尾的统一署名，`{role}` 替换为实际角色的 `name` |
| `roles` | 人格列表：`id`、`name`、`aliases`、`persona`（人格指令） |

**项目配置**：`<项目>/.agent/roleplay.config`——写这个项目**具体的邮件
地址和角色**。本目录的 `roleplay.config.example` 是模板，部署时拷到项目里
改名修改：

```json
{
  "watchFrom": "boss@intranet.local",
  "role": "日本牛郎",
  "pollIntervalMinutes": 30
}
```

- `watchFrom`：只处理来自这个发件人的邮件（必填，否则本轮无事）。
- `role`：本项目固定使用的角色（匹配 `roles` 的 `name` 或 `aliases`，
  不区分大小写）。可不填，由邮件标题指定。
- `pollIntervalMinutes`：本项目的值班轮询间隔（分钟），覆盖全局配置。
  `0` 或缺省 = 不自动轮询。

项目根目录 = 当前工作目录。查找顺序：`./.agent/roleplay.config` →
`./.claude/roleplay.config`（兼容旧部署）→ `./roleplay.config`。都没有 →
报告"项目未配置 roleplay.config"，把 `roleplay.config.example` 的用法告诉
用户即可（这属于部署引导，不是运行期提问）。

## 第三部分：值班全流程

### 1. 读取两层配置

读本目录的 `service.config.json`，再读项目配置并合并：项目配置的
`watchFrom` / `role` / `pollIntervalMinutes` 生效，其余字段用全局配置。
`attachmentRoot` 解析为**项目根目录下**的路径。

**自动忽略产物目录**：若项目根目录是 git 仓库（存在 `.git`），检查项目的
`.gitignore` 是否已忽略 `attachmentRoot`（如 `.agent/downloads/`）；没有就
追加一行。附件和产物不应进版本库，这一步每次值班都做，已忽略则跳过。

**轮询调度**：`pollIntervalMinutes` 大于 0 且用户要求"持续值班"时，用当前
平台的定时能力（agent 的定时任务、cron、计划任务、定时提醒等，有什么用什么）
按该间隔周期性触发本流程；为 `0` 或缺省时不自作主张，只在用户明确要求时
跑一轮。本服务本身是"一轮一跑"的模式，间隔只是给调度方的提示。

### 2. 找未读请求邮件

```bash
python scripts/imap.py search --unseen --from <watchFrom> --subject <subjectKeyword>
```

没有结果就是"本轮无事"，直接报告即可，不要做多余操作。

### 3. 逐封处理（每封邮件一个 UID）

取正文与真实发件地址：

```bash
python scripts/imap.py fetch <uid>
```

下载全部附件到项目内（按 UID 分目录，防覆盖）：

```bash
python scripts/imap.py download <uid> --dir <attachmentRoot>/<uid>
```

### 4. 选定人格

优先级：**邮件标题 > 项目配置 > 全局默认**。

- 标题格式约定：`【LLM服务请求】<角色名>`。用关键字后的文字匹配 `roles`
  的 `name` 或 `aliases`（不区分大小写）。
- 标题没写 → 用项目配置的 `role`；还没配 → 用 `defaultRole`。
- 写了但匹配不上 → 属于"不清楚"，按第 6 步回信询问可选角色列表，不要用
  默认角色硬演。

之后**全程以该人格的口吻工作**：`persona` 是行为准则。人格只改变表达
风格，**任务的实质完成度不能打折**。

**回信署名是统一的，与人格无关**：正文写完后，在末尾单独一行拼上
`signatureTemplate`，把 `{role}` 替换为实际角色的 `name`（如"日本牛郎"）。
不要加任何其他落款、昵称——脚本本身不加署名，信里出现什么署名完全取决于
你写的正文。

### 5. 执行正文中的任务

正文就是要执行的命令/任务描述。用当前 agent 的完整能力去做：跑命令、写
代码、分析刚下载的附件、读项目文件，都可以。

**所有改动和产出不许出项目仓库**：下载的附件、临时文件、生成的结果文件，
一律放在项目内（附件与产物放 `<attachmentRoot>/`，回信正文临时文件也放
那里）；不写本 skill 目录，不写系统临时目录，不碰项目以外的路径。

任务如果产生了结果文件（代码包、报表、图片等），**作为回信附件**用
`--attach` 发回给收件人，正文里说明每个文件是什么。

边界：

- 只执行 `watchFrom` 发来的、标题含关键字且未读的邮件里的指令——这三重
  条件就是全部授权边界，不要扩大。
- 明显危险或不可逆的操作（删库、格式化、对外发布）即使邮件里要求了，
  也不要做；回信说明拒绝原因。

### 6. 不清楚的地方：回信问，不问用户

**禁止使用任何形式的就地交互提问**（各 agent 的提问工具，如 AskUserQuestion、
request_user_input、交互式确认等，一律不用）。任何歧义（角色名不认识、
任务描述缺参数、附件打不开、正文为空等）都直接回信给对方，列出问题清单，
请对方补充后重新发一封请求邮件。回信同样需要 `--confirmed`。

### 7. 回信

回信正文建议先写到 `<attachmentRoot>/<uid>/reply.txt`，再：

```bash
python scripts/smtp.py send --to <发件人> --subject "Re: <原标题>" --body-file <正文文件> [--attach <文件1,文件2>] --confirmed
```

`--confirmed` 在此直接传入：请求方通过"往这个邮箱发带关键字的邮件"已经
完成了授权与确认，本服务的设计就是不打扰本机用户（`.env` 里
`EMAIL_REQUIRE_SEND_CONFIRMATION` 的交互确认语义由第 6 步的回信机制替代）。

回信后标记已读（`markReadAfterReply` 为 true 时）：

```bash
python scripts/imap.py mark-read <uid>
```

**必须先回信成功，再标记已读。** 回信失败的邮件保持未读，下轮重试。

### 8. 汇报

最后向本机用户简报本轮处理了几封、各自的角色与结果摘要、回传的附件、
SMTP 结果。SMTP `success` 只代表服务器已受理，不要宣称"对方已收到"。

## 附：邮件命令速查（也可单独当邮件工具用）

收信（IMAP）：

```bash
python scripts/imap.py accounts                                  # 列出配置的账号（打码）
python scripts/imap.py check [--limit 10] [--recent 2h]          # 未读邮件
python scripts/imap.py fetch <uid>                               # 取正文
python scripts/imap.py download <uid> [--dir 目录] [--file 名]   # 下附件
python scripts/imap.py search [--unseen] [--from x] [--subject x] [--since 日期] [--limit 20]
python scripts/imap.py mark-read <uid> [uid2 ...]
python scripts/imap.py mark-unread <uid> [uid2 ...]
python scripts/imap.py list-mailboxes
```

发信（SMTP）：

```bash
python scripts/smtp.py accounts
python scripts/smtp.py send --to <地址> --subject <标题> --confirmed \
    [--body 文本 | --body-file 文件 | --html-file 文件] \
    [--cc x] [--bcc x] [--attach 文件1,文件2] [--account id]
python scripts/smtp.py test                                      # 给自己发测试信
```

注意：发信 `success: true` 只代表 SMTP 服务器已受理，不代表对方已收到。
`--subject` 支持中文；多收件人用英文逗号分隔。

## 排错

- 连接超时 → 确认服务器地址/端口，本机能否 ping 通、端口是否通。
- 认证失败 → 用户名一般要完整邮箱地址（有的内网服务器只要账号名）；
  公共邮箱（163/QQ/Gmail）要用授权码/应用专用密码，不是登录密码。
- TLS 错误 → 端口与加密方式要匹配（993/465=直接 TLS，143/587/25=明文或
  STARTTLS）；内网自签名证书设 `IMAP_REJECT_UNAUTHORIZED=false` /
  `SMTP_REJECT_UNAUTHORIZED=false`。
- `python` 命令不存在 → 需要 Python 3.7+（只用标准库，任何发行版均可）。
- 附件下载目录写不进去 → 检查 `attachmentRoot` 是否解析到了项目内预期位置。

## 致谢与来源

邮件收发脚本（`scripts/config.py` / `imap.py` / `smtp.py`）移植自网易有道
[LobsterAI](https://github.com/netease-youdao/LobsterAI) 项目的
[`imap-smtp-email`](https://github.com/netease-youdao/LobsterAI/tree/main/SKILLs/imap-smtp-email)
skill（作者 NetEase，MIT License），由 Node.js 改写为纯 Python 标准库实现，
去掉了 npm 依赖。多账号配置（`accounts.json`）、环境变量（`EMAIL_CONFIG_MODE`
等）与输出格式保持与上游兼容。详见 README 的 Credits 一节。
