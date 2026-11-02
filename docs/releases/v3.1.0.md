# v3.1.0 交付说明：主题迁入背景页 + 新增两套纯色主题

## 这次改了什么

**一句话**：主题选择从「外观」页搬进「背景」页，按深色系 / 浅色系分组展示；配色从 2 套扩到 4 套，新增「曜石（纯黑）」与「珍珠（纯白）」，切换逻辑与旧版完全一致（浮动条那个按钮还是「按一下换一套」）。

| 项 | 旧 | 新 |
|----|----|----|
| 主题入口 | 设置 → 外观 → 主题 | 设置 → **背景** → 配色主题 |
| 套数 | 2（星夜 / 月白） | **4**（星夜 / 曜石 / 月白 / 珍珠） |
| 归类 | 无 | 深色系（星夜、曜石）· 浅色系（月白、珍珠） |
| 切换循环 | 深 ↔ 浅 两态 | 深 → 浅 → 深 → 浅 **四态交替** |

## 关键决策（三个）

**1. 挪位置 ≠ 合并概念。** v2.8.3 曾刻意把「主题（配色）」和「背景（底图）」拆成两个正交维度，任何主题配任何背景。这次只是让两者在同一页上管理，正交关系原样保留 —— 已在 DESIGN.md §41 写明，避免后人误以为要回退旧决策。

**2. 名字拆成「意象名 + 明暗」两个字段。** `THEME_LABEL`（星夜/曜石/月白/珍珠）+ `THEME_TONE`（深色/纯黑/浅色/纯白），界面用 `theme_caption()` 拼「曜石 · 纯黑」。不写死成一个字符串，是因为浮动条 tooltip 只需要意象名 —— 否则会读出「切换到星夜 · 深色主题」这种别扭句子。

**3. 循环顺序刻意交替，与展示分组不同。** `THEME_ORDER`（切换用）是 深→浅→深→浅，`THEME_GROUPS`（界面展示）是深色系两项在前。看着矛盾，其实是两个维护不同目标的表：前者保手感（那个按钮的历史语义就是「明暗翻转」，连按两次必须明暗变），后者保分类清晰。两个表都有测试钉住，注释里写明了「刻意不同」。

## 纯色主题的两个坑

- **`BG=#000000` 会让层次全消失**：窗口边界、阴影、面板与窗口底的对比度变成 1.0，看着像没渲染完。曜石实际用 `#0a0a0c`，肉眼看仍是纯黑，但 SURFACE 能差出一档。
- **`#ffffff` 同理**：珍珠必须给 SURFACE 一档差（`#fafafa`），否则面板边缘看不见。

配套新增 `test_pure_themes_are_actually_pure`（亮度 <0.02 / >0.97 + BG≠SURFACE），防止将来有人把值改回"教科书纯色"。

## 改动文件

| 文件 | 改动 |
|------|------|
| `ui/theme.py` | 新增 `OBSIDIAN` / `PEARL` 两套 Theme；`THEMES` 扩到 4；新增 `THEME_ORDER`（4 态交替）、`THEME_GROUPS`、`THEME_LABEL`/`THEME_TONE`/`theme_caption()` |
| `ui/settings_dialog.py` | 外观页删掉主题行；背景页开头新增「配色主题」区，按 `THEME_GROUPS` 分组两个单选行（组名左对齐固定 46px），下方才是「背景图案」 |
| `ui/main_window.py` | `_toggle_theme()` 改按 `THEME_ORDER` 轮转；`_apply_theme()` 的 toast 用 `THEME_LABEL`；两处过期「两态循环」注释改掉 |
| `ui/float_bar.py` | `set_theme_icon()` docstring 同步为四套配色语义（逻辑本就走 `THEME_NEXT`，无需改代码） |
| `tests/test_theme.py` | 新增 4 例：注册表精确匹配、分组不漏不重、`theme_caption` 拼接、纯色确实纯、顺序明暗交替 |
| `tests/test_e2e.py` | `test_settings_bg_tab_has_preset_cards` 断言改按 `THEME_GROUPS` 顺序；`test_float_bar_theme_toggle` 重写为**从真相源推导的 4 态循环**断言 |
| `DESIGN.md` | 新增 §41（命名表、配色硬约束、4 态循环理由、5 条风险处理） |
| `README.md` | 「双主题」改为「四套配色主题」，注明在「设置 → 背景 → 配色主题」按深色系/浅色系分组 |
| `app/version.py` | 3.0.9 → **3.1.0** |

## 那个"失败"的测试其实抓到了真东西

`test_float_bar_theme_toggle` 原来写死「初始浅色 → 点一下变深色 → tooltip 含"切换到深色主题"」这套两态语义。四套配色上线后它失败了，报 `'切换到深色主题' not found in '切换到曜石主题'`。

**这不是测试脆弱，是它正确地发现了语义变更。** 但直接改成「断言切换到曜石」会把同样的坑留给下一次加主题，所以重写成：

```python
def check(cur):
    nxt = THEME_NEXT[cur]
    assert settings.theme == cur
    assert btn._kind == THEME_ICON[nxt]
    assert f"切换到{THEME_LABEL[nxt]}主题" in btn.toolTip()
    assert btn.isChecked() == (THEME_ICON[cur] == "sun")

for _ in range(len(THEME_ORDER)):   # 走一整圈
    window._toggle_theme()
    cur = THEME_NEXT[cur]
    check(cur)
assert cur == "light"               # 闭环回起点
```

这样它守的是「切换逻辑一致性」这个真需求（用户原话），而不是某个具体名字 —— 下次加到 5 套、6 套都不用改。

## 验证

- `ruff check .` → All checks passed
- `test_theme.py` / `test_dialogs.py` / `test_widgets.py` / `test_build.py` / `test_store.py` / `TestE2EAppearance` / `TestE2EThemeBackground` 全绿
- 四套 QSS 均正常生成：columbina 13146 字符（含渐变），其余 3 套 13079 字符（无渐变）
- `TestE2EV2` 单类回归（本轮修完后重跑）
- 打包后 `--check-ai` 自证版本号

## 遗留

- 主题图标仍是月亮 / 太阳两套复用（深色系内重复、浅色系内重复）。真正的区分在 tooltip 与设置页文案上，四个专属图标属视觉优化。
