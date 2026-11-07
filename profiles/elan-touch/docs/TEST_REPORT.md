# 测试报告 — ThinkPad Elan 触控板手势（Apple 复刻）

生成时间：2026-11-06 20:09 CST；Apple 手势移植更新于 2026-11-06 22:20 CST。所有命令均在本机实际执行；原始输出见 [evidence.txt](evidence.txt)、[offline-test.log](offline-test.log)、[replay-matrix.txt](replay-matrix.txt)、[probe.json](probe.json)。

## 1. 环境

| 项目 | 实测值 |
|---|---|
| 主机 | Lenovo ThinkPad E14 20RA002JCD |
| 系统 | Fedora Linux 44 (Workstation Edition) |
| 内核 | `7.2.15-200.fc44.x86_64`（用户描述 7.2.5） |
| 桌面 | Niri 26.04，Wayland，`XDG_SESSION_TYPE=wayland` |
| Shell | fish |
| Python | 3.14.10，系统 `/usr/bin/python3`；项目 `.venv` |
| evdev | `evdev-binary==2.0.0` cp314 wheel，`import evdev` 成功，sha256 经 `pip --require-hashes` 校验 |
| 服务管理器 | systemd 259.10，user manager running，`graphical-session.target` active |

## 2. 真实硬件只读能力勘察

`python -m elan_gesture probe` 在直接 `open()` 被拒绝时，自动回退到 sysfs + `pidfd_getfd` 对 Niri 已持有的 fd 只做 ioctl（**不读事件队列、不 grab**）。原始 JSON 见 [probe.json](probe.json)。

| 判据 | 实测结果 | 结论 |
|---|---|---|
| 节点 | `/dev/input/event11`，`13:75`，`root:input 0660` | 普通用户无读权限 |
| udev | `i2c:04f3:002f`，`ID_INPUT_TOUCHPAD=1`，98×60 mm | 与用户描述基本一致（高度实测 60 mm） |
| EV/KEY | `EV_SYN, EV_KEY, EV_ABS`；`BTN_TOOL_FINGER/DOUBLETAP/TRIPLETAP/QUADTAP/QUINTTAP` | 驱动声明最多五指工具事件 |
| type-B MT | `ABS_MT_SLOT, TRACKING_ID, POSITION_X, POSITION_Y` 全部存在 | **可追踪独立触点** |
| 其他 MT 轴 | `TOUCH_MAJOR/MINOR, PRESSURE` | 可作掌根/压力过滤 |
| 最大 slot | 4（slot 0–4，与用户 evtest 观察一致） | 至少 5 个 slot 地址 |
| X | min 0, max 3052, resolution 31 units/mm | 约 98.45 mm |
| Y | min 0, max 1888, resolution 31 units/mm | 约 60.90 mm |
| 换算 | `scale.units_per_mm_x/y = 31`，来源 `kernel` | 阈值可按 mm 配置 |

**限制**：以上证明驱动声明了 type-B 与三指能力，但不等于已用真实手指证明「三指同时按下时始终给出 3 个独立 tracking ID」。物理采集尚未完成，原因见第 7 节。

## 3. 第一阶段：只读检测代码路径

- `probe`：不打开事件流、不执行动作；输出能力、轴范围、权限、单位换算。
- `monitor`：逐 `SYN_REPORT` 输出 `contacts=N`、每个 `tracking_id` 的 `slot/x/y/x_mm/y_mm/pressure`、状态、静止 IDs、mover ID、方向、置信度、拒绝原因。构造上不创建 `ActionDispatcher`。
- `capture`：写 `(sec,usec,type,code,value)` JSONL；与 daemon 共用 `MTParser` / `GestureDetector`。
- `replay`：读 JSONL 并跑同一生产识别代码。

## 4. 第二阶段：识别与误触测试（全部实际运行）

`./scripts/test-offline.sh`：`unittest discover` **71 tests / OK**；`compileall`、`bash -n`、`fish -n`、`systemd-analyze --user verify` 全部通过。完整输出见 [offline-test.log](offline-test.log)。

新增测试分组：`test_tap`（5）、`test_swipe`（5）、`test_spread`（3）、`test_edge_swipe`（2）、`test_engine`（5）、`test_inject`（7）、`test_niri_dynamic`（9），以及扩展的 `test_config`（+6）与 `test_actions`（+6）。

15 个 JSONL 固件回放结果见 [replay-matrix.txt](replay-matrix.txt)：

| 用例 | 期望 | 实际 |
|---|---|---|
| `gesture_up/down/left/right` | 各触发 1 次对应方向 | PASS：4/4，置信度 0.929 |
| `gesture_fast_up` | 3 帧快速滑动仍识别 up | PASS：up 0.949 |
| `gesture_continuous` | 连续四方向轮转各触发一次 | PASS：up/down/left/right 各 0.929 |
| `repeat_gestures` | 抬指后冷却结束可再次触发 | PASS：2 次 up |
| `false_two_finger_scroll` | 双指滚动不触发 | PASS：0 |
| `false_three_finger_swipe` | 三指同向滑动不触发 | PASS：0，reason `settle_movement` |
| `false_four_finger` | 四指不触发 | PASS：0 |
| `false_static_drift` | 静止指漂移不触发 | PASS：0 |
| `false_short_move` | 位移不足不触发 | PASS：0 |
| `false_diagonal` | 正交分量过大/方向变化不触发 | PASS：0 |
| `false_tracking_id_change` | 中途换 ID 不触发 | PASS：0 |
| `false_syn_dropped` | 丢帧后取消候选 | PASS：0 |

单元测试还覆盖：slot 复用但 tracking ID 改变、触点释放、`SYN_DROPPED` 清空、`BTN_TOOL_QUADTAP` 优先计数、JSONL 时间戳往返、置信度公式边界、多 mover 拒判、配置非法值、Niri IPC 请求/错误响应、`dry_run` 零进程、argv 非 shell、速率限制、noop 动作。

## 4b. Apple 手势 fixture 矩阵（全部实际回放，`--config config/examples/apple-trackpad.toml`）

| 用例 | 期望 | 实际 |
|---|---|---|
| `gesture_three_finger_tap` | 触发 `three_finger_tap` | PASS：confidence 0.773，reason `tap_release` |
| `false_three_finger_tap_moved` | 不触发 | PASS：reason `tap_moved` |
| `false_three_finger_hold` | 不触发（超时） | PASS：reason `tap_too_slow` |
| `false_two_finger_tap` | 不触发（触点不足） | PASS：0 |
| `gesture_four_swipe_left/right` | 各触发对应方向 | PASS：`four_finger_left` / `four_finger_right` |
| `gesture_four_swipe_down` | 触发 `four_finger_down`（provider=auto） | PASS |
| `gesture_four_swipe_up` | 不触发（provider=niri，enabled=false） | PASS：0 |
| `false_four_swipe_short` | 位移不足不触发 | PASS：reason `swipe_too_short` |
| `gesture_thumb_spread_open` | 触发 `thumb_spread_open` | PASS：`radius_ratio≈1.45`，`thumb_travel_mm=0` |
| `gesture_thumb_pinch` | 触发 `thumb_spread_pinch` | PASS |
| `false_four_translate_not_spread` | 四指平移不得判为张合 | PASS：0（由 swipe 判据拒绝） |
| `gesture_edge_swipe_right` | 触发 `two_finger_edge_left` | PASS |
| `false_edge_swipe_middle` | 中部双指滑动不触发 | PASS：reason `not_from_edge` |

`scripts/test-offline.sh` 里的 `gesture expectations (apple profile)` 与 `legacy asymmetric matrix (default profile)` 两段断言会逐条打印 PASS/FAIL，任一不符即退出码 1。

## 5. 第三阶段：动作绑定实测

直接对真实 `$NIRI_SOCKET` 执行（均返回成功）：

```text
{"Ok":{"Version":"26.04"}}
{"Action":{"Spawn":{"command":["true"]}}}       -> {"Ok":"Handled"}
{"Action":{"SpawnSh":{"command":"true"}}}       -> {"Ok":"Handled"}
{"Action":{"FocusWorkspaceUp":{}}}              -> {"Ok":"Handled"}
```

`niri msg action spawn -- /usr/bin/true` 与 `niri msg action spawn-sh -- true` 退出码 0。守护进程日志确认 `Niri IPC handshake: {'Ok': {'Version': '26.04'}}`。

四方向配置示例 [config/examples/four-directions.toml](../config/examples/four-directions.toml) 使用四种不同写法：`niri_action`、`niri_spawn_sh`、`niri_spawn`、`command`。`dry_run=true` 在单元测试中证明不连接 IPC、不启动子进程；`monitor/capture/replay/probe` 不构造 dispatcher。

## 6. 第四阶段：部署实测

`./scripts/install.sh` 实际执行结果：

- 创建 `.venv` 并安装锁定 wheel；
- 写入 `~/.config/elan-gesture/config.toml`、fish helper、`~/.config/systemd/user/elan-gesture.service`；
- `systemd-analyze --user verify` 通过；
- `systemctl --user enable --now elan-gesture.service` → `enabled`、`active (running)`、`ConditionResult=yes`、`ExecMainStatus=0`；
- 服务进程 UID=1000，非 root；日志显示 Niri IPC 握手成功；
- `WantedBy=graphical-session.target` 链接已建立，每次图形会话登录自动启动；
- unit 增加 `Environment=YDOTOOL_SOCKET=%t/.ydotool_socket`，仍是 uid 1000、无 AmbientCapabilities、无 EVIOCGRAB；
- Niri 进程仍持有 `/proc/2883/fd/23 -> /dev/input/event11`，证明未 `EVIOCGRAB`。

fish 语法、bash 语法、unit 语法、配置文件加载均通过。卸载脚本与 `--purge` 分支已做 `bash -n` 语法验证；为避免删除刚安装的服务，本次未实际运行 uninstall。

## 7. 权限、真机事件流与剩余验证

用户已于 2026-11-06 在图形终端完成一次性授权：

```text
Installed /etc/udev/rules.d/72-elan-touchpad-gesture-uaccess.rules
# file: /dev/input/event11
user:lancetfish:rw-
```

当前实测：

- 普通用户 `open('/dev/input/event11', O_RDONLY|O_NONBLOCK)` → `OPEN_OK`；
- `python -m elan_gesture probe` → `direct_open_error=None`，`type_b_mt=True`，内核分辨率 31 units/mm；
- 服务从真实事件流输出 `tracking_id=1730`、`x_mm=50.81`、`y_mm=28.58` 等坐标，不再出现设备不可用重试；
- 独立 4 秒 `capture` 记录 1388 条原始事件，包含 `ABS_MT_TRACKING_ID=1731`、X/Y、pressure、touch major/minor；
- 该文件回放 280 帧，`touchviz` 解码器同样得到最大 1 个真实触点；
- TouchViz 真实设备窗口模式、透明叠加模式、回放模式均连续运行到 4 秒 timeout（exit 124），不再闪退。

**尚待本地补做**：

- 原有「两指静止 + 第三指上/下/左/右」各 3 次，以及双指滚动 / 普通三指滑动 / 四指 / 点击掌根误触各 10/10/5/5 次；
- Apple 手势：三指轻点 20 次、四指左/右滑各 10 次、拇指张合各 10 次、右边缘双指左滑 10 次、四指下滑在 overview 开/关两态各 5 次。

静态能力与单指事件已证明 type-B 身份追踪，离线 fixture 已证明识别逻辑，但都不替代真机物理验证。清单与命令见 [APPLE_GESTURES.md](APPLE_GESTURES.md) 第 7 节。

录制命令：

```fish
env PYTHONPATH=src .venv/bin/python -m elan_gesture \
  capture --out docs/captures/real-$(date +%s).jsonl
```

`capture` 现已在 SIGTERM/SIGINT 时落盘，可直接用 `timeout -s TERM 8s ...` 做有界采集。

## 8. 命令速查

```fish
elan-gesture-probe
elan-gesture-monitor
elan-gesture-gestures
elan-gesture-lookup --print-only
elan-gesture-inject-test
elan-gesture-log
elan-gesture-status
elan-gesture-restart
systemctl --user stop elan-gesture.service
./scripts/test-offline.sh
./scripts/uninstall.sh
./scripts/uninstall.sh --purge
```
