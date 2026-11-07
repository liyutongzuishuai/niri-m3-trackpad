# 整合过程与实测报告

生成时间：2026-11-06。所有结果来自本机命令，原始逐项输出见 [validation.log](validation.log)。

## 1. 阅读与归纳

| 上游 | 读入的关键文件 |
|---|---|
| waybar-m3 | `README.md`、`config.jsonc`、`install.sh`、`style.css`、`colors.css`、`scripts/controlcenter.py` 前 260 行、全部脚本/工具的依赖扫描 |
| lancetfish-niri-fedora | `README.md`、`lancetfi.sh` 全 389 行、`lancetfishniri` 关键段、`config.kdl` 全 820 行、`matugen/config.toml`、旧 waybar `config.jsonc`/`style.css`/`colors.css`、`问题分析.md`、`修复总结.md` |
| 当前 ThinkPad 项目 | Elan 源码、配置、服务、udev 规则、测试报告、TouchViz 源码与测试快照 |

归纳出的冲突：Waybar 启动路径、旧/新 Waybar 共存、Matugen 未同步 M3 颜色、上游硬编码路径、安装脚本过度系统级、Elan/TouchViz 与桌面项目相互独立。

## 2. 实际生成的控制面

- `manifest.toml`：5 个 profile + 3 个集成点 + safety 策略；
- `scripts/install.sh`：默认 dry-run，`--apply` 逐目标备份并生成 `restore.tsv`；
- `scripts/activate.sh`：默认 dry-run，可选重启 Waybar 与 Elan 服务；
- `scripts/restore.sh`：按某次备份恢复；
- `scripts/verify.sh`：22 项校验并写报告；
- `tools/validate.py`：JSONC/TOML/CSS 角色/路径/来源检查；
- `modules/integrated-waybar`、`niri-startup.kdl`、`matugen-waybar-m3.toml`；
- `README.md` 与 `AGENTS.md`：用户说明 + 维护契约。

## 3. 已修复的活跃路径

| 文件 | 原值 | 新值 |
|---|---|---|
| `profiles/elan-touch/fish/conf.d/elan-gesture.fish` | `/home/lancetfish/code/ThinkPad` | `$HOME/.local/share/integrated-niri-m3/elan-touch` |
| `profiles/elan-touch/scripts/test-offline.sh` | 绝对项目路径 | 运行时 `ROOT` / `INTEGRATED_ELAN_ROOT` |
| `profiles/niri-dotfiles/.../config.kdl` | 绝对壁纸路径 | `$HOME/Pictures/Wallpapers/...` |
| `profiles/m3-waybar/colors.css` | 绝对壁纸注释 | `$HOME/...` |
| `profiles/m3-waybar/tools/find-icon.py` | 绝对字体路径 | `Path.home()` |
| `manifest.toml` | 绝对 home/state | `$HOME/...` |

历史 README、问题分析、修复总结、上游快照注释保留原文，不参与活跃路径审计。

## 4. 验证结果

`./scripts/verify.sh`：`PASS=22 FAIL=0`。

覆盖范围：

- manifest / Waybar JSONC / Elan TOML / Matugen TOML 解析；
- bash、fish、Python 语法与 `compileall`；
- 上游 M3 全部 shell 脚本 `bash -n`、`controlcenter.py` 编译；
- M3 CSS 颜色角色全部在 `colors.css` 定义；
- 活跃配置不含硬编码 `/home/lancetfish`；
- profile 来源路径存在；
- Niri 启动片段存在；
- Elan 23 个 unittest、TouchViz 5 个 unittest；
- 运行时命令与 Niri IPC `Version`。

## 5. 隔离安装演练

用户要求把 `/tmp` 里本次演练产物移到项目本地。现已：

- 原 `/tmp/integrated-niri-m3-sandbox` → `.sandbox/home`；
- 原 `/tmp/integrated-sandbox-install.log` 等 → `docs/tmp-artifacts/`；
- `scripts/verify.sh` 的单步输出 → `.sandbox/validation-check.log`；
- 新增 `scripts/test-install-sandbox.sh`，演练 HOME 固定为项目内 `.sandbox/home`；
- 项目自控脚本/文档中不再使用 `/tmp` 作为演练目录。

实际执行：

```text
./scripts/test-install-sandbox.sh
sandbox install OK
docs/sandbox-install.log
.sandbox/state/backups/<时间戳>/restore.tsv
```

演练结果（全部位于项目本地，未触碰真实 `~/.config`）：

- `.sandbox/home/.config/waybar-m3/config.jsonc` 存在；
- `.sandbox/home/.local/bin/integrated-waybar` 存在且语法通过；
- `.sandbox/home/.config/niri/config.kdl` 的启动项改为 `spawn-at-startup "integrated-waybar"`，壁纸路径为 `$HOME/Pictures/Wallpapers/...`；
- `.sandbox/home/.config/matugen/config.toml` 追加 `[templates.waybar_m3]`；
- `.sandbox/home/.config/systemd/user/elan-gesture.service` 的 `WorkingDirectory`、`PYTHONPATH`、`ExecStart --config` 全部跟随沙箱 HOME；
- 沙箱内 `.venv` 离线复制已验证的 `evdev` 模块，`import evdev, evdev.ecodes` 成功；
- `restore.tsv` 记录被修改的 Niri/Matugen 配置。

演练中修掉的四个真实问题：

1. `backup_dest()` 在同一 `local` 声明里引用未生效变量（bash 未绑定变量）；
2. 干净 HOME 没有 `~/.local/bin`，启动器安装失败；
3. 联网 pip 瞬时重置导致 Elan venv 失败；改为优先离线复制本项目已验证的 `evdev` 模块，联网只作回退；
4. 反复 `sed` 会污染快照里的 systemd unit；改为从原始模板按目标 HOME 生成，不改快照。

## 6. 最终回归

`./scripts/verify.sh`：`PASS=23 FAIL=0`。相对首轮 `PASS=22`，新增 `bash -n scripts/test-install-sandbox.sh` 一项。报告见 [validation-report.md](validation-report.md)，逐项输出见 [validation.log](validation.log)。
