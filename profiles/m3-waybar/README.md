# waybar-m3

把「Material 3 Expressive Web 应用」那份提示词，翻译成一份**能直接跑的 waybar 配置**。

针对你这台机器的实际情况做的适配（都验证过，不是猜的）：

| 事实 | 影响 |
|---|---|
| 合成器是 **niri 26.04**（不是 Hyprland/Sway） | 工作区模块用 `niri/workspaces`，窗口定位用 `niri msg` |
| **waybar 0.15** 自带 `pulseaudio/slider`、`backlight/slider` | 滑块用原生模块，**真的可以拖动**，不用自己画 |
| 启动器是 **fuzzel**（没有 rofi） | 搜索栏与面板都走 fuzzel，配色由 colors.css 注入 |
| 通知守护是 **mako**（没装 dunst/swaync） | 消息来源优先 `makoctl list -j` |
| 你已有的 `~/.config/waybar/` 用 **Matugen 配色 + em 相对单位 + 透明底** | 本配置沿用同一套策略，颜色角色名同构，可直接互换 |

---

## 尺寸：横向按草图，竖直压扁

第一版按你 bar 的 34px 等比缩到 0.53，结果一行只占 45% 宽度、M3 形体感也没了；
后来回到草图的 dp 值（56px 高），又偏高。现在**两个方向分开定**：
横向保留草图的宽度，竖直压到 40px。

| 组件 | 提示词 | 现在 | 备注 |
|---|---|---|---|
| 图标按钮 | 56dp 圆形 | `2.22em` (40px) 圆 | |
| 时钟 | 28sp | `1.22em` (22px) | |
| 搜索栏 | 56dp 高 | `12em × 2.22em` (216×40) | 宽度保留 |
| 容器框 | 412×52dp | `22.89em × 2.11em` (**412×38**) | 宽不动，只压高度 |
| 滑块轨道 | 16dp 粗 | `4.67em × 0.56em` (84×10) | 粗细压扁；长度也收了 16px，给右侧状态集群让位 |
| 滑块手柄 | 4×44dp | `0.22em × 1.67em` (4×30) | |
| 屏幕边缘 | 16dp | `0.89em` (16px) | |

实测：`Bar configured (width: 1536, height: 40)`。

**「铺满」不再依赖尺寸** —— 三区布局（左/中/右）本身就把内容拉到两侧，所以压扁高度不会让一行变短。

### 想再扁一点 / 再宽一点

`style.css` 开头列了两组数，各改各的：

| 方向 | 改哪些 | 现值 |
|---|---|---|
| 竖直（扁平度） | `#workspaces button` / `#custom-search` / `#custom-mic` 的 `min-height`、`#custom-media` 的 `min-height`、滑块 `trough` 与 `slider` 的 `min-height` | 40 / 40 / 40 / 38 / 10 / 30px |
| 横向（铺满感） | `#custom-media` 与 `#custom-search` 的 `min-width`、滑块 `trough` 的 `min-width` | 412 / 216 / 84px |

## 布局：左右铺满 + 中间居中

| 区 | 模块 |
|---|---|
| 左 | `niri/workspaces` · `clock` · `custom/search` · `custom/mic` |
| 中 | `custom/media`（容器框，草图中 6 个元素的第 4 个 —— 正中间那个） |
| 右 | `tray` · `pulseaudio/slider` · `backlight/slider` · `battery` · `custom/wifi` · `custom/bluetooth` · `custom/panel` |

`"fixed-center": true` 是关键：waybar 默认只在「左右剩下的空间」里居中，两侧宽度不等时中间那组就会偏；
加了它才是真正的**屏幕中线**。元素顺序仍与草图一致：图标 → 时钟 → 搜索 → 容器框 → 滑块。

### tray：在滑块左边，带 M3 胶囊底色

`modules-right` 的顺序是 `tray` → `pulseaudio/slider` → `backlight/slider`
→ `battery` → `custom/wifi` → `custom/bluetooth` → `custom/panel`，整组靠右对齐。
tray 用和其他胶囊同一套语言：`surfaceContainerHigh` + 半高圆角（38px 高 → 19px 圆角），
悬停升到 `surfaceContainerHighest`。托盘右键菜单也用 M3 配色（`#tray menu`）。

图标尺寸设成 **32**：waybar 源码里 `icon_size(16)` 是默认值，而且它会按这个尺寸缩放应用给的
pixbuf（`item.cpp` 里 `scale_simple(width, scaled_icon_size, ...)`），所以 32 就是精确的两倍。
想再调只改 `config.jsonc` 里 `tray.icon-size`。

### 右侧状态集群：电量 · Wi-Fi · 蓝牙 · 控制中心

滑块右边新增四个模块，按「一个状态组」来设计：一个电量胶囊 + 三个 38×38 圆形按钮。

| 模块 | 是什么 | 左键 | 右键 |
|---|---|---|---|
| `battery` | waybar 原生电池模块（BAT0），图标 + 百分比 | 开控制中心 | 开控制中心 |
| `custom/wifi` | `scripts/wifi.sh`，JSON 输出 | 开 / 关 Wi-Fi | 选网络 |
| `custom/bluetooth` | `scripts/bluetooth.sh`，JSON 输出 | 开 / 关蓝牙 | 设备列表 |
| `custom/panel` | `scripts/control.sh`，tune 图标 | 开控制中心 | — |

三种状态用同一套 M3 语言表达（class 由脚本的 JSON 给出）：

| class | 底色 | 图标色 | 含义 |
|---|---|---|---|
| `on` | `primary` 实底 | `on_primary` | 开关就是开着的 |
| `off` | `surfaceContainerHigh` | `outline` | 开关关着 |
| `na` | `surface` 深底 + 2px `outlineVariant` 边 | `outline` | 没有硬件 / 没有工具 |

**`na` 为什么不用「整体降透明度」**：一开始是那么做的，实测在深色壁纸上
（梵高星夜，蓝紫色碎块）半透明按钮会糊成一团，比正常的 off 按钮更难看清。
改成「更实的深底 + 一圈 2px 边框」之后，边界就清楚了 —— 这也是设计稿里
「不可用」和「关闭」必须能一眼区分的要求。

#### 本机没有蓝牙适配器

`systemctl is-active bluetooth` 是 `active`，但 `bluetoothctl list` 是空的，
`bluetoothctl show` 报 `No default controller available` —— 没有硬件。
所以蓝牙按钮现在固定落在 `na` 档。**接上适配器后不用改任何配置**，
脚本会自己给出 `on` / `off`，样式已经备好了。

#### Wi-Fi 开关为什么用 nmcli 而不是 rfkill

本机 `/dev/rfkill` 不存在：

```
$ rfkill list
rfkill: cannot open /dev/rfkill: 没有那个文件或目录
```

所以开关走 `nmcli radio wifi on|off`。另外 `nmcli` 的输出**必须加 `LC_ALL=C`**：
中文环境下 ACTIVE 列是「是 / 否」，只有 C locale 才是稳定的 `yes` / `no`：

```
$ LC_ALL=C nmcli -t -f ACTIVE,SSID,SIGNAL device wifi list --rescan no
yes:A401_5G:59
no:A401:82
```

（`IN-USE` 那一列在本机一直是空字符串，不能用，所以判据用 `ACTIVE`。）

### 控制中心：GTK3 图形面板

第一版用 fuzzel 做，只能弹一列文本，做不出设计稿里的「2×2 开关卡 + 真滑块 + 电量卡 + 网络列表」。
现在是 `scripts/controlcenter.py`：GTK3 + `gtk-layer-shell`，贴屏幕右上角，
尺寸和 `design.html` 第 5 节一一对应。

| 元素 | 设计稿 | 实现 |
|---|---|---|
| 面板 | 376px 宽 · 圆角 26 · 内边距 16 | 同（`Gtk.Window` + 自定义 CSS） |
| 开关卡 | 圆角 20 · padding 10 · gap 8 | 同（`Gtk.Grid` 2×2，`EventBox` 整卡可点） |
| 滑块 | 轨道 12px · 手柄 4×24 | `Gtk.Scale` 真控件，可拖 |
| 电量卡 | 圆角 20 · 图标26/数字22 · 节电胶囊 | 同 |
| 网络行 | 圆角 12 · 选中 primary 20% · ✓ | 同，点击即连 |
| 页脚 | 三个按钮 · 圆角 16 | 同 |

**行为**：点开关卡立刻切系统状态并刷新卡面；滑块**松手才写系统**（拖动时逐像素写会卡）；
Esc 或点 ✕ 关闭；再点一次 bar 上的 tune 按钮会关掉已经开着的面板（pidfile 单实例）。

#### `control.sh` 会自动挑实现

```bash
control.sh            # 有 PyGObject + gtk-layer-shell → 图形面板；否则退回 fuzzel
control.sh --fuzzel   # 强制用 fuzzel 版（调试用）
```

`install.sh` 现在也会安装 `scripts/*.py` —— 之前只装 `*.sh`，
导致装完点 tune 按钮没反应（`control.sh` 找不到 `controlcenter.py`）。

#### 性能模式

电量卡右侧的胶囊（设计稿里是静态的「节电」，这里做成可点）：

```
节能 → 平衡 → 性能 → 节能 …
```

| 档位 | 图标 | tuned profile | platform_profile | governor |
|---|---|---|---|---|
| 节能 | eco 叶子 | `powersave` | low-power | powersave |
| 平衡 | 电池 | `balanced` | balanced | powersave/schedutil |
| 性能 | 闪电 | `throughput-performance` | performance | performance |

**为什么用 tuned 而不是直接写 sysfs**：本机 `/sys/firmware/acpi/platform_profile`
是 `root:root 644`，普通用户写不了；而且它只影响 platform_profile，
governor / EPP 得另写。tuned 一次全改好，而且它的 polkit 规则
`com.redhat.tuned.switch_profile` 是 `allow_active=yes` ——
**普通用户切换不需要密码**。实测三档都对。

本机没装 power-profiles-daemon（`systemctl is-active` 是 inactive、也没有
`powerprofilesctl`），所以不能用它。

切换是循环的：`tuned-adm profile <名>`，失败就退回真实状态（不会把界面卡在假值上）。

#### ★ GTK3 的两个坑（都踩过）

**1. `EventBox` 必须 `set_visible_window(True)` 才会画 CSS 背景。**
设成 `False` 时卡片完全没有底色，因为窗口是 RGBA + layer-shell 透明的，
结果壁纸上的代码文字直接透进面板里，四张卡也糊成一片。同时把 CSS 里的
半透明色换成实色 —— `design.html` 里用 0.95 是因为底下已铺了一层不透明面板，
layer-shell 窗口没有那层。

**2. 图标标签必须同时带 `mi` 类。**
只加尺寸类（`b-ico` / `t-ico`）不加 `mi`，字体会掉到默认字体，
而本机 Nerd Font 也声明了 `U+EBD4`、`U+E63E`、`U+EF5E`、`U+E88D`、`U+F053`、`U+E643`
这些码点，于是渲染成 Nerd 的图标（电量卡显示成一个层叠状的怪符号）。
`icon_label()` 现在强制加 `mi`。
查某码点是否被 Nerd Font 抢占：
```bash
fc-list ':charset=ebd4' family | grep -c BitstromWera   # >0 就是被抢了
```

**验证过的内容**：Wi-Fi / 勿扰 / 夜览三个开关切换后能还原；
音量亮度写入系统（55%/45% → 再改回 40%/60%）；
面板截图与设计稿逐项对照（卡片底色、Wi-Fi 高亮、网络选中勾、节电胶囊、页脚三按钮）。

### ★ 中线核算：右区已经贴着上限，加模块前必读

`fixed-center` 把中间胶囊钉在屏幕中线，**前提是左右两区都不超过各自可用宽度**。
超出一点点，中间胶囊就会开始被挤偏：

```
可用宽度 = (1536 屏宽 - 32 左右内边距 - 444 中间胶囊) / 2 = 530.0
```

当前实测左区 388.8、右区 **529.6** —— 只剩 **0.4px** 余量，中线偏移 −0.8px
（和加这组模块之前完全一致，算对齐）。

这是实测踩出来的：加完模块后中线偏了 −10.8px，把右区一点点收窄，
偏移跟着变，但**不是线性的** —— 收窄到 529.6 以内时突然回到 0，
因为越过阈值后中间胶囊才重新拿到完整空间。所以只能测，不能算。

要加新模块，先从这几处让出等量宽度：

| 可调项 | 当前值 | 说明 |
|---|---|---|
| 两根滑块轨道 `min-width` | `4.67em` = 84px | 每缩 1px，右区让 2px（两根一起） |
| 电量胶囊 `padding` | 左右合计 16px | 别小于 14px，否则图标贴边 |
| 三个按钮相互 `margin-left` | 3px | 再小就看不出是三个独立按钮了 |

验证方法（会自己跑一次 waybar + 截屏 + 报数）：

```bash
tools/probe-bar.sh .test-runtime/style-tag.css
```

输出里看 `>>> media 中心 ... 偏移 ±x.xx 逻辑px`。绝对值 ≤1px 就算对齐。

### 弹出面板的锚点跟模块位置走

`scripts/lib.sh` 的 `fuzzel_theme_flags` 第 3 个参数是锚点：

| 调用方 | 锚点 | 上边距 |
|---|---|---|
| `search.sh`（搜索栏在左） | `top-left` | 48px |
| `workspace.sh`（按钮在最左） | `top-left` | 48px |
| `panel.sh`（消息面板在右） | `top-right` | 48px |

上边距 48 = bar 高 40 + 8px 间隙，面板落在 bar 下面而不是压住它。
（之前一律 `top-right`，所以点左边的搜索栏会在右上角弹出来。）

### 工作区图标：Nerd Font 的 Fedora logo

用 `U+F30A`（`linux-fedora`），并且**在 span 上显式指定字体族**：

```jsonc
"format-icons": { "default": "<span font_family='BitstromWera Nerd Font Propo' size='x-small'>\uF30A</span>" }
```

两个坑：

1. **Nerd Font 和 Material Symbols 撞码点**。Nerd Font 的图标都在 U+E000–F8FF 私用区，
   而 Material Symbols 也在那儿。实测 `U+EF7A` 在 Nerd Font 里是 `fa-cheese`（奶酪）、
   `U+E31D` 是 `weather-thunderstorm` —— 正好是 search / mic 的码点。
   所以**不能靠字体栈顺序**（谁排前面都会毁掉另一个），必须在 span 上钉死 `font_family`。
2. **Pango 标记的 `size` 不认比例值**。写 `size='0.72'` 会报
   `Value of 'size' attribute ... should be an integer, or a string such as 'small'`，
   整条文字都渲染不出来。只能用关键字：`x-small` = 0.694 × 基准 = 12.5px，
   实测图标墨迹 17.4px ≈ 数字「1」的 17px，视觉等高。

想让别的模块居中（比如时钟，跟你现有那条 bar 一样）：把 `clock` 从 `modules-left` 挪到
`modules-center` 里即可，中间那组会整体居中。注意放在 `modules-center` 的模块左右 margin 必须对称
（`style.css` 里容器框已写成 `margin: 0 0.44em`），否则会偏离中线。

### 整体缩放

改 `style.css` 里 `*` 的 `font-size`（基准 18px，1em = 18px）会**两个方向一起**缩放：

| 基准 | bar 高度 | 容器框 |
|---|---|---|
| 18px | 40px | 412×38 |
| 15px | 33px | 343×32 |
| 12px | 27px | 275×25 |

只想压高度、不动宽度的话，用上面那张「竖直」表，别动 `font-size`。

### em 的坑（踩过，记一笔）

CSS 的 em 是按**元素自己的 font-size** 解析的。写成
`#custom-media { font-size: 1.56em; min-height: 2.89em }` 时，2.89em 会按 28px 算 = **81px**，
而不是想要的 52px —— 实测 bar 高度变成 82px，比最初你嫌大的 72px 还高。
所以本配置的分工是：盒子尺寸留在模块上（模块字号仍是基准 18px），`font-size` 下沉到 `#模块 label`。

---

## 文件

```
config.jsonc              三区布局：左(workspaces·clock·search+mic) 中(media)
                          右(tray·volume·brightness·battery·wifi·bt·control)
style.css                 M3 Expressive 的形状、字体、动效（全部按角色名引用颜色）
colors.css                提示词给定的 M3 深色配色，唯一颜色来源
scripts/
  lib.sh                  颜色解析（从 colors.css 读）、fuzzel 主题、显示宽度截断、json_emit
  wifi.sh                 Wi-Fi 开关 / 网络列表（nmcli，带 LC_ALL=C）
  bluetooth.sh            蓝牙开关 / 设备列表（没有适配器时给出 na）
  control.sh              控制中心入口（有 GTK 就走图形面板，否则退回 fuzzel）
  controlcenter.py        图形控制中心：GTK3 + gtk-layer-shell，照 design.html 还原
  media.sh                检测谁在占用音频输出 → 否则检测消息；点开面板 / 切窗口 / 播放暂停
  messages.sh             消息来源：mako list → mako history → dunst → 消息池
  panel.sh                「屏幕 1 副本」：swaync 优先，否则 fuzzel 右上角面板
  search.sh               搜索栏内容 + 应用搜索 / 窗口切换 / 执行命令
  mic.sh                  语音输入开关（需要 nerd-dictation 或 whisper）
  workspace.sh            工作区选择器 / 下一个工作区
  message-add.sh          往消息池塞一条消息
  slider.sh               备用滑块（字形绘制，给没编译 slider 模块的 waybar）
install.sh                装到 ~/.config/waybar-m3 + 装字体
tools/build-preview.py    用真实数据生成 preview.html
preview.html              效果预览（颜色/文案都来自真实来源）
```

---

## 安装与试跑

```bash
cd waybar-m3
./install.sh                 # 装到 ~/.config/waybar-m3，并补齐字体
waybar -c ~/.config/waybar-m3/config.jsonc -s ~/.config/waybar-m3/style.css
```

`install.sh` **不会动你现有的 `~/.config/waybar/`**。想让现有配置接管它才用 `./install.sh --link`
（会先把原配置备份成 `waybar.bak.<时间戳>`）。

字体：Material Symbols Rounded 不在 Fedora 仓库里，图标会显示成豆腐块。
本机已经装好（`~/.local/share/fonts/waybar-m3/`，Material Symbols Rounded + Roboto），
不需要再执行；换机器时 `install.sh` 会自动下载。
不想要就删掉：`rm -rf ~/.local/share/fonts/waybar-m3 && fc-cache -f`。

---

### 滑块的特点（照设计稿做的）

M3 Expressive 的滑块由四部分组成，缺一不可：

| 部分 | CSS 节点 | 做法 |
|---|---|---|
| 粗轨道 | `trough` | 10px 高 + 半高圆角 |
| 填充胶囊 | `highlight` | `primary` 色，右侧留 4px 缝 |
| 细高手柄 | `slider` | 4×30px 竖线 |
| **末端圆点**（stop indicator） | 无此节点 | 用径向渐变画在 `trough` 右端 |

#### ★ 手柄必须用「负 margin」，否则轨道会被撑粗

waybar 的滑块不是自绘控件，而是一个 **`Gtk::Scale`**（`src/ASlider.cpp`）。
`GtkScale` 会把**手柄的高度算进控件高度**，然后把这份高度摊给 `trough` ——
于是「手柄设 30px 高」的结果是**填充轨道被拉成 31px 厚的粗条**，
看起来完全不像 10px 的细轨道（预览图里是 10px，所以和实际对不上）。

Adwaita 自己的解法是给手柄**负的竖直 margin**，让它溢出细轨道：

```css
#pulseaudio-slider slider {
    min-width: 0.17em;   /* 3px */
    min-height: 1.67em;  /* 30px */
    margin: -0.56em 0;   /* ★ -(30-10)/2 = -10px，让手柄溢出而不是撑粗轨道 */
}
```

Xvfb 里用复刻的 `GtkScale` 实测（像素级）：

| 写法 | 填充轨道高 | 手柄 |
|---|---|---|
| `margin: 0` | **31px** ✗ 粗条 | 4×31px |
| `margin: -0.56em 0` | **11px** ✓ | 3×31px |

手柄宽度按 M3 规范的比例定（手柄宽 / 轨道 ≈ 0.25，10px 轨道 → 2.5px），取 3px。

圆点是设计稿里最容易被忽略的一笔，GTK 没有对应节点，只能画：

```css
background-image: radial-gradient(circle closest-side,
                    @on_surface_variant 0%, @on_surface_variant 65%, transparent 66%);
background-size: 0.33em 0.33em;
background-position: right center;   /* 只能两段式：right 2px center 会报 Junk at end of value */
background-repeat: no-repeat;
```

填充胶囊和手柄之间那道缝用 `highlight { margin-right: 0.22em; }` 实现。

## 配色：从壁纸推导

`colors.css` 不是写死的，而是用 **matugen** 从当前壁纸推导出来的 M3 深色配色。
本机壁纸是 `~/Pictures/Wallpapers/3840px-Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg`，
`scheme-content` 推出来的主色是 `#a9c7ff`（星空的蓝）。

```bash
~/.config/waybar-m3/tools/set-colors.sh              # 用 niri 配置里的壁纸重新推导
~/.config/waybar-m3/tools/set-colors.sh --list       # 先看各 scheme 出什么色
~/.config/waybar-m3/tools/set-colors.sh -t scheme-fidelity
~/.config/waybar-m3/tools/set-colors.sh --prompt     # 还原提示词给的那套紫色
```

同一张壁纸、不同 scheme 的结果（`--list` 会实时算）：

| scheme | primary | secondary | tertiary |
|---|---|---|---|
| `scheme-content`（默认） | `#a9c7ff` | `#bcc7df` | `#ebb5ec` |
| `scheme-fidelity` | `#a9c7ff` | `#bcc7df` | `#ebc16d` ← 星星的黄 |
| `scheme-tonal-spot` | `#a9c7ff` | `#bdc7dc` | `#dcbce1` |
| `scheme-expressive` | `#a0d490` | `#ecb8cd` | `#bbc4fa` |

提示词给的那套紫色完整保留在 `colors.prompt.css`。

**为什么能一键换**：`style.css` 只用 `@primary`、`@surface_container_high` 这类角色名，
脚本也从同一个文件读十六进制值（`scripts/lib.sh` 的 `m3()`），所以只换 `colors.css` 一个文件，
CSS 和所有脚本（容器框文字、滑块、fuzzel 面板配色）会一起变。

**这里有个静默陷阱**：matugen 模板输出的 `@define-color` 是**带前导空格**的
（`    @define-color primary #c7bfff;`，你现有的 `~/.config/waybar/colors.css` 就是这样）。
`m3()` 的正则原本是 `^@define-color`，换成 matugen 生成的配色后会**全部取色失败、
静默退回 error 色（粉红）**，而 CSS 那边看起来完全正常 —— 最难发现的那种错。
现在正则写成 `^[[:space:]]*@define-color` 了。

## 提示词 → waybar 映射

| 提示词里的元素 | 实现 | 备注 |
|---|---|---|
| 图标按钮（public 图标，显示在哪个 workspace） | `niri/workspaces` + `current-only` | 只显示一个 56px 圆形色调按钮。格式是 `{icon} {value}`：**光有 public 图标看不出在哪个工作区**，所以把编号也放进按钮里 |
| 文本「01:01:01」(28sp) | `clock` | `{:%H:%M:%S}`。提示词要求点击不加反馈，所以没有 on-click |
| 搜索栏（类似 rofi，右端 mic） | `custom/search` + `custom/mic` | 两个模块靠左右圆角拼成**一条**胶囊（中间不留缝），mic 单独可点 |
| 412×52 容器框 | `custom/media` | 412×52，圆角 28，surfaceContainerHigh，正文 28px |
| 「zen浏览器：我和我的祖国」 | `media.sh` 读 `pactl -f json list sink-inputs` | 进程名做友好映射（zen→zen浏览器、linuxqq→qq）。有 MPRIS 时用真曲名，否则用 `media.name`（浏览器标签页标题） |
| 点击后从右侧滑入的「屏幕 1 副本」 | `panel.sh` | 装了 swaync 就调 `swaync-client -t`（原生右滑入）；否则 fuzzel 面板锚在右上角，尺寸对齐 212px |
| 「qq：女神」/「我喜欢你」两行 | 面板里的消息条目 | 面板显示「进程名：标题」，选中后复制全文并弹出完整内容 |
| 滑块 ×2（音量 / 亮度） | `pulseaudio/slider` + `backlight/slider` | 原生模块，**可拖动、可点击定位**；M3 的粗轨道 + 竖长手柄用 `trough`/`highlight`/`slider` 三个节点画 |
| M3 深色 Purple 配色 | `colors.css` 的 `@define-color` 角色 | 与 Matugen 角色名同构，可直接用 Matugen 输出覆盖 |
| 圆角 / Roboto / 动效 | `style.css` | 胶囊 = 高度一半；`cubic-bezier(0.2, 0, 0, 1)`，无回弹 |

### 交互一览

| 组件 | 左键 | 中键 | 右键 | 滚轮 |
|---|---|---|---|---|
| workspace 按钮 | 工作区选择器 | — | 下一个工作区 | — |
| 时钟 | 无（提示词要求） | — | — | — |
| 搜索栏 | 应用搜索 | 执行命令 | 窗口切换 | — |
| mic | 语音输入开关 | — | — | — |
| 容器框 | 打开面板（全部） | 播放/暂停 | 切到出声的窗口 | — |
| 音量滑块 | 拖动 / 点击定位 | — | — | — |
| 亮度滑块 | 拖动 / 点击定位 | — | — | — |
| 电量胶囊 | 打开控制中心 | — | 打开控制中心 | — |
| Wi-Fi 开关 | 开 / 关 Wi-Fi | — | 选择网络 | — |
| 蓝牙开关 | 开 / 关蓝牙 | — | 设备列表 | — |
| 控制中心按钮 | 打开控制中心 | — | — | — |

### 消息来源

按顺序取第一个**真的有内容**的（不是第一个“能用”的，否则 mako 装着但缓冲为空时会挡住后面的来源）：

1. `makoctl list -j` —— 当前还挂在屏幕上的通知（真正的未读）
2. `makoctl history -j` —— 历史缓冲（最新的在前）
3. `dunstctl history`
4. 消息池 `$XDG_RUNTIME_DIR/waybar-m3/messages.jsonl`，用 `scripts/message-add.sh <应用> <标题> [正文]` 写入

环境变量：`WAYBAR_M3_MESSAGE_SOURCE=list|history|dunst|spool` 可强制只用某一个来源。
只认“未读”就设 `list`（否则历史里的旧通知也会出现在容器框里）。

---

## 已知限制（GTK3 做不到的部分）

- **按下缩放（scale feedback）和涟漪**：GTK3 CSS 没有 `transform`，也没有涟漪机制。
  改用 M3 的 state layer 表达（悬停 8%、按下 12% 叠加）。
- **行高**：GTK3 CSS 不支持 `line-height`（实测报错 `'line-height' is not a valid property name`），
  行高由字体度量决定，无法指定 M3 的 1.3〜1.5 倍。
- **没有 swaync 时面板没有滑入动画**：fuzzel 不支持动画，只能锚定在右上角。
  `sudo dnf install SwayNotificationCenter` 后 `panel.sh` 会自动改用它。
- **容器框不能原地展开**：bar 高度是固定的，52dp 的框没法就地变成 212dp。
  「展示全部」交给从右侧滑入的面板承载。
- **语音输入**：识别引擎要自备（`nerd-dictation` / `whisper-dictation`），
  或用 `WAYBAR_M3_VOICE_CMD` 指定。没装时 mic 按钮会明确提示，不会假装能用。

---

## 换配色

`colors.css` 是唯一颜色来源：`style.css` 只用 `@primary`、`@surface_container_high` 这类角色名，
脚本也从这个文件里读十六进制值（`scripts/lib.sh` 的 `m3()`）。
所以直接覆盖它就能换主题，例如用你现有的 Matugen 产物：

```bash
cp ~/.config/waybar/colors.css ~/.config/waybar-m3/colors.css
```

角色名同构（`surface_container_high`、`on_surface_variant`…），覆盖后配置和脚本都不用改。

---

## 验证记录

这台机器上实际跑过的检查（不是“应该没问题”）：

- `config.jsonc` 去注释后 JSON 解析通过；7 个模块都有定义
- `style.css` 用 **GTK 的 CssProvider**（waybar 用的同一套解析器）加载通过
- `waybar` 实跑 5 秒：`Bar configured (width: 1536, height: 40)`，stderr 无错误/警告，
  自定义模块的 JSON 输出全部被接受
- 每个脚本单独跑过真实数据：媒体检测到 zen 正在出声 → `zen浏览器：Home / X`；
  屏蔽音频后切到消息状态 → `qq：女神`（正是提示词里的例子）；消息池清空 → 空状态
- Material Symbols 的码点用官方 `.codepoints` 表校对过 —— **`mic` 是 `e31d` 不是 `e029`、
  `search` 是 `ef7a` 不是 `e8b6`**（Material Symbols 与老 Material Icons 不同），
  并用 Pango 实测确认三个图标都能渲染
- 配色：`set-colors.sh` 自带自检 —— 换完配色后逐个确认 `style.css` 与脚本用到的角色都在新文件里，
  不齐就直接报错退出；并实测脚本取色确实跟着新配色变（`#c4c6d0` / `#8d909a` 都来自新调色板）
- 取色正则用你现有那份**带缩进的** `~/.config/waybar/colors.css` 验证过：修好后能读出
  `#c7bfff`，修复前返回空（会静默退回粉红）
- 滑块尺寸：在 **Xvfb** 里用复刻 waybar 结构的 `Gtk::Scale` 探针（`set_name("pulseaudio-slider")`、
  `add_class("module")`、`set_draw_value(false)`、放进 40px 高的行里）渲染后**按像素量**，
  才发现 `margin: 0` 会把轨道撑到 31px；换成负 margin 后是 11px
- 滑块圆点：先拿 GTK 的 CssProvider 逐个试写法 —— `radial-gradient(circle, #x 0 2px, ...)` 报
  「Missing closing bracket」，`background-position: right 2px center` 报
  「Junk at end of value」，最终确定 `circle closest-side` + 两段式 position 可用
- tray 图标尺寸：翻 waybar 源码确认默认是 16（`src/modules/sni/item.cpp` 的 `icon_size(16)`），
  且它会把 pixbuf 缩放到请求尺寸，所以 32 = 两倍是有依据的，不是猜的
- 字体：`fc-match` 确认 Roboto / Material Symbols Rounded 已就位；
  图标码点用 Pango 逐个实测（`get_unknown_glyphs_count()`）确认能渲染
- 弹出位置：用假 fuzzel 拦截实参，确认三个调用方分别收到 `--anchor=top-left/top-right`
- stderr 断言：只查「有没有报错」不够 —— 加上了「必须出现 `Bar configured`」
  和「stderr 里不能有 Gtk-WARNING」，后者抓出了 Pango `size='0.72'` 解析失败
- 修掉一个自己的 bug：`local tmp` + `trap ... EXIT`，函数返回后 local 失效，
  退出时 trap 报「未绑定的变量」且临时目录不会被删（每次点面板/搜索漏一个）。
  改成全局变量 + `m3_mktempdir`，并清理了之前漏下的 3 个目录
