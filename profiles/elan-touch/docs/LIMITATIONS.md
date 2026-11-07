# 已知限制与未验证项

## 1. 权限授权已完成

用户已在图形终端执行 `sudo scripts/bootstrap-permissions.sh --root-stage`。最终结果：

```text
Installed /etc/udev/rules.d/72-elan-touchpad-gesture-uaccess.rules
user:lancetfish:rw-
```

`72-` 编号确保 `TAG+="uaccess"` 在 `73-seat-late.rules` 执行 `uaccess` builtin 之前生效；旧 `99-` 规则已自动删除。普通用户 `open('/dev/input/event11', O_RDONLY|O_NONBLOCK)` 现返回成功；服务不再重试设备错误，已从真实事件流输出 tracking ID 与 mm 坐标。

## 2. 驱动支持情况与剩余物理验证

只读 ioctl 与真实事件流均确认标准 type-B MT 能力（slot、tracking ID、X/Y、pressure、touch major/minor、max slot 4）。一次 4 秒真实采集已记录 1388 条单指事件（`docs/captures/live-smoke.jsonl`），回放得到 280 帧、最大 1 个触点，并正确解析 `tracking_id=1788`、X/Y、pressure 与 31 units/mm 坐标。

**尚待用户本地补做**：用真实手指完成「两指静止 + 第三指上/下/左/右」各 3 次及误触测试。若出现以下任一情况，程序会拒绝并写原因，不会伪造识别：

- 三指时只上报 2 个 tracking ID，或静止两指被合并/重映射；
- 静止指坐标跳变超过 `static_max_mm`，或频繁 `SYN_DROPPED`；
- slot 与 tracking ID 在同一帧中不一致到无法重建身份。

用 `capture` 录制、`monitor` 观察、`replay` 复核；必要时把结果写入 `docs/captures/` 并调整阈值。

## 3. 不 grab 的固有权衡

程序不调用 `EVIOCGRAB`，因此 Niri/libinput 仍会收到原始事件，原生三指/四指 swipe 与本项目动作可能叠加。默认 `trigger_on="release"` 会把自定义动作延后到抬指后，配合 `cooldown_ms` 降低叠加。若要求完全抑制原生手势，必须独占设备，违反「不要影响原有鼠标、双指滚动和 Niri 手势」的要求，本项目不采用。

## 4. 尺寸与坐标

udev 实测高度为 60 mm（用户描述 61 mm），内核 `ABS_MT_POSITION_X/Y` resolution 均为 31 units/mm；默认按实测换算。`config.toml` 的 `height_mm` / `units_per_mm_*` 可覆盖。

## 5. 自动启动语义

用户级服务挂在 `graphical-session.target`，即每次图形会话登录时自动启动，而非在 GDM 出现前、无 Wayland socket 时启动。会话退出时随 `PartOf` 停止。

## 6. 依赖与范围

仅使用项目 `.venv` 中的 `evdev-binary==2.0.0`（提供顶层 `evdev` 模块）与系统 Python 标准库；不使用 Touchegg、X11、uinput/ydotool 注入、dbus 运行依赖、pytest 或 root 守护进程。

## 7. Apple 手势移植带来的新限制

### 7.1 三指轻点必然附带一次鼠标点击

libinput 的三指 tap 固定映射到一个按钮（默认 middle，可用 `tap-button-map` 换成 right），没有任何配置项能只保留手势而不产生点击。因此「三指轻点 → 查找」在实际使用中等于「一次中键点击 + 一次查找」。若不能接受，只能关闭 `three_finger_tap`。

### 7.2 四指下滑与 Niri 原生「关闭 overview」同向

Niri 把四指垂直滑动绑定为 overview 开关。四指下滑时 Niri 会关闭 overview，与 Apple 的 App Exposé 语义重叠。本项目用 `provider = "auto"` 在**手势起始帧**查询一次 `OverviewState`：

- 已打开 → daemon 不动作，让 Niri 关闭；
- 未打开 → daemon 触发 App Exposé。

若 IPC 查询超时（`ipc_state_timeout_ms`，默认 200 ms），按 `is_open = False` 处理并记 WARNING，此时可能和 Niri 各动作一次。

### 7.3 App Exposé 不是真正的窗口网格

Niri 没有应用级窗口预览，`niri_dynamic app-expose` 实现为「聚焦同一个 `app_id` 的下一个窗口」。单窗口应用会返回 `app-expose:single-window` 而不动作。

### 7.4 旋转手势不支持

Wayland 与 libinput 都没有 rotate 手势协议，Apple 的双指旋转在 Linux 上只能由应用自己实现，daemon 无法合成。

### 7.5 双指手势会同时被 libinput 消费

「右边缘双指左滑 → 通知中心」在不 grab 的前提下，libinput 仍会把同一批触点当作水平滚动。本项目用 15 mm 边缘触发带 + 向内位移阈值降低误触，但无法彻底消除。

### 7.6 注入只覆盖键盘与滚轮

`inject` 动作只合成键盘组合（ydotool）与滚轮刻度（evdev UInput），**从不合成鼠标移动或点击**，因此不会破坏指针行为。三指轻点默认先读 PRIMARY 选区，只有在选区为空时才注入 `Ctrl+C`，把副作用降到最低。

### 7.7 `provider` 门控只作用于新手势

为了保持与旧配置、旧测试的兼容，`[actions.*]` 的四方向非对称三指识别仍然只在 `ActionDispatcher` 里检查 `enabled`，而 `[gestures.*]` 的新手势在 `Engine` 层就检查。两者行为等价（禁用即不执行），差异只体现在 `monitor`/`replay` 的 `fires` 输出里：旧四方向即使禁用也会出现在 `fires`。

## 8. 尚未完成的真机验证

以下需要在本机用真实手指完成，本次改动没有替代它：

- 三指轻点 20 次，统计命中率与误触（重点观察是否被 libinput 的中键点击干扰）。
- 四指左/右滑各 10 次，确认不与 Niri 的水平视图移动冲突。
- 拇指+三指张开/捏合各 10 次，确认拇指判定选对触点（`monitor` 输出里的 `thumb_tid`）。
- 右边缘双指左滑 10 次，确认不连带水平滚动。
- 四指下滑在 overview 打开/关闭两种状态下各 5 次，确认 `provider = "auto"` 仲裁正确。

录制与回放命令见 [APPLE_GESTURES.md](APPLE_GESTURES.md) 第 7 节。
