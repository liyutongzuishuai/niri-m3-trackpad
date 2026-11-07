# TouchViz：把触控板显示成一块“触控屏”

只显示哪里被按/点击，不注入任何输入事件。`touchviz.py` 用只读 evdev 逐帧显示：

- 每个 `ABS_MT_TRACKING_ID` 一个独立彩色圆点（slot 只作协议地址，不当身份）；
- 内核 X/Y 轴按 `resolution` 或 min/max + 物理尺寸精确映射到触控板矩形；
- 十字准心显示精确位置，标签显示 `ID / mm 坐标 / pressure`；
- `TOUCH_MAJOR` 可选接触椭圆，物理按键按下时圆点放大；
- `SYN_DROPPED` 计数并清空状态，避免显示陈旧触点；
- 全程不 `EVIOCGRAB`，普通用户运行，不影响 Niri、指针、双指滚动或原有手势。

## 直接运行（真实设备）

```fish
/home/lancetfish/code/ThinkPad/touchviz/run-touchviz.sh --labels
```

若 `/dev/input/event11` 还没有 uaccess ACL，窗口会显示明确报错；在图形终端执行一次：

```bash
sudo /home/lancetfish/code/ThinkPad/scripts/bootstrap-permissions.sh --root-stage
```

然后重新登录或重新运行。也可用 `--device /dev/input/event11` 强制指定节点。

## 透明叠加（不挡鼠标）

```fish
/home/lancetfish/code/ThinkPad/touchviz/run-touchviz.sh \
  --transparent --x 40 --y 40 --width 600 --height 400
```

窗口会用 GTK4 Layer Shell 置顶，并把 input region 设为空（点击穿透）。Fedora 44 的 `gtk4-layer-shell` 需要 `LD_PRELOAD` 链接顺序修复，wrapper 已自动处理。

## 无需权限的验证模式

```fish
/home/lancetfish/code/ThinkPad/touchviz/run-touchviz.sh \
  --replay /home/lancetfish/code/ThinkPad/tests/fixtures/gesture_up.jsonl --labels
```

`--replay` 使用上一项目的 JSONL 原始事件，走完全相同的 type-B 解码与坐标映射；适合在没有触控板权限时确认显示逻辑。真实 `capture` 文件也可以直接回放：

```fish
env PYTHONPATH=/home/lancetfish/code/ThinkPad/src \
  /home/lancetfish/code/ThinkPad/.venv/bin/python -m elan_gesture \
  capture --out /home/lancetfish/code/ThinkPad/docs/captures/touchviz.jsonl
/home/lancetfish/code/ThinkPad/touchviz/run-touchviz.sh \
  --replay /home/lancetfish/code/ThinkPad/docs/captures/touchviz.jsonl --labels
```

## 参数

| 参数 | 作用 |
|---|---|
| `--device PATH` | 覆盖自动发现的设备节点 |
| `--config PATH` | 读取 `[device] width_mm/height_mm` 的 TOML |
| `--replay FILE` | 回放 JSONL，不需要设备权限 |
| `--labels` | 显示 tracking ID、mm 坐标、pressure |
| `--transparent --x --y` | 置顶透明、点击穿透叠加 |
| `--width --height` | 窗口尺寸 |

## 精度说明

- X/Y 轴优先使用内核报告的 `resolution`（本机实测 31 units/mm），而不是把原始值粗略拉伸到窗口。
- 触控板矩形按物理宽高比绘制；窗口内先等比缩放再居中，避免非等比拉伸造成位置偏差。
- 坐标范围来自 `EVIOCGABS`，不假定 `event11` 的固定编号；`Capture/replay` 与真实设备共用同一个解析器和轴模型。
