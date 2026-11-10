# 机房故障智能诊断助手

面向高校机房运维的 AI 故障排查工具：用自然语言描述现象，AI 逐层问诊给出故障原因，
自动落成报修台账，并结合课表判断哪几节课受影响、可以挪到哪间教室。

## 界面

| 落地页 | 对话式诊断 |
|---|---|
| ![落地页](docs/screenshots/01-landing.png) | ![对话式诊断](docs/screenshots/02-diagnosis.png) |

| 报修台账 | 运行总览 |
|---|---|
| ![报修台账](docs/screenshots/03-records.png) | ![运行总览](docs/screenshots/04-overview.png) |

| 课表与调课 | 日常报备 |
|---|---|
| ![课表](docs/screenshots/05-schedule.png) | ![日常报备](docs/screenshots/06-daily-tasks.png) |

| 教室与设备管理 | 教室详情 |
|---|---|
| ![教室管理](docs/screenshots/07-classroom-admin.png) | ![教室详情](docs/screenshots/08-classroom-detail.png) |

## 安装与运行

### 环境要求

| 项目 | 要求 |
|---|---|
| Python | 3.10 或更高（开发环境为 3.15.0） |
| 依赖库 | 见 `requirements.txt` |
| API Key | DeepSeek API Key（[申请地址](https://platform.deepseek.com/)） |

```bash
python --version
```

### 1. 获取代码

```bash
git clone git@github.com:liyishuo1/dsh-fault-diagnosis.git
cd dsh-fault-diagnosis
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API Key

程序从环境变量读取 Key，**不写入代码**。
需要配哪几项、每项什么含义，见根目录的 **`.env.example`**（环境变量模板）。

**Windows（PowerShell，永久生效）：**

```powershell
[Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "你的key", "User")
```

设置后需要**新开一个终端**才生效。

**临时设置（仅当前终端有效）：**

```powershell
$env:DEEPSEEK_API_KEY = "你的key"
```

**验证：** `echo $env:DEEPSEEK_API_KEY` 能输出你的 key 即可。

### 4. 运行

**方式一：一键启动（推荐）**

- **Windows**：双击根目录的 `start.bat`
- **Linux / macOS**：`./start.sh`

脚本会自动检查依赖、读取 API Key、检查端口占用，并打开浏览器。

```powershell
.\start.bat -Port 5001      # 换端口
.\start.bat -NoBrowser      # 不自动开浏览器
```

**方式二：桌面窗口版（Windows）**

双击根目录的 `desktop.bat`，直接弹出一个最大化窗口，没有地址栏、没有标签页、没有控制台。
关闭窗口即退出程序。

```bash
pip install pywebview
```

侧边栏底部的**设置**按钮可以查看 / 修改 / 清除 API Key，以及打开数据目录。

**方式三：打包成 exe（不用装 Python）**

```bash
tools\build_exe.bat
```

产物在 `dist\机房故障智能诊断助手\`，**整个文件夹一起拷走**，双击里面的 exe 即可。

源数据（教室台账、报修记录、课表）放在程序同目录的 `data\` 下。

## 账户初始化与本机维护

首次访问会初始化账户文件并显示登录页。在同一个项目目录和数据目录下运行以下命令，分别查看管理员与普通成员邀请码，再从登录页进入注册。

```powershell
python src/account_admin.py show-invite admin
python src/account_admin.py show-invite member
```

邀请码可供同角色多人注册。用 `python src/account_admin.py rotate-invite admin` 轮换管理员邀请码，然后用查看命令取得新码。用 `python src/account_admin.py reset-password "用户名"` 交互式重置密码，旧登录会话随即失效。

升级时会先备份旧报修 CSV 再添加账户字段。核对实际数据中的历史记录编号后，用 `python src/account_admin.py migrate-reporters "李一硕" R001 R002` 这种形式补录上报人，其中编号应替换为实际确认的清单。重复运行会保留已填写的上报人。

维护命令使用与服务相同的 `DSH_DATA_DIR`。如未指定，则按项目的本地数据目录规则解析。请使用仅本机运维人员可访问的数据目录，邀请码、账户、会话、审计日志和备份随数据目录管理。


## v1.1.0 更新

2026-11-10 更新账户与权限管理、上报人追踪和管理员操作日志。登录与注册使用用户名，侧边栏提供账户、日志和退出图标，收起后仅显示图标。

管理员操作日志支持操作类型、日期范围、关键词查询及时间升降序排序，筛选覆盖完整日志并支持分页加载。详情见 `docs/迭代日志.md` 和 `docs/账户系统设计.md`。

桌面版升级时沿用原程序的 `data/`，保留账户、邀请码及业务记录。账户文件与实际业务数据在本机维护。
