# 集成级测试入口

综合项目的真实测试由 [../scripts/verify.sh](../scripts/verify.sh) 统一执行；本目录不重复复制上游单元测试。

| 测试 | 命令 | 结果 |
|---|---|---|
| 静态校验 | `python3 ../tools/validate.py --all ..` | OK |
| 全量验证 | `../scripts/verify.sh` | PASS=23 FAIL=0 |
| 隔离安装 | `../scripts/test-install-sandbox.sh` | OK |
| Elan 离线单测 | `PYTHONPATH=../profiles/elan-touch/src ../.venv/bin/python -m unittest discover -s ../profiles/elan-touch/tests -p 'test_*.py'` | 71 tests OK |
| TouchViz 单测 | `../.venv/bin/python ../profiles/elan-touch/touchviz/test_touchviz.py` | 5 tests OK |
| Waybar 短跑（安装后） | `timeout 5s waybar -c ~/.config/waybar-m3/config.jsonc -s ~/.config/waybar-m3/style.css` | 需图形会话 |
| Niri IPC | `niri msg --json version` | 已通过 |

隔离安装产物固定留在项目内 `.sandbox/`，不写 `/tmp`，不触碰真实 `~/.config`。
