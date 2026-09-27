# Niri Translate：给 AI 助手的安装指南

本文供具备本机终端权限的 AI 助手使用，目标是帮助用户安装并启动 Niri Translate。按用户的实际要求执行；用户指定的目录、模型、网络或测试限制优先。只有聊天能力、无法操作电脑的助手，应提供对应命令，不要声称已经安装。

- 项目：https://github.com/chalmery/niri-translate
- 本文原始 Markdown：https://raw.githubusercontent.com/chalmery/niri-translate/main/docs/INSTALL_FOR_AI.md
- 产品说明：[README](../README.md)
- 环境：Linux、Wayland、支持 layer-shell 的合成器；主要验证环境为 Fedora / niri。
- 界面：Quickshell；推理：本地 llama.cpp，自动 GPU / CPU；无需云 API 密钥。

## 1. 先检查目标机器

先做只读检查，避免套用开发者的发行版或个人路径：

```bash
cat /etc/os-release
uname -m
printf 'session=%s\nwayland=%s\n' "$XDG_SESSION_TYPE" "$WAYLAND_DISPLAY"
python3 --version
for tool in uv qs git cmake ninja curl pkg-config glslc; do
  command -v "$tool" || true
done
```

如果 `qs` 已安装，执行 `qs --version`。本项目验证版本是 Quickshell 0.3.1，Python 要求 >= 3.11；Python 依赖版本与哈希以仓库 `requirements.lock` 为准。

确认用户正在图形 Wayland 会话中，并且顶部栏/面板支持 StatusNotifierItem 托盘。Clavis 可提供托盘和主题配色，但不是安装前提。没有图形会话时可以准备安装，不能宣称界面启动成功；X11、Windows、macOS 不属于当前安装流程的支持范围。

检查是否已有安装和运行实例。升级时保留模型、配置、断点下载及用户源码改动；重启前保留当前窗口中的原文与译文。

## 2. 补齐依赖

根据 `/etc/os-release` 使用对应包管理器。以下仅为 Fedora 示例，不要直接在其他发行版上执行：

```bash
sudo dnf install python3 uv gcc-c++ cmake ninja-build curl git pkgconf-pkg-config
# 准备使用 Vulkan GPU 加速时：
sudo dnf install vulkan-loader-devel glslc spirv-headers-devel
```

安装 Quickshell 时先查询当前发行版的软件源，缺少软件包时参考 [Quickshell 官方安装说明](https://quickshell.org/docs/v0.3.0/guide/install-setup/)。包名和软件源会变化，不要假设所有发行版都能直接安装同名包，也不要替换用户现有桌面配置。

GPU 需要可用的 Vulkan 驱动。客户端会检查实际设备，加载失败时回退 CPU；不要仅凭显卡品牌承诺加速成功。当前构建启用 Vulkan 或 CPU，不编译 CUDA。已有驱动不需要为安装本应用而重装。

## 3. 获取源码并安装

先选一个用户可写的源码目录。下面以当前用户的 `~/src` 为例；如果用户已有仓库，使用已有目录，并检查 remote、分支和未提交改动。干净的 `main` 可用 `git pull --ff-only` 更新，发生分叉时保留用户改动再处理，不强制覆盖。

全新安装：

```bash
mkdir -p "$HOME/src"
cd "$HOME/src"
git clone https://github.com/chalmery/niri-translate.git
cd niri-translate
./scripts/install.sh
```

安装前阅读当前版本的 `scripts/install.sh` 和 `scripts/build-runtime.sh`。脚本使用用户级虚拟环境，按锁文件安装 Python 依赖，并在运行时缺失或版本不符时构建固定提交的 llama.cpp。**安装脚本以普通用户执行，不要用 `sudo ./scripts/install.sh`。**

首次编译会花费一些时间。内存较少时可使用 `BUILD_JOBS=2 ./scripts/install.sh`。只需 CPU 的机器可使用 `NIRI_TRANSLATE_BACKEND=cpu ./scripts/install.sh`；该变量仅在需要构建运行时时生效。要更改已安装运行时的后端，在退出客户端后显式运行：

```bash
NIRI_TRANSLATE_BACKEND=cpu ./scripts/build-runtime.sh
# 或：依赖和驱动齐全时构建 Vulkan 后端
NIRI_TRANSLATE_BACKEND=vulkan ./scripts/build-runtime.sh
```

安装过程需要访问 Python 包源及 GitHub，下载模型需要访问 Hugging Face。下载失败时检查具体网络错误，不关闭 TLS 校验或绕过 SHA-256 校验。

## 4. 准备默认小翻译模型

默认推荐 **Hy-MT2-1.8B Q4_K_M**，下载约 **1.13 GB**；文件大小不等于运行内存。安装脚本本身不下载模型。

如果用户要求完整安装并可直接翻译，下载这个默认模型即可；如果用户只要求安装客户端或禁止下载大文件，则跳过权重下载并如实说明。已有模型应先复用和校验，不必重复下载，更不要批量下载所有型号。

可以启动后进入“设置 → 常用小模型”，点击“下载模型”，或通过已安装客户端的下载函数完成相同步骤：

```bash
NIRI_PYTHON="${XDG_DATA_HOME:-$HOME/.local/share}/niri-translate/venv/bin/python"
"$NIRI_PYTHON" - <<'PY'
import threading
from niri_translate.catalog import load_catalog
from niri_translate.download import download
from niri_translate.storage import model_path, settings, verify

config = settings()
models, _, _ = load_catalog()
model = next(m for m in models if m['id'] == '1.8b-q4_k_m')
# 优先尊重已关联的外部文件；校验失败时保留文件，交由用户处理。
from pathlib import Path
external = config.get('local_paths', {}).get(model['id'])
path = Path(external) if external else model_path(model, config)
cancel = threading.Event()
if path.is_file():
    verify(path, model, cancel)
else:
    if external:
        raise SystemExit('已关联的外部模型不存在，请在设置中重新选择模型路径')
    download(model, cancel, lambda done, total: print(f'\r下载 {done / total:.0%}', end='', flush=True), target=path)
print('\n模型已就绪：', path)
PY
```

不要在客户端正在下载同一模型时并行运行这段代码。下载会保留 `.part` 文件以便续传，并校验完整 SHA-256。新安装默认选择该模型；升级已有安装时保留用户当前选择，必要时在设置中切换。

## 5. 启动并确认结果

在用户的图形会话中启动已安装入口，不要长期依赖源码目录中的临时进程：

```bash
"$HOME/.local/bin/niri-translate"
# 用户需要仅托盘启动时：
"$HOME/.local/bin/niri-translate" --background
```

安装新代码不会自动重启旧进程。若旧客户端仍运行，再次启动通常只会唤起旧实例；应保存用户当前文本、正常退出旧客户端，再启动新版。不要为了重启杀死其他 Quickshell 面板。

检查实际界面已打开、托盘存在，并在“设置”确认模型就绪和实际运行设备。主页不显示显卡和耗时信息，这是正常设计。可用一条普通短句确认翻译能输出；如果用户要求不测试，则跳过并报告“已安装/已启动，翻译未验证”。不要用历史验收记录代替本机检查结果。

登录自启默认关闭。用户要求时，在设置中开启“登录后自动启动到托盘”。它使用 XDG autostart 和 `--background`，开机只显示托盘，不展开侧边栏；不要另加一套重复的 systemd 或 niri 启动项。

## 6. 路径与排错

所有路径都按当前用户解析。模型目录也可能已由用户自定义，应以设置中的实际路径为准。

| 内容 | 默认路径 |
| --- | --- |
| 模型 | `${XDG_DATA_HOME:-$HOME/.local/share}/niri-translate/models/` |
| 虚拟环境 / 推理运行时 | `${XDG_DATA_HOME:-$HOME/.local/share}/niri-translate/{venv,runtime}/` |
| 配置 | `${XDG_CONFIG_HOME:-$HOME/.config}/niri-translate/settings.json` |
| 日志 | `${XDG_STATE_HOME:-$HOME/.local/state}/niri-translate/{client,drawer}.log` |
| 启动入口 | `$HOME/.local/bin/niri-translate` |

- 缺少 `qs`、QML 模块或界面启动失败：检查 Quickshell 与系统 Qt 依赖，以及 `drawer.log`；不要删除用户的顶部栏配置。
- 仅 CPU：检查设置中的设备检测结果、Vulkan 驱动和构建依赖；必要时重新构建 Vulkan 运行时。不要将“有显卡”等同于“运行时已启用 GPU”。
- 模型未就绪：检查下载状态、实际存储位置、校验信息及可用内存；“扫描本地”和“在线更新”均不会下载权重。
- 安装后界面仍旧：确认已退出旧实例，再从已安装入口启动；仅比较磁盘文件不足以证明运行中的界面已更新。
- Hugging Face 连接失败：保留已有模型和下载片段；恢复连接后续传，也可以导入模型库中可校验的本地 GGUF。

结束时简要告知用户：安装的提交、启动结果、所用模型、实际 GPU/CPU 状态、自启是否开启，以及没有完成的步骤。只有确认过的结果才写“成功”。
