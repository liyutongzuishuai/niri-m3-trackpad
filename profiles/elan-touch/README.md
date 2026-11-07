# ThinkPad Elan 触控板手势（Apple 复刻）

在 Fedora 44 / Niri Wayland 下把 [Apple 多点触控手势](https://support.apple.com/zh-cn/102482) 尽量复刻到 Elan Touchpad：除了原有的「两指静止 + 第三指独立滑动」四方向识别，还新增三指轻点、四指滑动、拇指张合、边缘双指滑动。程序只以普通用户读取 `evdev` 原始事件，不 grab 设备，不依赖 X11、Touchegg、内核补丁或触控板固件。

与 Niri 原生手势的分工见 [docs/APPLE_GESTURES.md](docs/APPLE_GESTURES.md)：Niri 已经提供的（轻点、双指滚动、三指切工作区、四指 overview）由 Niri 继续负责，daemon 只补它缺的那部分，并在配置里用 `provider` 明确标注，避免一次手势触发两次。

## 它做了什么

- 通过 `evdev` 只读、非阻塞、不 `EVIOCGRAB` 打开 Elan Touchpad。
- 以 `ABS_MT_SLOT` 组装 type-B 帧，以 `ABS_MT_TRACKING_ID` 作为手指身份；处理释放、ID 复用、`SYN_DROPPED`。
- 只有恰好 3 个触点，且其中 2 个各自漂移与相互距离变化都低于阈值、第三个触点达到单轴净位移时才识别。
- 输出方向、置信度、静止 ID、mover ID、位移与拒绝原因。
- 通过 `$NIRI_SOCKET` 的单行 JSON IPC 或用户命令执行四方向动作。
- 默认 `trigger_on = "release"`：抬指后触发，避免与 Niri 原生手势叠加；`dry_run` 可只记日志。
- 新增多指识别器：三指轻点（查找/数据检测器）、四指整体滑动、拇指+三指张合（显示桌面 / Launchpad）、右边缘双指左滑（通知中心），由 [engine.py](src/elan_gesture/engine.py) 统一仲裁，同一帧最多派发一个手势。
- 可选注入后端（`inject` 动作类型）：只发键盘组合与滚轮，绝不发鼠标移动或点击；`inject-test` 可先 dry-run 诊断。

## 目录

| 路径 | 用途 |
|---|---|
| [src/elan_gesture/main.py](src/elan_gesture/main.py) | CLI / monitor / probe / capture / replay / daemon |
| [src/elan_gesture/mt.py](src/elan_gesture/mt.py) | type-B slot 与 tracking ID 帧解析 |
| [src/elan_gesture/gesture.py](src/elan_gesture/gesture.py) | 阈值、静止约束、方向、置信度、状态机 |
| [src/elan_gesture/engine.py](src/elan_gesture/engine.py) | 多识别器仲裁，唯一的帧入口 |
| [src/elan_gesture/tap.py](src/elan_gesture/tap.py) | 多指轻点 |
| [src/elan_gesture/swipe.py](src/elan_gesture/swipe.py) | 多指整体平移 |
| [src/elan_gesture/spread.py](src/elan_gesture/spread.py) | 拇指 + 三指张合 |
| [src/elan_gesture/edge_swipe.py](src/elan_gesture/edge_swipe.py) | 边缘双指内滑 |
| [src/elan_gesture/inject.py](src/elan_gesture/inject.py) | 可选注入后端（ydotool / UInput 滚轮） |
| [src/elan_gesture/niri_dynamic.py](src/elan_gesture/niri_dynamic.py) | 需要查询 Niri 状态的动作 |
| [src/elan_gesture/lookup.py](src/elan_gesture/lookup.py) | 三指轻点的查找动作 |
| [src/elan_gesture/actions.py](src/elan_gesture/actions.py) | Niri IPC / 注入 / 命令分发 |
| [config/default.toml](config/default.toml) | 完整默认配置（所有新手势默认关闭） |
| [config/examples/four-directions.toml](config/examples/four-directions.toml) | 四方向自定义示例 |
| [config/examples/apple-trackpad.toml](config/examples/apple-trackpad.toml) | Apple 手势完整映射 |
| [docs/APPLE_GESTURES.md](docs/APPLE_GESTURES.md) | 15 项 Apple 手势落地对照 |
| [systemd/elan-gesture.service](systemd/elan-gesture.service) | 用户级服务 |
| [fish/conf.d/elan-gesture.fish](fish/conf.d/elan-gesture.fish) | fish 函数 |
| [scripts/install.sh](scripts/install.sh) / [scripts/uninstall.sh](scripts/uninstall.sh) | 安装/卸载 |
| [docs/TEST_REPORT.md](docs/TEST_REPORT.md) | 实际测试报告 |
| [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | 已知限制 |

## 安装

```bash
cd /home/lancetfish/code/ThinkPad
./scripts/install.sh
```

脚本会：
1. 在项目 `.venv` 中安装锁定的 `evdev-binary==2.0.0`（Python 3.14 wheel，带 sha256 校验）。
2. 把四方向示例复制到 `~/.config/elan-gesture/config.toml`（已有文件不覆盖）。
3. 安装 fish helper 与 `~/.config/systemd/user/elan-gesture.service`，验证 unit 语法。
4. 检测 `/dev/input/event11` 能否用普通用户 `O_RDONLY` 打开；如不能则尝试一次 `pkexec`/`sudo` 安装精确匹配该触控板的 `TAG+="uaccess"` 规则。
5. `systemctl --user enable --now elan-gesture.service`，链接到 `graphical-session.target.wants`（每次图形会话登录自动启动）。

**如果当前终端没有图形 polkit agent 或 sudo 无密码权限**，安装脚本会保留全部交付物并打印唯一待执行授权命令：

```bash
sudo /home/lancetfish/code/ThinkPad/scripts/bootstrap-permissions.sh --root-stage
# 或 pkexec /home/lancetfish/code/ThinkPad/scripts/bootstrap-permissions.sh --root-stage
```

执行后重新登录/重插触控板，或重启服务：

```bash
systemctl --user restart elan-gesture.service
getfacl -p /dev/input/event11         # 应出现 user:lancetfish:rw-
```

授权只给当前活跃 seat 用户开放这一个触控板节点的读权限；不把用户永久加入 `input` 组，不开放键盘等其他输入设备，程序也绝不以 root 常驻。

## 第一阶段：只读检测

```fish
elan-gesture-probe     # 能力、轴范围、单位换算、权限
elan-gesture-monitor   # 实时 contacts / 每个 tracking ID 坐标 / 方向 / 置信度 / 拒绝原因
```

`monitor` 和 `probe` 都**不会执行任何配置命令**。monitor 示例输出：

```text
t=1762400000.264 contacts=3 state=WATCHING reason=settled ...
contacts_detail=[{"tracking_id":11,"slot":0,"x":100,"y":100,"x_mm":3.23,...},...]
t=1762400000.760 contacts=3 state=ARMED ... direction=up confidence=0.929 ...
```

采集真机事件（仍不执行动作）：

```fish
env PYTHONPATH=/home/lancetfish/code/ThinkPad/src \
  /home/lancetfish/code/ThinkPad/.venv/bin/python -m elan_gesture \
  capture --out /home/lancetfish/code/ThinkPad/docs/captures/real.jsonl
```

回放同一生产代码路径：

```fish
elan-gesture-replay --in docs/captures/real.jsonl
```

## Apple 手势对照

完整矩阵、参数与差异见 [docs/APPLE_GESTURES.md](docs/APPLE_GESTURES.md)。速查：

| Apple 手势 | 触点 | 谁负责 | 命令 |
|---|---|---|---|
| 轻点来点按 / 双指右键 / 滚动 / 捏合 | 1–2 | Niri (libinput) | `--niri-input` 补齐 clickfinger/drag |
| 三指轻点 → 查找与数据检测器 | 3 | daemon | `three_finger_tap` → `elan_gesture.lookup` |
| 四指左/右滑 → 全屏 App 间切换 | 4 | daemon | `FocusColumnLeft/Right` |
| 四指下滑 → App Exposé | 4 | daemon（auto） | 按 overview 状态仲裁 |
| 四指上滑 → 调度中心 | 4 | Niri 原生 | 配置里标记 `provider = "niri"` |
| 拇指+三指张开 → 显示桌面 | 4 | daemon | 切到空工作区，再张开回来 |
| 拇指+三指捏合 → Launchpad | 4 | daemon | `fuzzel` |
| 右边缘双指左滑 → 通知中心 | 2 | daemon | M3 控制中心 → swaync → 通知 |
| 智能缩放 / 页面轻扫 / 旋转 | 2 | 应用或不可用 | 见文档说明 |

使用 Apple 映射：

```fish
cp config/examples/apple-trackpad.toml ~/.config/elan-gesture/config.toml
elan-gesture-restart
elan-gesture-gestures          # 查看哪些手势归 daemon、哪些归 Niri
```

注入后端是可选的。`ydotoold` 未运行时 daemon 照常工作，只是 `type = "inject"` 的动作会失败；`elan-gesture-inject-test` 可以只读诊断：

```fish
elan-gesture-inject-test                 # 默认 dry-run，只打印能力
elan-gesture-inject-test --keys ctrl c --yes   # 真正注入一次用于验证
```

## 四方向自定义配置

编辑 `~/.config/elan-gesture/config.toml`。四种动作类型见 [config/examples/four-directions.toml](config/examples/four-directions.toml)：

- `niri_action`：直接发一个 Niri JSON action，例如 `{"Action":{"FocusWorkspaceUp":{}}}`。
- `niri_spawn`：通过 Niri IPC `Spawn` 传 argv。
- `niri_spawn_sh`：通过 Niri IPC `SpawnSh` 传 shell 命令。
- `command`：守护进程直接启动普通用户命令，默认 `shell=false`。
- `noop` / `enabled=false`：关闭。

改完执行 `systemctl --user restart elan-gesture.service`，或 `kill -HUP $(systemctl --user show -p MainPID --value elan-gesture.service)` 热重载。先用 `[general] dry_run = true` 验证动作日志不实际执行。

## fish / systemd 命令

```fish
elan-gesture-status
elan-gesture-log
elan-gesture-restart
elan-gesture-gestures
elan-gesture-lookup
elan-gesture-inject-test
systemctl --user stop elan-gesture.service
systemctl --user disable --now elan-gesture.service
journalctl --user -u elan-gesture.service -f -o cat
```

`WantedBy=graphical-session.target` + `PartOf=graphical-session.target` 意味着每次 Niri 图形会话登录自动启动、会话退出时停止；这符合 `$NIRI_SOCKET` 只在会话内存在的生命周期。

## 测试与卸载

```bash
./scripts/test-offline.sh           # 71 个 unittest + 29 个 JSONL 回放 + probe/IPC/syntax
./scripts/uninstall.sh              # 停止/禁用/删除服务和 fish/udev；保留配置与报告
./scripts/uninstall.sh --restore-niri # 额外还原 install.sh --niri-input 写过的 Niri 配置
./scripts/uninstall.sh --purge      # 额外删除 .venv、用户配置、captures、报告、日志
```

默认卸载不修改 `~/.config/niri/config.kdl`、内核模块、固件、libinput 配置或任何 X11 设置；只有显式 `--restore-niri` 才会还原 `install.sh --niri-input` 备份过的文件。

## 附加小工具：TouchViz（只显示触点，不注入输入）

`touchviz/` 是一个独立的 GTK4/Cairo 可视化器：把触控板按内核轴范围/物理尺寸映射成一块矩形，逐帧显示每个 `ABS_MT_TRACKING_ID` 的位置、十字准心、压力椭圆、物理按键高亮与 mm 坐标。只读、不 grab、点击穿透，不影响原有输入。

```fish
# 窗口模式（真实设备）
/home/lancetfish/code/ThinkPad/touchviz/run-touchviz.sh --labels

# 透明置顶叠加
/home/lancetfish/code/ThinkPad/touchviz/run-touchviz.sh --transparent --x 40 --y 40 --width 600 --height 400

# 无设备权限时用 JSONL 回放验证
/home/lancetfish/code/ThinkPad/touchviz/run-touchviz.sh \
  --replay /home/lancetfish/code/ThinkPad/tests/fixtures/gesture_up.jsonl --labels
```

详见 [touchviz/README.md](touchviz/README.md) 与预览 [docs/touchviz-preview.png](docs/touchviz-preview.png)。uaccess ACL 已于 2026-11-06 生效，真实设备可直接运行；回放模式仍不需要权限。

## 排错

| 现象 | 检查 |
|---|---|
| `no readable MT input device found` | `getfacl -p /dev/input/event11`；执行 bootstrap-permissions 后重新登录/重启服务 |
| 服务不在 `active` | `journalctl --user -u elan-gesture.service -n 50 -o cat`；确认 `NIRI_SOCKET`、`WAYLAND_DISPLAY` 已由 niri-session 导入 |
| 动作不执行 | `general.dry_run`、对应 `[actions.X].enabled`、`elan-gesture-monitor` 是否达到 `min_confidence` |
| 误判/漏判 | 调 `move_min_mm`、`static_max_mm`、`settle_ms`、`min_confidence`，用 `capture` + `replay` 复现 |
| 原生三指手势叠加 | 默认 `trigger_on="release"` 已降低叠加；不 grab 是「不影响原有手势」的硬约束，见 [docs/LIMITATIONS.md](docs/LIMITATIONS.md) |
| 三指轻点没反应 | `elan-gesture-gestures` 确认 `three_finger_tap` 为 enabled；`elan-gesture-lookup --print-only` 看是否读到选区 |
| 四指下拉把 overview 关了又开 | 该手势应为 `provider = "auto"`；`journalctl` 里看 `niri_overview_busy` |
| 注入类手势不生效 | `elan-gesture-inject-test`；确认 `spawn-at-startup "ydotoold"` 在跑 |
