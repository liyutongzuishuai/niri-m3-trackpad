# 架构与数据流

## 用户输入到桌面动作

```text
Elan Touchpad (/dev/input/event11, uaccess ACL)
  │  evdev type-B: SLOT / TRACKING_ID / POSITION_X,Y / PRESSURE / SYN_REPORT
  ├─> elan-gesture.service (uid 1000, O_RDONLY, no grab)
  │     ├─ MTParser: tracking ID 为身份，slot 只为地址
  │     ├─ GestureDetector: 2 静止 + 1 移动 → 方向/置信度
  │     └─ NiriIPC: $NIRI_SOCKET 单行 JSON → Action / Spawn / SpawnSh
  └─> TouchViz (GTK4/Cairo 只读可视化，显示触点与 mm 坐标)

Niri session
  ├─ config.kdl: spawn-at-startup "integrated-waybar"
  ├─ integrated-waybar → waybar -c ~/.config/waybar-m3/config.jsonc -s style.css
  ├─ waybar-m3 scripts → fuzzel / mako / nmcli / pactl / brightnessctl / niri msg
  ├─ controlcenter.py (GTK3 layer-shell): 开关/滑块/电量/网络/性能模式
  └─ Matugen → ~/.config/waybar/colors.css + ~/.config/waybar-m3/colors.css
```

## 配置层

| 层 | 文件 | 谁写 | 是否受备份 |
|---|---|---|---|
| 项目清单 | `manifest.toml` | 维护者 | 否，项目内文件 |
| Profile 快照 | `profiles/**` | 本仓库 | 否 |
| Niri 会话 | `~/.config/niri/config.kdl` | `install_niri_core()` | 是 |
| M3 Waybar | `~/.config/waybar-m3/**` | `install_m3()` | 是 |
| Matugen | `~/.config/matugen/**` | `install_niri_theme()` | 是 |
| Supporting dotfiles | `~/.config/<whitelist>` | `install_niri_supporting()` | 是 |
| Elan 用户配置 | `~/.config/elan-gesture/config.toml` | 仅在不存在时创建 | 否（不覆盖） |
| Elan 服务 | `~/.config/systemd/user/elan-gesture.service` | `install_elan()` | 当前版本直接安装；恢复依赖用户已有 unit 由 restore 处理 |
| udev ACL | `/etc/udev/rules.d/72-...` | 用户已一次性 sudo 执行 | 不在本安装器默认动作内 |

## 颜色流

`matugen image <wallpaper>` → `~/.config/matugen/templates/colors.css` → 两个输出：

1. `~/.config/waybar/colors.css`（旧栏/全局）
2. `~/.config/waybar-m3/colors.css`（M3 栏与控制中心）

`style.css` 只用 `@primary` 等角色名；`scripts/lib.sh` 的 `m3()` 也从同一个 `colors.css` 读取，因此 fuzzel 面板、消息容器、GTK 控制中心都会同步换色。

## 安全边界

- 所有守护进程都是用户级；Niri 自己仍持有触控板 fd，Elan 程序只新增一个独立只读 client。
- 不 `EVIOCGRAB`，因此 Niri/libinput 原有两指滚动、指针、原生手势不受影响。
- 不发送合成输入；TouchViz 的 GTK4 overlay 把 input region 设为空。
- 安装器写 `$HOME` 前逐文件备份；禁止 root；默认 dry-run。
