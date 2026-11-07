# niri-m3-trackpad

**Niri 26.04 + Material 3 Waybar + Apple 风格触控板手势**，三合一、可安装、可回滚、可验证。

把原本分散在三个仓库里的东西打包成一个项目：

| 来源 | 内容 | 在本仓库 |
|---|---|---|
| `waybar-m3` | Material 3 Expressive 状态栏、原生滑块、Wi‑Fi/蓝牙/电量、GTK 卡片式控制中心、字体、Matugen 换色 | [profiles/m3-waybar](profiles/m3-waybar) |
| `lancetfish-niri-fedora` | Niri KDL、快捷键、动画/窗口规则、Matugen 模板、fish/foot/fuzzel/mako 等 dotfiles | [profiles/niri-dotfiles](profiles/niri-dotfiles) |
| `ThinkPad` | Elan 触控板的 Apple 手势复刻守护进程、`uaccess` 规则、systemd 服务、fish helper、TouchViz | [profiles/elan-touch](profiles/elan-touch) |

上层控制面在 [manifest.toml](manifest.toml)、[scripts](scripts)、[modules](modules)、[tools](tools)。默认 **dry-run**，只有 `--apply` 才写 `$HOME`。

---

## 1. 触控板手势（本项目的核心）

在 Fedora / Niri Wayland 上，用**普通用户只读** `evdev` 事件复刻 [Apple 多点触控手势](https://support.apple.com/zh-cn/102482)。不 grab 设备、不改内核/固件/libinput 系统配置、不 root 常驻。

| Apple 手势 | 落地 | 谁负责 |
|---|---|---|
| 轻点、双指右键、滚动、捏合 | libinput（`tap` / `clickfinger` / `natural-scroll`） | Niri |
| 三指拖移 | libinput `drag` + `drag-lock` | Niri |
| **三指轻点 → 查找与数据检测器** | `elan_gesture.lookup`：读 PRIMARY 选区，必要时注入一次 `Ctrl+C`，按 URL/日期/电话/文本分流 | daemon |
| **四指左/右滑 → 切换全屏 App** | `FocusColumnLeft/Right` | daemon |
| **四指下滑 → App Exposé** | 查 `OverviewState` 仲裁，聚焦同 `app_id` 的下一个窗口 | daemon |
| 四指上滑 → 调度中心 | Niri 原生 overview | Niri |
| **拇指+三指张开 → 显示桌面** | 切到空工作区，再张开回来 | daemon |
| **拇指+三指捏合 → Launchpad** | `fuzzel` | daemon |
| **右边缘双指左滑 → 通知中心** | 复用 waybar tune 按钮的 `control.sh open`，与点击状态栏**共享同一个 toggle** | daemon |
| 智能缩放 / 页面轻扫 / 旋转 | 应用自身或 Wayland 不支持 | — |

完整 15 项对照、参数、已知差异见 [profiles/elan-touch/docs/APPLE_GESTURES.md](profiles/elan-touch/docs/APPLE_GESTURES.md)。

### 为什么能和 Niri 原生手势共存

Niri 原生占用三指垂直（切工作区）、三指水平（移动视图）、四指垂直（overview）。由于 daemon **不 grab**，Niri 一定会收到同一批触点，因此配置里用 `provider` 明确归属：

- `niri` → 只观察、不派发（避免一次手势触发两次）；
- `auto` → 手势开始查一次 `OverviewState` 再决定；
- `daemon` → daemon 独占（四指左右滑在 Niri 中没有绑定）。

所有手势默认 `trigger_on = "release"`，抬指后才动作。

### 注入后端

`inject` 动作类型只合成**键盘组合**（ydotool）与**滚轮刻度**（evdev UInput），从不发鼠标移动或点击。三指轻点默认先读选区，只有为空才注入 `Ctrl+C`。`ydotoold` 未运行时 daemon 照常工作，仅 `inject` 类动作失败。

---

## 2. 与 waybar 的搭配

`custom/panel`（tune 图标）和 `battery` 的 `on-click` 指向 `~/.config/waybar-m3/scripts/control.sh open`，拉起**独立的 GTK3 卡片式控制中心**（`controlcenter.py`，gtk-layer-shell，右上角，带真滑块）。

手势 `two_finger_edge_left` 直接**从 waybar 的 `config.jsonc` 里解析出同一条 `on-click` 命令**并异步执行，共享 `$XDG_RUNTIME_DIR/waybar-m3-cc.pid`。因此：

- 手势与点击状态栏按钮可以**互相开关**同一个面板；
- 不要求 waybar 进程是某个特定构建（本机就是裸 `waybar` 加载默认配置）；
- 第二次手势会关闭面板并清理 SIGTERM 残留的 pidfile。

Matugen 换色同时刷新旧栏 `~/.config/waybar/colors.css` 与新 M3 栏 `~/.config/waybar-m3/colors.css`。

---

## 3. 快速开始

```fish
cd ~/code/niri-m3-trackpad

# 只看计划，不写任何用户文件
./scripts/install.sh --dry-run --all
./scripts/verify.sh
```

`verify.sh` 当前实测 `PASS=23 FAIL=0`。

### 安装推荐组合

```fish
./scripts/install.sh --apply --profile m3-waybar \
    --profile niri-core --profile niri-theme --profile elan-gesture
```

这会：

- 部署 M3 Waybar 到 `~/.config/waybar-m3` 并安装字体；
- 部署 Niri 配置与 Matugen 模板；
- 安装 `~/.local/bin/integrated-waybar` 启动器，KDL 只把 `spawn-at-startup "waybar"` 改成它；
- 安装 Elan 手势到 `~/.local/share/integrated-niri-m3/elan-touch`，生成独立 venv，复制用户配置/systemd/fish 文件；
- 逐文件备份被覆盖的目标到 `~/.local/state/integrated-niri-m3/backups/<时间戳>/restore.tsv`。

`--all` 额外包含 `niri-supporting`（fish/foot/fuzzel/mako/kitty/waypaper 等白名单目录）；`--assets` 才复制壁纸；`--no-elan` 可跳过手势。

### 激活与回滚

```fish
./scripts/activate.sh --apply          # 重启 Waybar、启用/重启 elan-gesture.service
./scripts/restore.sh --latest           # 先看恢复计划
./scripts/restore.sh --latest --apply   # 实际恢复
```

### 手势单独安装（不走综合安装器）

```fish
cd profiles/elan-touch
./scripts/install.sh                   # 可选 --niri-input 补 clickfinger/drag
elan-gesture-gestures                  # 打印生效手势表
journalctl --user -u elan-gesture.service -f -o cat
```

首次使用先把 [config/examples/apple-trackpad.toml](profiles/elan-touch/config/examples/apple-trackpad.toml) 复制到 `~/.config/elan-gesture/config.toml`。

---

## 4. 目录结构

```text
niri-m3-trackpad/
├── README.md                  # 本文件
├── AGENTS.md                  # 给 AI / 维护者的实施契约
├── manifest.toml              # profile、路径、依赖、集成点的唯一清单
├── modules/
│   ├── integrated-waybar      # Niri 启动的 Waybar 启动器
│   ├── niri-startup.kdl       # 可抄进 config.kdl 的片段
│   └── matugen-waybar-m3.toml # Matugen 追加的 M3 输出模板
├── scripts/
│   ├── install.sh             # 非破坏安装；默认 dry-run
│   ├── activate.sh            # 重启 Waybar / Elan 服务
│   ├── restore.sh             # 按 restore.tsv 恢复
│   ├── test-install-sandbox.sh# HOME 指向沙箱的 apply 演练
│   └── verify.sh              # 一键校验 + docs/validation-report.md
├── tools/validate.py          # JSONC / CSS 角色 / TOML / 硬编码路径静态检查
├── profiles/
│   ├── m3-waybar/             # 上游 waybar-m3 快照
│   ├── niri-dotfiles/         # 上游 Niri dotfiles 快照
│   └── elan-touch/            # 触控板手势 + TouchViz
│       ├── src/elan_gesture/  # 识别器 / 引擎 / 动作 / 注入后端
│       ├── config/            # default.toml + apple-trackpad.toml
│       ├── docs/APPLE_GESTURES.md
│       └── tests/             # 71 个 unittest + 29 个 JSONL fixture
├── docs/                      # 架构与整合报告
└── tests/                     # 集成级测试入口说明
```

---

## 5. 依赖矩阵

核心会话：`niri` 26.04、`waybar`、`swaybg`、`fcitx5`、`fuzzel`、`mako`、`foot`、`fish`。

M3 Waybar 脚本：`jq`、`pactl`、`brightnessctl`、`nmcli`、`bluetoothctl`、`playerctl`、`makoctl`、`notify-send`、`python3-gobject`、`gtk3`、`gtk-layer-shell`、`Material Symbols Rounded`、`Roboto`。

Elan 手势：`evdev-binary==2.0.0`（自带 `requirements.lock` 校验）、Python 3.14、`systemctl --user`、udev `uaccess` ACL；可选 `ydotoold`（注入）、`wl-paste`（查找）、`GTK4` + `python3-cairo` + `gtk4-layer-shell`（TouchViz）。

可选：`matugen`、`swaync`、`wlsunset`、`tuned`。`verify.sh` 会列出缺失命令，缺可选命令不会让静态校验失败。

---

## 6. 验证

```fish
./scripts/verify.sh
./scripts/test-install-sandbox.sh       # 把 HOME 指向 .sandbox/home，不碰真实 ~/.config
cd profiles/elan-touch && ./scripts/test-offline.sh
```

检查项：manifest/TOML、Waybar JSONC、M3 CSS 颜色角色、硬编码路径、profile 来源、Niri 启动片段、bash/fish/Python 语法、**71 个手势单测**、TouchViz 5 个单测、29 个 JSONL 回放、Niri IPC。

Waybar 与控制中心可短跑验证：

```bash
timeout 5s waybar -c ~/.config/waybar-m3/config.jsonc -s ~/.config/waybar-m3/style.css
~/.config/waybar-m3/scripts/control.sh open
elan-gesture-inject-test                 # 只读诊断注入后端
elan-gesture-lookup --print-only         # 只读诊断查找动作
```

---

## 7. 安全与权限

- 安装器禁止 root 执行，所有写入都在 `$HOME` 内；
- 每次覆盖前 `cp -a` 备份并写 `restore.tsv`；
- 不删除用户文件，不覆盖不在白名单里的配置；
- `72-` udev 规则只给当前 seat 用户授权**一个** Elan 触控板节点的读权限，不把用户加入 `input` 组；
- daemon 仍是普通用户、无 `AmbientCapabilities`、无 `EVIOCGRAB`；
- 综合安装器默认不 `sudo`、不启用 COPR、不改 `/etc`、不改内核/固件/Niri 系统包。

---

## 8. 已知限制

- 三指轻点在 libinput 层必然附带一次 middle/right 点击（无法禁用）；
- 四指下滑与 Niri「关闭 overview」同向，靠 `provider = "auto"` 仲裁，IPC 超时时可能各动作一次；
- App Exposé 不是真正的窗口网格（Niri 无应用级预览），实现为聚焦同 `app_id` 的下一个窗口；
- 旋转手势不支持（Wayland/libinput 无 rotate 协议）；
- 右边缘双指左滑会同时被 libinput 当作水平滚动，靠 15 mm 边缘带降低误触；
- 真机手指的完整统计仍需本地补做，见 [profiles/elan-touch/docs/TEST_REPORT.md](profiles/elan-touch/docs/TEST_REPORT.md)。

---

## 9. 致谢与来源

- [Apple 支持：在 Mac 上使用多点触控手势](https://support.apple.com/zh-cn/102482)
- [niri](https://github.com/niri-wm/niri) 与 [niri IPC 文档](https://niri-wm.github.io/niri/IPC.html)
- 上游 [SHORiN-KiWATA/shorin-niri](https://github.com/SHORiN-KiWATA/shorin-niri) 的 Niri 配置思路
- 本项目三个 profile 均为本机实际跑过/验证过的内容快照；历史文档中的旧绝对路径保留原样，安装器会在复制时替换为当前 `$HOME`。
