# AGENTS.md — 维护契约

> 给后续 AI / 维护者：**怎么改、按什么顺序改、什么不能改**。
> 仓库：`niri-m3-trackpad`；目标环境 Fedora 44 / Niri 26.04 / Wayland / fish / Python 3.14。

## 0. 最高优先级事实

- 三个 profile 是本机验证过的**内容快照**，不是上游 git 子模块；改上游仓库后要先 diff 再合并，不要直接覆盖。
- 综合安装器默认 **dry-run**，只有显式 `--apply` 才写 `$HOME`。
- 不允许覆盖 `~/.config/waybar`：M3 栏安装在 `~/.config/waybar-m3`。
- 不允许替换整个 `~/.config`：只按 profile 白名单复制。
- 不允许默认执行 `lancetfi.sh` / `lancetfishniri`（会装 RPM / COPR / Flatpak / OMF）。
- 不允许 grab 触控板、root 常驻、改内核/固件/Niri 系统包。

## 1. 三个来源与在本仓库的位置

| profile | 角色 | 处理规则 |
|---|---|---|
| `profiles/m3-waybar` | Material 3 状态栏 + GTK 控制中心 + 字体 + 换色 | 保留上游核心样式/脚本，只做路径归一化与集成 |
| `profiles/niri-dotfiles` | Niri KDL、快捷键、动画、Matugen 模板、fish/foot/fuzzel/mako 等 | 安装脚本仅作历史资料，不默认执行 |
| `profiles/elan-touch` | Elan 触控板 Apple 手势 daemon、udev 规则、service、fish helper、TouchViz | 核心识别器与 service/venv 设计保留 |

## 2. 必须遵守的调用链

```text
manifest.toml
  └─ scripts/install.sh --dry-run/--apply --profile ...
       ├─ backup_dest() -> ~/.local/state/integrated-niri-m3/backups/<RUN_ID>/restore.tsv
       ├─ install_m3()             -> ~/.config/waybar-m3 (+ 用户字体)
       ├─ install_niri_core()      -> ~/.config/niri + ~/.local/bin/integrated-waybar
       ├─ install_niri_theme()     -> ~/.config/matugen + templates.waybar_m3
       ├─ install_niri_supporting()-> ~/.config/<白名单>
       └─ install_elan()           -> ~/.local/share/integrated-niri-m3/elan-touch

scripts/activate.sh --apply
  ├─ pkill waybar; nohup ~/.local/bin/integrated-waybar
  ├─ systemctl --user enable/restart elan-gesture.service
  └─ niri msg --json version

scripts/restore.sh --latest --apply
  └─ 逐行读 restore.tsv，cp -a 回原位置

scripts/verify.sh
  ├─ tools/validate.py --all / --no-hardcoded-home / --sources / --css-roles / --jsonc
  ├─ bash -n / fish -n / compileall
  ├─ elan unittest + touchviz unittest
  └─ docs/validation-report.md
```

## 3. 集成决策（不要无理由推翻）

1. **Waybar 启动器**：KDL 的 `spawn-at-startup` 不展开 `$HOME`，所以必须装 `~/.local/bin/integrated-waybar`，由它自己拼路径 `exec waybar -c ...`；KDL 只改成 `spawn-at-startup "integrated-waybar"`。**启动器里绝对不能用 `pkill -f 'integrated-waybar'`**：`-f` 会匹配脚本自身命令行并杀死它（已实测两次 SIGTERM）。需要重启时用 `pkill -x waybar`。
2. **Matugen 换色**：原模板输出 `~/.config/waybar/colors.css`；追加 `templates.waybar_m3` 输出 `~/.config/waybar-m3/colors.css`。M3 `style.css` 只按角色名引用颜色，`tools/validate.py --css-roles` 会卡住未定义角色。
3. **颜色源**：`profiles/m3-waybar/colors.css` 是唯一颜色来源。
4. **路径可移植性**：活跃脚本/配置不得出现 `/home/lancetfish`；`install_tree` 复制后还会做一次 `sed` 替换。历史 README、问题分析、修复总结、上游快照注释不参与审计。
5. **Elan 路径**：安装后 systemd unit 的 `WorkingDirectory` / `PYTHONPATH` / `ExecStart` 必须指向 `~/.local/share/integrated-niri-m3/elan-touch`，fish helper 的 `ELAN_GESTURE_ROOT` 同理。生成 unit 时从**原始模板** sed，不要改快照本身（否则重复安装会叠加路径）。
5a. **备份去重**：`backup_dest` 用 `BACKED_UP[dest]` 去重，每个目标只备份一次。`install_tree` 覆盖后不要再对同一文件 `backup_dest`，否则备份里存的是新文件、回滚会丢用户原配置（已实测）。KDL 的 `integrated-waybar` / 壁纸绝对路径替换与 `patch_niri_input` 都在 `install_tree` 之后做，且**不再重复备份**。
6. **udev 规则**：必须是 `72-` 前缀，排在 `73-seat-late.rules` 的 `uaccess` builtin 之前。`udevadm trigger` 用位置参数 `DEVPATH`。综合安装器 `bootstrap_permissions()` 会在读不到 `/dev/input/event*` 时通过 `pkexec`/`sudo` 调 `profiles/elan-touch/scripts/bootstrap-permissions.sh --root-stage`；无图形 agent 时打印唯一待执行命令。**不要在沙盒里跑它**（`test-install-sandbox.sh` 带 `--no-bootstrap`）。
7. **控制中心是独立 GTK 程序**，不是 waybar 内部面板。`custom/panel` 与 `battery` 的 `on-click` 指向 `~/.config/waybar-m3/scripts/control.sh open` → `controlcenter.py`（GTK3 + gtk-layer-shell，pidfile `$XDG_RUNTIME_DIR/waybar-m3-cc.pid`）。手势 `notify-center` **从 waybar config.jsonc 解析同一条命令**、异步 `Popen`、共享 pidfile 做 toggle，并清理 SIGTERM 残留的 pidfile。不要再加「waybar 必须是 m3 进程」这种前置判断。
8. **Niri IPC**：`Version` 是 JSON 字符串 `"Version"`；`Spawn`/`SpawnSh` 返回 `"Handled"`；`OverviewState` 用只读请求 `"OverviewState"` 查询。
9. **手势仲裁**：`profiles/elan-touch/src/elan_gesture/engine.py` 是唯一帧入口，优先级 `tap > spread > edge > swipe > asymmetric`，同一帧最多一个 fire。`main.py` 与 `replay.py` 不得再各自实现 release 逻辑。
10. **provider 排他**：`niri` 只观察不派发、`auto` 查 overview 状态、`daemon` 独占。四指上滑固定 `provider = "niri"`，避免与原生 overview 双触发。
11. **注入边界**：`inject` 只发键盘与滚轮，绝不发鼠标移动/点击；`dry_run` 时零进程、零注入、零 IPC。
12. **GTK 窗口生命周期**：TouchViz 用 `Gtk.ApplicationWindow(application=self)`；`GLibUnix.fd_add_full` 替代弃用的 `GLib.unix_fd_add_full`。
13. **完整复现**：`./scripts/install.sh --apply --profile m3-waybar --profile niri-core --profile niri-theme --profile elan-gesture` 一条命令必须做完：装文件、补 `clickfinger`/`drag`/`drag-lock`、`niri validate` 失败回滚、把 KDL 的 `$HOME/...` 换成真实绝对路径、复制壁纸、离线 wheel 建 venv、装 udev 规则、`systemctl --user enable --now`、重启已运行的 waybar。`--no-activate` / `--no-bootstrap` / `--no-niri-input` / `--no-assets` 只是逃生开关。
14. **离线 wheel**：`vendor/wheels/*.whl` 必须与 `requirements.lock` 的 sha256 一致（`tools/validate.py --all` 和 `verify.sh` 都校验）。`install_elan()` 先 `pip install --no-index` 用入库 wheel，再退回 hash 校验下载。donor 路径不再硬编码 `python3.14`。
15. **只用本地目录做验证**：`/tmp` 是 tmpfs（占内存）。所有回归、venv、探针放进 `.sandbox/`（已被 `.gitignore` 忽略），不要写 `/tmp`。

## 4. 修改流程

每次改动至少：

```fish
./scripts/verify.sh
```

改了安装逻辑还要做非破坏演练（HOME 指向沙箱，不碰真实配置）：

```bash
./scripts/test-install-sandbox.sh
```

改 `manifest.toml` 后必须跑：

```fish
python3 tools/validate.py --sources .
python3 tools/validate.py --all .
```

改了手势代码还要在 `profiles/elan-touch/` 里跑：

```fish
./scripts/test-offline.sh
```

## 5. 验证基线（2026-11-06 本机实测）

- `scripts/verify.sh` → `PASS=24 FAIL=0`
- `elan unittest` → **71 tests OK**（含 tap / swipe / spread / edge / engine / inject / niri_dynamic / config / actions）
- `touchviz unittest` → 5 tests OK
- `elan test-offline.sh` → 29 个 JSONL 回放矩阵 + probe + Niri IPC 全绿
- `test-install-sandbox.sh` → 沙盒 `--apply` 全链路通过（wheel 离线安装、clickfinger/drag 补丁、壁纸、KDL 绝对路径）；带 `--no-activate --no-bootstrap`，不碰真实 systemd/udev
- 回滚回归：预存带 marker 的 `~/.config/niri` 与 `matugen`，`install.sh --apply` → `restore.sh --apply` 后两个 marker 均恢复（每个 dest 只备份一次）
- 启动器实测：`integrated-waybar` 能 `exec waybar` 并输出 `Bar configured`，不再自杀
- `niri msg --json version` → `{"cli":"26.04","compositor":"26.04"}`
- 真机触控板 ACL 已生效；daemon 能读到真实 tracking ID 与 mm 坐标；服务 `active`
- 通知中心：手势第 1 次打开、第 2 次关闭，pidfile 无残留

任何改动若让这些数字下降，先修回归，不要加新功能。

## 6. 禁止事项清单

- 不要把 `~/.config/waybar` 改名/删除/链接成 M3 配置；
- 不要默认执行 `sudo dnf`、COPR enable、Flatpak install、Oh My Fish 安装；
- 不要给 Elan 服务加 `User=root` / `AmbientCapabilities` / `EVIOCGRAB`；
- 不要用 `pidfd_getfd` 从 Niri 偷读事件队列（只适合 ioctl 能力探测）；
- 不要删 `restore.tsv`；
- 不要把 README / AGENTS 改成纯教程，代码、脚本、配置、报告都必须真实存在且可跑；
- 不要在没有备份的情况下 sed 修改 `~/.config/niri/config.kdl`；
- 不要重新引入 `99-` udev 规则；
- 不要提交 `.venv`、`.sandbox`、`__pycache__`、真机 `docs/captures/`、`*.log`、`docs/probe.json`（见 `.gitignore`）。

## 7. 常见故障定位

| 症状 | 第一检查 |
|---|---|
| Waybar 起不来/秒退 | 启动器是否误用 `pkill -f 'integrated-waybar'`；`~/.local/bin/integrated-waybar` 是否可执行 |
| 壁纸不显示 | KDL 的 `swaybg` 行是否仍含字面 `$HOME`；`~/Pictures/Wallpapers/` 是否有图（`--assets` 默认开） |
| 双指右键/三指拖移无效 | `touchpad {}` 是否有 `click-method "clickfinger"` / `drag true` / `drag-lock` |
| daemon 读不到触控板 | 是否跑过 udev 授权；`getfacl -p /dev/input/event11` |
| M3 图标豆腐块 | `fc-match "Material Symbols Rounded"` / `fc-match Roboto` |
| 换壁纸后 M3 颜色不变 | `grep -A3 templates.waybar_m3 ~/.config/matugen/config.toml` |
| 控制中心不弹 | 手势是否解析到 `control.sh`；`python3-gobject` / `gtk-layer-shell`；`control.sh open` 单独能否拉起 |
| 通知中心只开关一次就失效 | `$XDG_RUNTIME_DIR/waybar-m3-cc.pid` 是否残留；`niri_dynamic.notify_center` 会主动清理 |
| Elan 服务打不到设备 | `getfacl -p /dev/input/event11`；规则是否 `72-` |
| 三指轻点没反应 | `elan-gesture-gestures` 确认启用；`elan-gesture-lookup --print-only` |
| 注入类手势不生效 | `elan-gesture-inject-test`；`spawn-at-startup "ydotoold"` |
| `verify.sh` 硬编码失败 | `python3 tools/validate.py --no-hardcoded-home .` 列出的文件是否是活跃配置 |

## 8. 交付完成定义

1. `scripts/verify.sh` 退出码 0，`docs/validation-report.md` 的 FAIL 为 0；
2. `install.sh --dry-run --all` 列出所有 profile 且无路径越界；
3. 改了安装器则 `test-install-sandbox.sh` 生成 `restore.tsv`；
4. README / AGENTS.md 与实际路径、命令、profile 名称一致；
5. 未修改上游仓库、未覆盖用户现有配置、未执行系统级包安装；
6. 改动只提交干净文件（见 `.gitignore`）。
