---
name: visualize
description: 将数据、关系、过程或抽象概念制作成可在对话中操作的图表、图解、计算器和模拟器
version: 1.0.0
tags: [visualize, interactive, chart, diagram, simulation, explainer]
requires_tools: [write_visualization, present_artifacts]
---

# 可视化工作方法

只有在视觉呈现或交互操作能明显帮助理解、比较、探索或决策时使用本技能。普通文字已经足够时，直接回答，不要为了装饰而生成可视化。

## 选择形式

- 标签和连线足以表达的静态结构，优先在回复中使用 Mermaid。
- 数值比较、趋势和分布可以生成交互图表。
- 参数变化、时间演化、空间运动和练习过程适合生成模拟器或解释器。
- 用户要的是正式网站、独立应用或现有项目改动时，不使用本技能，按项目开发方式处理。

## 输出契约

1. 使用 `write_visualization` 生成可视化，不要使用通用 `write`。文件名只需表达内容，例如 `sales-trend.html`；工具会自动规范为 `.visualization.html`。
2. 文件只包含 HTML 片段，不写 `doctype`、`html`、`head` 或 `body`。
3. CSS 和 JavaScript 可以写在片段内，也可加载下面白名单中的静态资源；不得使用 `fetch`、XHR、WebSocket、iframe、表单提交或页面跳转。
4. 不得访问 Node.js、Electron、文件系统、桌面接口或父页面对象。
5. 文件必须小于 1 MB。大数据先聚合、抽样或降低精度。
6. 根元素必须有唯一 ID，脚本通过这个 ID 查询自己的内容，不能依赖 `document.currentScript`。
7. 使用原生 HTML、SVG、Canvas 和 JavaScript；宿主不保证任何第三方库存在。
8. 完成后调用 `present_artifacts`，将 `write_visualization` 返回的 `output_path` 展示到当前对话。
9. 当 `attached_file` 明确说明它是 Desktop 当前全屏打开的可视化，且用户要求修改它时，先阅读其现有内容，再把该文件的 `id` 作为 `source_attachment_id` 传给 `write_visualization`。这会原位更新同一产物；不要另起文件名，也不要自行拼接绝对路径。用户明确要求“重新做一个”时才创建新可视化。

## 外部资源

仅允许通过 HTTPS 从以下来源加载静态 JavaScript、CSS、字体和媒体资源，其他来源会被宿主静默拦截：

- `cdnjs.cloudflare.com`
- `esm.sh`
- `cdn.jsdelivr.net`
- `unpkg.com`
- `fonts.googleapis.com`
- `fonts.gstatic.com`
- `fonts.bunny.net`

依赖必须固定版本，不使用 `latest`。数据必须直接包含在可视化片段中，不能通过网络 API 获取。数据图表优先使用固定版本的 D3，例如 `https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js`。

## 视觉规范

- Desktop 会提供以下随浅色／深色外观变化的 CSS 变量，按内容和设计需要自行选择，不要求全部使用：
  - 页面与文字：`--background`、`--foreground`。
  - 内容表面：`--card`、`--card-foreground`。
  - 次要信息：`--muted`、`--muted-foreground`。
  - 结构与操作：`--border`、`--primary`、`--primary-foreground`、`--accent`、`--accent-foreground`、`--destructive`。
  - 数据系列：`--viz-series-1` 至 `--viz-series-6`。
- 基础文字、边框和控件可以优先继承宿主变量，以便自然融入 Desktop；业务语义、品牌风格、热力图、渐变和艺术动画可以使用自定义颜色。
- 自定义颜色应同时适配浅色和深色外观，可使用 `light-dark(lightColor, darkColor)` 或在 `:root[data-theme="dark"]` 中提供另一套值，并保证文字、控件和数据标记清晰可读。
- 用户明确要求某种配色或视觉风格时，以用户要求为准。不要为了统一而压平有意义的视觉表达。
- 顶层背景保持透明，不额外套一层大卡片。
- 默认适配 736px 宽度，并能缩小到 320px；内容过窄时换行或纵向排列。
- 不使用固定视口高度、固定定位和页面级滚动条。
- 控件使用原生 `button`、`input` 和 `select`，提供可见标签和键盘操作。
- 图表应标明标题、轴名称、单位和关键数值，不能只靠颜色表达含义。
- 动画只用于状态变化，不做循环装饰，并尊重 `prefers-reduced-motion`。

## 与 Agent 继续对话

如果某个按钮需要让 Agent 继续分析，而不是只改变本地展示，可以调用：

```javascript
window.xiaomei?.sendFollowUpMessage({
  prompt: "分析当前选中的华东地区数据",
  title: "继续分析华东地区"
});
```

这只会把建议内容放入 Desktop 输入框，由用户确认后发送。筛选、切换、拖动和参数调整等展示操作应留在可视化内部完成。

## 宿主音乐播放器

制作音乐播放器、频谱、歌词或音乐演示界面时，不要在可视化中引用 Agent 的绝对路径，
也不要重新创建一套独立播放状态。Desktop 会提供同一个可复用播放器：

```javascript
const unsubscribe = window.xiaomei.media.subscribe((state) => {
  // state.status: buffering / playing / paused / completed / stopped / failed
  // state.title, state.positionMs, state.durationMs
  renderPlayer(state);
});

playButton.onclick = () => window.xiaomei.media.play();
pauseButton.onclick = () => window.xiaomei.media.pause();
stopButton.onclick = () => window.xiaomei.media.stop();
progressInput.oninput = () => window.xiaomei.media.seek(Number(progressInput.value));
volumeInput.oninput = () => window.xiaomei.media.setVolume(Number(volumeInput.value));
```

真实音乐由 Agent 调用 `play_music` 交给当前 Desktop 身体播放。可视化只负责外观和交互，
通过 `window.xiaomei.media` 读取并控制宿主播放器；不要写死 `music/...`、本机绝对路径或
私有 `<audio>` 播放列表。组件卸载时调用 `unsubscribe()`。

## 完成前检查

- 首屏无需操作也能看懂主要内容。
- 所有查询到的元素确实存在。
- 主要控件会更新对应图形或数值。
- 320px 和普通会话宽度下无文字重叠或横向溢出。
- 深色和浅色主题下均可阅读。
- 没有主动网络请求、白名单外资源或宿主访问。
