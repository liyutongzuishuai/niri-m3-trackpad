# Apple 触控板手势 → ThinkPad Elan / Niri 落地对照

来源：[在 Mac 上使用多点触控手势](https://support.apple.com/zh-cn/102482)（Apple 支持，2025-12-22 版）。

目标：在这台 Fedora 44 + Niri 26.04 + Elan Touchpad（`04f3:002f`，98×60 mm，max slot 4）上尽量复刻 Mac 体验，同时坚持「不 grab 设备、不 root 常驻」。

## 1. 15 项总表

| # | Apple 手势 | 触点 | provider | 落地 | 状态 |
|---|---|---|---|---|---|
| 1 | 轻点来点按 | 1 | niri | libinput `tap`（Niri 已启用） | 原生可用 |
| 2 | 辅助点按（右键） | 2 | niri | libinput `click-method "clickfinger"` | 需 `--niri-input` |
| 3 | 智能缩放（双指双击） | 2 | app | 应用/浏览器自身缩放 | 不做（应用已有） |
| 4 | 滚动 | 2 | niri | libinput `natural-scroll` | 原生可用 |
| 5 | 放大或缩小（捏合） | 2 | app | Niri `pinch-sensitivity` 把事件交给应用 | 原生可用 |
| 6 | 旋转 | 2 | — | Wayland/libinput 无 rotate 协议 | **不支持** |
| 7 | 在页面之间轻扫 | 2 | app | 水平滚动 + 应用快捷键 | 不做（应用已有） |
| 8 | 打开通知中心（右边缘左滑） | 2 | daemon | `two_finger_edge_left` → `niri_dynamic notify-center` | **新增** |
| 9 | 三指拖移 | 3 | niri | libinput `drag` + `drag-lock`（tap-and-drag） | 需 `--niri-input` |
| 10 | 查找和数据检测器（三指轻点） | 3 | daemon | `three_finger_tap` → `elan_gesture.lookup` | **新增** |
| 11 | 显示桌面（拇指+三指张开） | 4 | daemon | `thumb_spread_open` → `niri_dynamic show-desktop` | **新增** |
| 12 | App / Launchpad（拇指+三指捏合） | 4 | daemon | `thumb_spread_pinch` → `fuzzel` | **新增** |
| 13 | 调度中心（四指上滑） | 4 | niri | Niri 原生四指垂直滑动 = overview | 原生可用 |
| 14 | App Exposé（四指下滑） | 4 | auto | `four_finger_down` → `niri_dynamic app-expose` | **新增** |
| 15 | 在全屏 App 之间轻扫（四指左右） | 4 | daemon | `four_finger_left/right` → `FocusColumnLeft/Right` | **新增** |

`provider` 的含义：

- `niri`：合成器已经处理，daemon **只观察不派发**，避免一次手势触发两次。
- `daemon`：daemon 全权负责。
- `auto`：手势开始时查一次 `OverviewState`，再决定是否派发。
- `app`：应用自己的行为，daemon 不介入。

## 2. 为什么必须排他

Niri 原生已占用这些触控板手势（见 [niri Gestures](https://niri-wm.github.io/niri/Gestures.html)）：

| 原生手势 | 效果 |
|---|---|
| 三指垂直滑动 | 切换工作区 |
| 三指水平滑动 | 水平移动视图 |
| 四指垂直滑动 | 开/关 overview |

由于本项目**不 grab**，Niri 一定会收到同样的触点。因此：

- 四指上滑（Apple 调度中心）→ 直接交给 Niri，daemon 配 `provider = "niri"` 且 `enabled = false`。
- 四指下滑（Apple App Exposé）与 Niri 的「关闭 overview」同向冲突 → 用 `provider = "auto"`：手势开始时查询 `OverviewState.is_open`；已打开就让 Niri 关闭，未打开才触发 App Exposé。
- 四指左右滑动在 Niri 中没有绑定 → daemon 独占。

## 3. 新增识别器

| 文件 | 识别器 | 判据 |
|---|---|---|
| [tap.py](../src/elan_gesture/tap.py) | `TapRecognizer` | 到达目标触点数后，总时长 ≤ `tap_max_ms`、每指位移 ≤ `tap_max_mm` |
| [swipe.py](../src/elan_gesture/swipe.py) | `SwipeRecognizer` | 质心净位移 ≥ `swipe_min_mm`、正交比 ≤ `swipe_axis_ratio`、各指方向夹角 ≤ `swipe_angle_tolerance_deg`、两两距离变化 ≤ `spread_ratio_min` |
| [spread.py](../src/elan_gesture/spread.py) | `SpreadRecognizer` | 底部边缘优先判定拇指；拇指到其余三指平均极距 `r/r0 ≥ 1+spread_ratio_min`（张开）或 `≤ 1-pinch_ratio_min`（捏合），且拇指自身位移 ≤ `swipe_min_mm` |
| [edge_swipe.py](../src/elan_gesture/edge_swipe.py) | `EdgeSwipeRecognizer` | 双指起点质心落在边缘带 `edge_trigger_mm` 内，向内位移 ≥ `swipe_min_mm`，横向偏移 ≤ 0.6 × 向内位移 |

仲裁在 [engine.py](../src/elan_gesture/engine.py) 里完成，优先级 `tap > spread > edge > swipe > asymmetric`，**同一帧最多派发一个手势**。

## 4. 参数

全部在 `[gesture]` 段，单位 mm 或 ms：

| 键 | 默认 | 作用 |
|---|---|---|
| `tap_max_ms` | 220 | 三指轻点最长按压时间 |
| `tap_max_mm` | 2.5 | 轻点期间单指最大位移 |
| `swipe_min_mm` | 18 | 四指滑动最小质心位移 |
| `swipe_axis_ratio` | 0.35 | 正交分量 / 主轴分量上限 |
| `swipe_angle_tolerance_deg` | 25 | 各指方向与合方向的最大夹角 |
| `spread_ratio_min` | 0.18 | 张开判定阈值，也是滑动时允许的距离漂移上限 |
| `pinch_ratio_min` | 0.18 | 捏合判定阈值 |
| `thumb_edge_mm` | 12 | 拇指与其余三指的垂直间距要求 |
| `edge_trigger_mm` | 15 | 边缘触发带宽度与最小向内位移 |
| `finger_change_timeout_ms` | 800 | 单个手势最长跟踪时间 |
| `ipc_state_timeout_ms` | 200 | 手势开始时的 Niri 状态查询预算 |

## 5. 三指轻点（查找）的动作

`python -m elan_gesture.lookup`：

1. 先读 PRIMARY 选区（Wayland 下文本选中即写入）。
2. 为空时读 CLIPBOARD。
3. 仍为空且允许注入 → 用 ydotool 发 `Ctrl+C`，等 120 ms 再读 CLIPBOARD。
4. 按类型分流：URL 直接 `xdg-open`；日期/电话/邮件只弹通知；其他文本弹通知显示。
5. 全程不联网。设置 `ELAN_LOOKUP_SEARCH_URL`（模板含 `{query}`）才会打开浏览器搜索。

`--print-only` 只打印检测结果，`--no-inject` 禁止合成按键。

## 6. 通知中心

`niri_dynamic notify-center` 的降级顺序：

控制中心其实是**一个独立的 GTK 程序**（`controlcenter.py`），不是 waybar 的内部面板。waybar 的 `custom/panel`（tune 图标）与 `battery` 模块的 `on-click` 都指向 `~/.config/waybar-m3/scripts/control.sh open`，所以手势只需要复用同一条命令，不要求 waybar 进程名是 `integrated-waybar` 或带 `-c ~/.config/waybar-m3`。

`niri_dynamic notify-center` 的行为：

1. 从 `~/.config/waybar/config.jsonc`（以及 m3 配置副本）里解析出 `control.sh` 的 `on-click` 命令，**异步拉起**（GTK 窗口常驻，不能同步等待）。
2. 共享 `controlcenter.py` 的 `$XDG_RUNTIME_DIR/waybar-m3-cc.pid`：窗口已开则发 SIGTERM 关闭它，并清理它 SIGTERM 后残留的 pidfile。因此手势与点击 waybar 按钮可以互相开关同一个面板。
3. 找不到 `control.sh` 且 swaync 在跑 → `swaync-client -t`。
4. 都没有 → 发送一条说明性通知，而不是静默失败（mako 没有可切换的面板）。

## 7. 真机验收清单

```fish
# 1. 只读观察（不执行任何动作）
elan-gesture-monitor

# 2. 灌入 Apple 配置并重启
cp config/examples/apple-trackpad.toml ~/.config/elan-gesture/config.toml
elan-gesture-restart

# 3. 查看当前生效表
elan-gesture-gestures

# 4. 逐个手势各做 5 次
#    三指轻点 / 四指左滑 / 四指右滑 / 四指下滑 / 拇指+三指张开 / 拇指+三指捏合 / 右边缘双指左滑
journalctl --user -u elan-gesture.service -f -o cat

# 5. 若某个手势不触发，录制并回放
env PYTHONPATH=src .venv/bin/python -m elan_gesture capture --out docs/captures/tap.jsonl
env PYTHONPATH=src .venv/bin/python -m elan_gesture replay --in docs/captures/tap.jsonl
```

重点观察：三指轻点是否稳定命中、拇指判定是否选对触点、右边缘双指左滑是否误触发水平滚动。

## 8. 与 macOS 的已知差异

1. **三指轻点必然附带一次鼠标点击**：libinput 的三指 tap 固定映射到 middle（或按 `tap-button-map` 换 right），无法禁用。
2. **App Exposé 不是真的窗口网格**：Niri 没有应用级预览，实现为「聚焦同一个 `app_id` 的下一个窗口」。
3. **显示桌面是切换工作区**：切到空工作区，再张开一次用 `focus-workspace-previous` 回来。
4. **旋转不支持**：没有 rotate 手势协议。
5. **双指手势会同时被 libinput 消费**：不 grab 的固有权衡，右边缘手势靠 15 mm 边缘带降低误触。
