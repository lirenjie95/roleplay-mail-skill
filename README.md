# roleplay-mail-skill

一个"角色扮演邮件值班" agent skill：让任意 coding agent 守着指定邮箱，收到
**服务请求邮件**后，以配置好的角色人格（技术专家、日本牛郎、领导、算命大师、
秘书、科比、张雪峰、东北雨姐、丁真、姜萍）执行邮件正文里的任务，把结果
（含产物文件）作为回信发回去。

全程不打扰本机用户——有疑问直接回信问发件人，而不是就地弹窗提问。

## 特性

- **零依赖**：邮件收发脚本为纯 Python 3 标准库实现（3.7+），不需要 `pip install`
  任何东西，也不需要 Node.js。
- **agent 类型无关**：遵循开放的 Agent Skills（SKILL.md）标准，可用于
  Kimi Code、Claude Code、Codex CLI、DeepSeek Harness（dsh）、opencode、
  OpenClaw 等支持该标准的 coding agent。
- **多账号**：支持 `accounts.json` 多邮箱账号配置，兼容 `.env` 单账号。
- **安全第一**：发信需要 `--confirmed` 显式确认；只处理指定发件人 + 指定标题
  关键字 + 未读三重条件命中的邮件；账号信息在输出中自动打码。
- **人格扮演**：内置 10 个角色人格，人格只改表达风格，任务完成度不打折；
  回信末尾统一署名，可一眼看出是哪个"角色"办的差事。
- **可测试**：自带纯标准库 unittest 测试（`tests/`）和 GitHub Actions
  流水线（多系统、多 Python 版本）。

## 安装

需要 Python 3.7+（任何发行版，只用标准库）。

```bash
git clone <本仓库地址>
cd roleplay-mail-skill
python install.py
```

安装脚本会：

1. 检查 Python 版本；
2. 从 `.env.example` 复制生成 `.env`（已存在则不覆盖）；
3. 对邮件脚本做语法检查；
4. 自动探测本机已安装的 agent 的技能目录（Kimi Code `~/.agents/skills`、
   Claude Code `~/.claude/skills`、Codex `$CODEX_HOME/skills`（默认
   `~/.codex/skills`）、DeepSeek Harness `~/.dsh/skills`、opencode
   `~/.opencode/skills`、OpenClaw `~/.openclaw/skills` 等），确认后把
   skill 复制进去。

常用参数：

```bash
python install.py --yes           # 免确认，装到所有探测到的目录
python install.py --target DIR    # 装到指定技能目录（可重复）
python install.py --no-skill      # 只做本地初始化，不复制
python install.py --force         # 覆盖已存在的安装副本
```

也可以完全手动：把整个目录复制到任意 agent 的技能目录即可，无需任何构建。

## 配置

### 1. 邮箱账号（skill 目录内）

把 `.env.example` 复制为 `.env` 并填写（安装脚本已帮你复制）：

```bash
# IMAP（收邮件）
IMAP_HOST=mail.example.com      # 993=TLS，143=明文
IMAP_PORT=993
IMAP_USER=your@email.com
IMAP_PASS=your_password
IMAP_TLS=true
IMAP_REJECT_UNAUTHORIZED=false  # 内网自签名证书设 false

# SMTP（发邮件）
SMTP_HOST=mail.example.com      # 465=SSL，587=STARTTLS，25=明文
SMTP_PORT=465
SMTP_SECURE=true
SMTP_USER=your@email.com
SMTP_PASS=your_password
SMTP_FROM=your@email.com
```

多账号用 `accounts.json`（优先于 `.env`），公共邮箱（163/QQ/Gmail）请用
授权码/应用专用密码而非登录密码。

### 2. 服务行为（skill 目录内 `service.config.json`）

角色库、标题关键字（默认 `【LLM服务请求】`）、附件目录（默认项目内
`.agent/downloads`）、默认角色、轮询间隔（`pollIntervalMinutes`，`0` =
不自动轮询）、回信署名模板等。值班时若项目在 git 仓库里，附件目录会被
自动追加进项目的 `.gitignore`。

### 3. 项目配置（需要值班的项目内）

把 `roleplay.config.example` 复制到项目里，改名为
`.agent/roleplay.config`：

```json
{
  "watchFrom": "boss@example.com",
  "role": "日本牛郎",
  "pollIntervalMinutes": 30
}
```

- `watchFrom`：只处理这个发件人的邮件（必填）。
- `role`：本项目固定角色（可省，由邮件标题 `【LLM服务请求】<角色名>` 指定）。
- `pollIntervalMinutes`：本项目值班轮询间隔（分钟，覆盖全局配置），
  如 `30` 表示让 agent 每 30 分钟检查一次新邮件；`0` 或缺省 = 不自动轮询。

查找顺序：`.agent/roleplay.config` → `.claude/roleplay.config`（兼容旧部署）
→ `roleplay.config`。

## 使用

配置好后，对你的 agent 说"检查服务请求邮件"或"跑邮件值班"即可，agent 会按
SKILL.md 里的流程：读配置 → 搜未读请求邮件 → 下载附件 → 选定人格 → 执行
任务 → 回信（附产物文件）→ 标记已读 → 向你简报。

邮件脚本也可以单独当命令行邮件工具用：

```bash
python scripts/imap.py check                 # 看未读
python scripts/imap.py fetch <uid>           # 读正文
python scripts/imap.py download <uid>        # 下附件
python scripts/smtp.py send --to x@y.com --subject "标题" --body "正文" --confirmed
python scripts/smtp.py test                  # 给自己发测试信
```

完整命令速查与值班全流程见 [SKILL.md](SKILL.md)。

## 项目结构

```
├── SKILL.md                  # skill 主文档（值班全流程）
├── service.config.json       # 全局配置：角色库、关键字、署名模板
├── roleplay.config.example   # 项目配置模板
├── .env.example              # 邮箱配置模板
├── install.py                # 安装脚本（纯标准库）
├── tests/                    # 单元测试与冒烟测试（纯标准库 unittest）
├── .github/workflows/        # GitHub Actions 测试流水线
├── scripts/
│   ├── config.py             # 配置加载（.env / accounts.json 多账号）
│   ├── imap.py               # IMAP 收信/搜索/下载附件/标记已读
│   └── smtp.py               # SMTP 发信/附件/测试信
└── LICENSE
```

## 测试

项目自带纯标准库 unittest 测试（无第三方依赖）：

```bash
python -m unittest discover -s tests -v
```

覆盖配置解析、安装脚本的复制排除逻辑（密钥文件绝不被复制）、以及
imap/smtp 脚本的 accounts 冒烟测试。GitHub Actions 流水线
（`.github/workflows/test.yml`）会在 ubuntu / windows / macOS ×
Python 3.9 / 3.12 上自动跑语法检查、配置校验和全部测试。

## Credits

邮件收发脚本（`scripts/config.py`、`imap.py`、`smtp.py`）移植自网易有道
[**LobsterAI**](https://github.com/netease-youdao/LobsterAI) 项目的
[`imap-smtp-email`](https://github.com/netease-youdao/LobsterAI/tree/main/SKILLs/imap-smtp-email)
skill（作者 **NetEase**，MIT License）。原作基于 Node.js（imap-simple /
nodemailer / mailparser），本项目将其改写为纯 Python 标准库实现，去掉了
npm 依赖；`accounts.json` 多账号配置、环境变量（`EMAIL_CONFIG_MODE`、
`EMAIL_ACCOUNTS_PATH` 等）与 JSON 输出格式保持与上游兼容。

值班流程、人格库与署名机制为本项目原创。

## License

[MIT](LICENSE) —— 邮件脚本部分源自 NetEase 的 imap-smtp-email（MIT），
其余部分为本项目贡献者所有。
