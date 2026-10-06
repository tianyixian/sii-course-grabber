# SII Course Grabber 🎯

> SII 学生培养及教务管理系统的自动选课工具 —— 监控捡漏 + 开放瞬间冲刺，两种模式覆盖所有抢课场景。

[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Dependencies](https://img.shields.io/badge/依赖-仅%20requests-green.svg)](requirements.txt)

## ✨ 功能特性

| 模式 | 适用场景 | 工作方式 |
|---|---|---|
| 🔍 **监控模式** `run_monitor.py` | 课程满员，等别人退课捡漏 | 24 小时轮询（默认 20±4 秒），发现空缺立即抢入，抢完自动退出 |
| ⚡ **冲刺模式** `run_burst.py` | 选课定时开放 / 扩容放名额，拼手速 | 服务器时钟校准 + 多线程全速抢课（300ms/发），跳过所有页面点击 |

核心能力：

- **全自动登录续期** —— 复现统一身份认证（CAS）的 RSA 密码加密登录流程，token 过期自动重登，长期挂机无需人工干预
- **服务器时钟校准** —— 用 HTTP Date 响应头消除本地时钟偏差，秒级精准触发
- **扩容监视哨** —— 比通知时间更早发现扩容生效就提前开火，不放过任何一个提前量
- **同名课多班精确匹配** —— 按课程实例 ID 抢，绝不误中其他老师的班
- **状态持久化** —— 重启免登录、记住已抢到的课；网络异常自动重试，线程永不崩溃

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/tianyixian/sii-course-grabber.git
cd sii-course-grabber
pip install -r requirements.txt
```

### 1. 配置

```bash
cp config.example.json config.json
```

编辑 `config.json`，填入你的学号密码：

```json
{
  "backend_base": "https://xspy.sii.edu.cn/educationalAdministrationBackend",
  "username": "你的学号",
  "password": "你的密码",
  "targets": []
}
```

> ⚠️ `config.json` 已被 .gitignore 排除，账号密码不会进入 git 仓库。

### 2. 查课程 ID

```bash
python -m sii_grabber.find_course
```

会列出本学年全部可选课程：

```
课程名                       老师             已选/容量   状态   课程实例ID
----------------------------------------------------------------------
高级机器学习及深度学习应用     严骏驰           150/150    未选   40c00bde48d84d61...
凸优化与非线性优化            冯恺睿           60/160     未选   a220d44ea2984819...
```

把想抢的**课程实例 ID** 填进 `config.json` 的 `targets`。

### 3a. 监控模式（等退课捡漏）

```bash
python run_monitor.py
```

挂机即可。每轮打印目标课人数，出现 `*** 成功选上【xxx】***` 即告捷，程序自动退出。

### 3b. 冲刺模式（开放瞬间抢）

```bash
# 例：选课系统 16:30 开放（支持 'HH:MM:SS' 或 'YYYY-MM-DD HH:MM:SS'）
python run_burst.py --open "16:30:00"
```

程序会提前校准时钟、在开放前 10 秒预热连接，开放瞬间多线程全速抢课，抢到蜂鸣提醒（Windows）。

`targets` 中 `primary: true` 的课 300ms/发全速抢；`primary: false` 的课低频捡漏（适合没扩容、只能等退课的课）。

## ⚙️ 配置说明

| 字段 | 说明 |
|---|---|
| `backend_base` | 教务后端地址（一般不用改） |
| `username` / `password` | 你的学号与密码（初始密码规则见新生须知） |
| `school_year` | 学年代码，`S003` = 2026-2027；用 find_course 可核对 |
| `targets` | 目标课程列表：`{name, id, primary}`；监控模式也支持直接写课程名字符串 |
| `deadline` | 选课窗口截止时间（ISO 格式），到点自动停止 |
| `check_interval` / `jitter` | 监控模式轮询间隔与随机抖动（秒） |

## 🧠 工作原理

```
┌──────────────┐   ①RSA加密密码    ┌──────────────┐
│  学号 + 密码  │ ───────────────▶ │  CAS 统一认证  │
└──────────────┘                  └──────┬───────┘
                                         │ ②OAuth code
                                         ▼
┌──────────────┐   ④Authorization: token ┌───────────────┐
│   JWT token  │ ◀───────────────────── │  教务后端 API  │
└──────────────┘                        └──────┬────────┘
                                               │ ③JSON API
                              ┌────────────────┼────────────────┐
                              ▼                ▼                ▼
                        getSelectCourse   selectCourse     refundCourse
                        PagingList 查询    选课（一步到位）    退课
```

浏览器里"选课 → 确认"的两步弹窗，最终只是同一个 POST 请求。本工具直连该接口，
并做了时钟校准、请求并发、失败重试、token 续期，把从"看到名额"到"选上"的延迟
压缩到一次网络往返。

**错误码速查**（实现细节见 `sii_grabber/api.py`）：

| errorCode | 含义 | 处理 |
|---|---|---|
| `00000` | 成功 | 完成 |
| `B0001` | 选课未开启 / 人数已满（共用） | 继续重试 |
| `A0200` | 未登录 / token 失效 | 自动重新登录后续跑 |

## 📁 项目结构

```
sii-course-grabber/
├── run_monitor.py            # 入口：监控模式
├── run_burst.py              # 入口：冲刺模式
├── config.example.json       # 配置模板（复制为 config.json 填写）
├── sii_grabber/
│   ├── cas_login.py          # CAS 自动登录（RSA 加密）
│   ├── api.py                # 教务 API 封装 + token 续期 + 服务器校时
│   ├── monitor.py            # 监控抢课核心
│   ├── burst.py              # 冲刺抢课核心（多线程 + 监视哨）
│   └── find_course.py        # 课程 ID 查询工具
├── requirements.txt
└── LICENSE
```

## ❓ FAQ

**Q: 会被封号吗？**
A: 请求频率参照人工操作（监控模式 20 秒一次；冲刺模式瞬时高频但仅持续 1-2 分钟）。请合理使用，不要把轮询间隔调到夸张的小值，不要并发多账号。

**Q: token 多久过期？**
A: 约 6 天，但工具会在过期前自动重新登录，无需关心。

**Q: 抢到后想退课？**
A: 登录选课网站正常退，或用 `api.py` 里的 `refund()`。

**Q: 课程时间冲突导致选不上？**
A: 服务器会返回相应错误并记录在日志，请自行规划课表。

## 📝 免责声明

本项目仅供学习交流，用于自动化处理**本人**的选课操作。请遵守学校相关规定，
合理使用。因使用本工具造成的任何后果由使用者自行承担。

## 📄 许可证

[MIT](LICENSE)
