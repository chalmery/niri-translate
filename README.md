# Niri Translate

适用于 Linux / niri / Wayland 的本地中英文翻译客户端。点击系统托盘图标，从屏幕右侧滑出翻译抽屉；由本机运行的 Hy-MT2 模型完成翻译，自动检测可用 GPU（Vulkan），不可用或加载失败时回退 CPU。

- 原文、译文左右双栏；`Ctrl+Enter` 翻译，流式输出，可停止、复制。
- 点击抽屉外部或 `Esc` 收起，内存中保留文字；退出后不保存历史。
- 独立的 Wayland layer-shell 面板，不占用 niri 平铺布局；设置在抽屉内。
- 跟随 **Clavis 的 Material 配色和浅色/深色主题**，文件更新后自动同步，无需重启。
- 模型卡片直接显示本地状态、大小、完整路径；支持打开目录、复制路径、下载续传及导入外部文件。
- 可选择或填写模型存储目录，校验可写性后保存；支持恢复默认位置。
- 官方 GGUF 按需下载、进度、取消、断点续传、SHA-256 校验；外部模型关联在切换后保留。
- 设置中选择自动 GPU / 仅 CPU，显示检测到的显卡、显存和当前运行设备。
- 单实例、同一时间只运行一个模型；切换先卸载，退出清理推理进程。
- 登录自启默认关闭；开启后仅显示托盘。

![浅色翻译抽屉](docs/screenshot.png)

## 环境与版本

实测：Fedora 44，niri 26.04，Clavis/Quickshell 顶部栏，Intel i5-13400，约 32 GB 内存。无需独立显卡。

| 组件 | 锁定 / 验证版本 |
| --- | --- |
| Python | >= 3.11；安装环境实测 3.13.5 |
| PySide6 / Qt Python 组件 | 6.11.2，依赖与哈希见 `requirements.lock` |
| Quickshell | 0.3.1（本机 RPM `0.3.1-2.fc44`），使用系统 Qt |
| llama.cpp | v0.5.0，提交 `d2e54583c7452353eb35d40431281f6ee984332f` |
| 推理配置 | 自动 GPU / CPU，CPU 最多 8 线程，8192 上下文，单 slot |

界面使用 Quickshell/QML；Python/PySide6 负责托盘、设置、下载及进程管理，通过当前用户私有 Unix socket 与抽屉通信。两个 Qt 版本分属独立进程，不混载动态库。独立于 Clavis 源码，Clavis 只作为配色来源；没有 Clavis 时使用明暗主题后备色。

## 安装和启动

需要已有 Wayland 会话和支持 StatusNotifierItem 的托盘（Clavis 已支持）。先安装发行版提供的 `quickshell`（验证版本 0.3.1）及构建依赖：

```bash
sudo dnf install python3 uv gcc-c++ cmake ninja-build curl git
# 可选：Vulkan GPU 构建依赖（还需要适配显卡的 Vulkan 驱动）
sudo dnf install vulkan-loader-devel glslc spirv-headers-devel
# quickshell 按其官方 Fedora 安装说明配置软件源后安装。
git clone https://github.com/chalmery/niri-translate.git
cd niri-translate
./scripts/install.sh
```

安装脚本创建专用虚拟环境、校验并编译固定提交的运行时（构建依赖齐全时启用 Vulkan，否则 CPU），安装图标与 `.desktop` 入口。不会自动下载模型、开启自启或修改 niri/Clavis 配置。

从应用菜单搜索 **Niri 本地翻译 / Niri Translate**，或执行：

```bash
~/.local/bin/niri-translate
# 仅托盘启动：
~/.local/bin/niri-translate --background
```

首次进入抽屉的“设置”，在模型卡片中下载默认模型或导入已有官方 GGUF。已在本地、未下载、下载未完成和大小异常会分别显示；“已在本地”表示文件存在且大小匹配，加载前仍执行完整 SHA-256 校验。模型校验和加载期间仍能编辑文本。之后可完全离线翻译。点击托盘图标切换抽屉，右键菜单提供打开、设置、退出。

如要配置 niri 快捷键，可自行在已有 `binds` 中加入：

```kdl
Mod+T { spawn "niri-translate"; }
```

不需要浮动窗口规则。抽屉宽度可在设置或通过拖动左边缘调整并记住；高度适应屏幕可用空间。托盘不可用时保留可见抽屉，设置页面底部仍可退出。

## GPU 加速

运行时通过 `llama-server --list-devices` 检测实际可用的推理设备，过滤软件渲染器，自动优先选择空闲显存最多的 GPU。GPU 模式将所有模型层放到该设备；加载失败或超时会自动重试 CPU 一次。仅 CPU 模式使用 `--device none`，完全禁用 GPU 卸载。GPU 是否更快取决于硬件和输入，设置中可切换对比。

已有 CPU 安装可在安装上述 Vulkan 构建依赖后执行：

```bash
./scripts/build-runtime.sh
# 可显式选择构建后端：
NIRI_TRANSLATE_BACKEND=vulkan ./scripts/build-runtime.sh
NIRI_TRANSLATE_BACKEND=cpu ./scripts/build-runtime.sh
```

构建使用动态后端；无兼容 GPU 时仍可使用 CPU。构建完成后重启客户端以重新检测设备。默认模式为自动；设置中的模式选择会保存，切换模式会停止当前翻译并重新加载模型。该版不修改显卡驱动。

## 模型

模型配置存于 `niri_translate/models.json`，包含固定仓库 revision、完整文件名、字节数与官方 LFS SHA-256；下载 URL 不跟随 `main` 漂移。

| 模型 | 文件 | 精确大小 | 定位 |
| --- | --- | ---: | --- |
| Hy-MT2-1.8B Q4_K_M | `Hy-MT2-1.8B-Q4_K_M.gguf` | 1,133,080,448 B | 默认，已在本机真实验证 |
| Hy-MT2-1.8B Q8_0 | `Hy-MT2-1.8B-Q8_0.gguf` | 1,908,528,192 B | 精度对照选项，未在本机完整下载/推理验收 |
| Hy-MT2-7B Q4_K_M | `Hy-MT2-7B-Q4_K_M.gguf` | 4,624,648,896 B | 质量候选，未在本机完整下载/推理验收 |

上面是文件大小，不是运行内存。只适配这三个官方文件，本地文件也按完整哈希识别，不承诺任意 GGUF 兼容。默认模型取舍是本地速度、质量与资源平衡，没有“中译英绝对最好”的结论。

官方来源：[1.8B GGUF](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF)、[7B GGUF](https://huggingface.co/tencent/Hy-MT2-7B-GGUF)、[llama.cpp](https://github.com/ggml-org/llama.cpp)。运行时已用默认文件验证 `hunyuan-dense`、Q4_K_M 和文件内嵌聊天模板。参数从官方建议起步：temperature 0.7、top_p 0.6、top_k 20、repeat_penalty 1.05，最多生成 4096 tokens。

下载中的文件使用 `.gguf.part`，校验成功后原子改名；失败可重试，未完成文件不会加载。网络断开后保留部分文件；服务端忽略 Range 时安全重下，哈希错误时删除损坏临时文件。

### 自定义模型存储目录

在设置中的“模型存储位置”选择文件夹或填写绝对路径（支持 `~/Models`），点击“应用目录”保存。目录不存在时会尝试创建，并检查写入权限；失败时保留原配置。更改目录会停止当前翻译，重新扫描并加载所选模型；下载、校验、加载过程中暂时不能更改目录。

新下载及 `.gguf.part` 断点文件使用保存后的目录。已有模型和未完成的下载不会自动搬移：可以导入旧目录中的模型，或切回旧目录续传。导入的外部文件始终在原路径使用。“恢复默认”先填入默认位置，点击“应用目录”后生效。

## 翻译与隐私

服务只监听 `127.0.0.1` 随机端口，使用临时 API key，关闭 Web UI，并开启 `--offline`。客户端只在点击下载时访问 Hugging Face；正常翻译不访问外部接口。安装依赖、构建运行时需要联网。

采用模型内嵌聊天模板，原文只进入翻译提示词，不具备执行命令或调用工具的权限。模型仍可能受原文中的指令影响译文质量，不能把提示词视为可靠的语义隔离。

按 `/props` 的实际上下文及 `/tokenize` 的真实 token 数预算。先保留换行/段落和完整代码围栏，再对超长段落按句子拆分；单个句子仍太长时按测量后的字符/词边界继续拆分，不丢字、不静默截断。分段可能损失跨段语境。单次本地通信帧上限为 8 MiB，超过时明确报错并阻止使用旧原文翻译，需要分批粘贴。检测输出长度限制或意外流结束，保留部分结果并明确标记未完成。

取消、重新翻译和切换模型有请求代次隔离，旧结果不能覆盖新结果。默认不保存原文、译文或历史；日志只保留启动、退出和 QML 诊断。不要在诊断时开启含请求内容的 llama.cpp 调试日志。

## 主题与桌面集成

默认只读 Clavis：

- 配置：`$XDG_CONFIG_HOME/clavis/config.json`
- 配色：`$XDG_DATA_HOME/clavis/profiles/default/generated/clavis/colors.json`

支持 Clavis 的 `CLAVIS_CONFIG_HOME`、`CLAVIS_DATA_HOME`、`CLAVIS_PROFILE`、`CLAVIS_PROFILE_HOME`、`CLAVIS_GENERATED_HOME`、`CLAVIS_PERSONALIZATION_CONFIG` 环境覆盖。文件及目录同时监听，兼容 matugen 原子替换文件；监听遗漏时 3 秒轮询补偿。抽屉背景复用 Clavis `colLayer0Base` 的混色规则，文字/强调色使用对应 Material 语义色，并跟随背景透明度。当前不复制 Clavis 的专有模糊效果。

登录自启使用标准 XDG autostart：本机 niri-session 的 `xdg-desktop-autostart.target` 已实际启用。其他会话若不处理 XDG autostart，需要先启用该机制。设置开关只管理本应用的 `.desktop` 文件。

固定标识：托盘/桌面应用 `io.github.chalmery.niri-translate`；Wayland layer-shell namespace `niri-translate-drawer`。层面板没有普通 xdg-toplevel 窗口的 app_id。

## 目录与卸载

遵循 XDG（缺省展开为下表）：

| 内容 | 目录 |
| --- | --- |
| 配置 | `~/.config/niri-translate/` |
| 模型 | 默认 `~/.local/share/niri-translate/models/`，可在设置中修改 |
| Python 环境/运行时 | `~/.local/share/niri-translate/{venv,runtime}/` |
| 日志 | `~/.local/state/niri-translate/` |
| 单实例锁/通信 | `$XDG_RUNTIME_DIR/niri-translate/` |
| 登录自启 | `~/.config/autostart/io.github.chalmery.niri-translate.desktop` |

先从托盘退出，再执行：

```bash
./scripts/uninstall.sh                         # 保留模型、配置和日志
./scripts/uninstall.sh --purge                 # 另删配置和日志
./scripts/uninstall.sh --purge --delete-models # 明确选择删除默认目录内的模型
```

自定义存储目录和外部选择的本地 GGUF 从不删除，需要自行管理。卸载不删除源码仓库；构建缓存 `.build/` 可自行清理。早期本次开发测试添加的 niri 浮动规则已撤回；当前版本不需要任何浮动窗口配置。

## 开发与验证

```bash
~/.local/share/niri-translate/venv/bin/python -m unittest discover -s tests -v
# 真实桌面验收会使用测试文本并退出测试实例；先退出正在使用的客户端：
~/.local/share/niri-translate/venv/bin/python tests/live_acceptance.py
# 实际运行时与长输入检查：
~/.local/share/niri-translate/venv/bin/python tests/runtime_acceptance.py /tmp/runtime-test.json
# 使用隔离配色验证浅色→深色→浅色，不改系统主题；需要 matugen：
~/.local/share/niri-translate/venv/bin/python tests/theme_live.py
```

源代码：`app.py` 管理托盘/状态/通信，`ui/shell.qml` 绘制抽屉，`theme.py` 跟随主题，`runtime.py` 管理子进程，`inference.py` 负责真实 token 预算和流式翻译，`download.py` 负责可恢复下载，`storage.py` 管理 XDG 与完整性校验。

新增模型必须核对官方架构、模板、量化支持，加入固定 revision/大小/哈希，再完成真实推理与质量测试；仅添加目录项并不等于已经验证兼容。

详细实测和未验证项目见 [验收记录](docs/validation.md)。本版不包含 OCR、划词、云 API、账户或历史记录。
