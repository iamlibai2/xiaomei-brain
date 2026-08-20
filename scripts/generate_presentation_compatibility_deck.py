"""Generate a deterministic PPTX deck for Desktop and Office compatibility QA."""

from __future__ import annotations

import argparse
import math
import struct
import sys
import tempfile
import wave
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from xiaomei_brain.plugins.tools.document_presentation.writer import PresentationWriter


def _write_test_tone(path: Path) -> None:
    sample_rate = 16_000
    duration_seconds = 1.2
    frequency = 523.25
    amplitude = 8_000
    frames = bytearray()
    for index in range(int(sample_rate * duration_seconds)):
        fade = min(1.0, index / 800, (sample_rate * duration_seconds - index) / 800)
        value = int(amplitude * fade * math.sin(2 * math.pi * frequency * index / sample_rate))
        frames.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(frames)


def _chart(
    chart_type: str,
    title: str,
    *,
    x_cm: float,
    categories: list[str] | None = None,
    series: list[dict] | None = None,
    colors: list[str] | None = None,
    show_values: bool = False,
    show_percentages: bool = False,
    title_color: str | None = None,
) -> dict:
    chart = {
        "type": "chart",
        "chart_type": chart_type,
        "title": title,
        "x_cm": x_cm,
        "y_cm": 4.0,
        "width_cm": 15.3,
        "height_cm": 12.6,
        "series": series or [],
        "show_legend": True,
        "legend_position": "bottom",
    }
    if categories is not None:
        chart["categories"] = categories
    if colors:
        chart["series_colors"] = colors
    if show_values:
        chart["show_values"] = True
    if show_percentages:
        chart["show_percentages"] = True
    if title_color:
        chart["title_color"] = title_color
    return chart


def _specification() -> dict:
    quarters = ["一季度", "二季度", "三季度", "四季度"]
    palette = ["176B5B", "E2A447", "D5685B", "527A9F"]
    slides: list[dict] = [
        {
            "type": "title",
            "title": "PPT 全面兼容性验收",
            "subtitle": "原生对象生成 · Desktop 预览 · WPS / PowerPoint 打开",
            "background_color": "10241F",
            "theme": {
                "title_color": "F6FAF8",
                "text_color": "BDD2C9",
                "accent_color": "8DD3B7",
            },
            "transition": {"type": "fade", "speed": "medium"},
            "notes": "验收范围：图表、流程形状、表格、公式、媒体、转场与基础动画。",
        },
        {
            "type": "content",
            "title": "分类图表｜柱形与堆积柱形",
            "transition": {"type": "push", "direction": "left", "speed": "fast"},
            "elements": [
                _chart(
                    "column",
                    "季度销售额",
                    x_cm=1.2,
                    categories=quarters,
                    series=[
                        {"name": "华东", "values": [120, 148, 176, 205]},
                        {"name": "华南", "values": [98, 126, 151, 183]},
                    ],
                    colors=palette[:2],
                    show_values=True,
                ),
                _chart(
                    "column_stacked",
                    "成本结构",
                    x_cm=17.35,
                    categories=quarters,
                    series=[
                        {"name": "材料", "values": [62, 68, 74, 79]},
                        {"name": "人工", "values": [22, 24, 26, 28]},
                        {"name": "制造", "values": [16, 18, 19, 21]},
                    ],
                    colors=palette[:3],
                ),
            ],
        },
        {
            "type": "content",
            "title": "趋势图表｜折线与面积",
            "elements": [
                _chart(
                    "line_markers",
                    "月度增长趋势",
                    x_cm=1.2,
                    categories=["1月", "2月", "3月", "4月", "5月", "6月"],
                    series=[
                        {"name": "收入", "values": [42, 48, 53, 67, 76, 92]},
                        {"name": "订单", "values": [31, 37, 45, 52, 66, 79]},
                    ],
                    colors=["176B5B", "D5685B"],
                ),
                _chart(
                    "area",
                    "服务覆盖规模",
                    x_cm=17.35,
                    categories=["1月", "2月", "3月", "4月", "5月", "6月"],
                    series=[{"name": "活跃客户", "values": [18, 26, 35, 47, 61, 78]}],
                    colors=["527A9F"],
                    show_values=True,
                ),
            ],
        },
        {
            "type": "content",
            "title": "比较与占比｜条形、饼图",
            "elements": [
                _chart(
                    "bar",
                    "区域交付效率",
                    x_cm=1.2,
                    categories=["华东", "华南", "华北", "西南"],
                    series=[{"name": "按期交付率", "values": [94, 91, 88, 86]}],
                    colors=["176B5B"],
                    show_values=True,
                ),
                _chart(
                    "pie",
                    "客户行业分布",
                    x_cm=17.35,
                    categories=["制造", "零售", "服务", "其他"],
                    series=[{"name": "客户数", "values": [38, 27, 21, 14]}],
                    colors=palette,
                    show_percentages=True,
                ),
            ],
        },
        {
            "type": "content",
            "title": "坐标与多维｜散点、雷达",
            "elements": [
                _chart(
                    "scatter_lines",
                    "投入与产出",
                    x_cm=1.2,
                    series=[
                        {
                            "name": "项目组合",
                            "x_values": [1, 2, 3, 5, 8],
                            "values": [2, 4, 7, 13, 21],
                        }
                    ],
                    colors=["D5685B"],
                ),
                _chart(
                    "radar_filled",
                    "方案能力画像",
                    x_cm=17.35,
                    categories=["质量", "速度", "成本", "协同", "创新"],
                    series=[
                        {"name": "当前", "values": [82, 76, 71, 88, 79]},
                        {"name": "目标", "values": [92, 86, 80, 93, 90]},
                    ],
                    colors=["176B5B", "E2A447"],
                ),
            ],
        },
        {
            "type": "content",
            "title": "深色主题｜环形图与高对比标题",
            "background_color": "142620",
            "theme": {
                "background_color": "142620",
                "title_color": "F6FAF8",
                "text_color": "C6D9D1",
                "accent_color": "8DD3B7",
            },
            "elements": [
                _chart(
                    "doughnut",
                    "资源投入占比",
                    x_cm=1.2,
                    categories=["研发", "交付", "服务", "运营"],
                    series=[{"name": "占比", "values": [42, 31, 17, 10]}],
                    colors=["8DD3B7", "E8B760", "EE8F83", "87A9C4"],
                    show_percentages=True,
                    title_color="F6FAF8",
                ),
                {
                    "type": "shape",
                    "shape": "round_rect",
                    "x_cm": 19.0,
                    "y_cm": 6.0,
                    "width_cm": 11.0,
                    "height_cm": 5.4,
                    "fill_color": "203A31",
                    "line_color": "8DD3B7",
                    "line_width_pt": 1.5,
                    "text": "验收重点\n切片颜色应各不相同\n中心必须透明\n标题在深色背景清晰可读",
                    "text_color": "F6FAF8",
                    "font_size_pt": 17,
                    "align": "left",
                    "animation": {
                        "effect": "fade",
                        "trigger": "after_previous",
                        "duration_ms": 650,
                    },
                },
            ],
        },
        {
            "type": "content",
            "title": "原生流程形状与连接线",
            "transition": {"type": "wipe", "direction": "left", "speed": "medium"},
            "elements": [
                *[
                    {
                        "type": "shape",
                        "shape": shape,
                        "x_cm": x,
                        "y_cm": y,
                        "width_cm": 5.2,
                        "height_cm": 2.5,
                        "fill_color": color,
                        "line_color": "FFFFFF",
                        "line_width_pt": 1.2,
                        "text": label,
                        "text_color": "17372D" if color == "E2A447" else "FFFFFF",
                        "font_size_pt": 14,
                        "bold": True,
                        "animation": {
                            "effect": "zoom" if index % 2 else "fly",
                            "direction": "left",
                            "trigger": "on_click" if index == 0 else "after_previous",
                            "duration_ms": 450,
                            "delay_ms": index * 40,
                        },
                    }
                    for index, (shape, label, x, y, color) in enumerate(
                        [
                            ("rectangle", "矩形", 1.0, 4.2, "176B5B"),
                            ("round_rect", "圆角矩形", 7.6, 4.2, "527A9F"),
                            ("ellipse", "椭圆", 14.2, 4.2, "D5685B"),
                            ("diamond", "菱形", 20.8, 4.2, "E2A447"),
                            ("hexagon", "六边形", 27.4, 4.2, "6E5C9A"),
                            ("triangle", "三角形", 2.3, 11.0, "527A9F"),
                            ("chevron", "箭头形", 9.3, 11.0, "176B5B"),
                            ("pentagon", "五边形", 16.3, 11.0, "D5685B"),
                            ("parallelogram", "平行四边形", 23.3, 11.0, "E2A447"),
                            ("trapezoid", "梯形", 28.2, 14.4, "6E5C9A"),
                        ]
                    )
                ],
                *[
                    {
                        "type": "line",
                        "connector": connector,
                        "x_cm": start_x,
                        "y_cm": start_y,
                        "to_x_cm": end_x,
                        "to_y_cm": end_y,
                        "line_color": "48645A",
                        "line_width_pt": 1.8,
                        "line_dash": dash,
                        "end_arrow": "triangle",
                    }
                    for connector, start_x, start_y, end_x, end_y, dash in [
                        ("straight", 6.2, 5.45, 7.6, 5.45, "solid"),
                        ("elbow", 12.8, 5.45, 14.2, 5.45, "dash"),
                        ("curve", 19.4, 5.45, 20.8, 5.45, "dot"),
                        ("straight", 26.0, 5.45, 27.4, 5.45, "solid"),
                    ]
                ],
            ],
        },
        {
            "type": "content",
            "title": "原生表格与公式",
            "elements": [
                {
                    "type": "table",
                    "x_cm": 1.2,
                    "y_cm": 4.0,
                    "width_cm": 18.0,
                    "height_cm": 10.8,
                    "column_widths_cm": [5.0, 4.0, 4.0, 5.0],
                    "header_style": {
                        "fill_color": "176B5B",
                        "text_color": "FFFFFF",
                        "bold": True,
                        "font_size_pt": 15,
                    },
                    "cell_style": {
                        "fill_color": "F5F8F7",
                        "text_color": "273630",
                        "font_size_pt": 14,
                    },
                    "data": [
                        ["指标", "当前值", "目标值", "状态"],
                        ["按期交付率", "91%", "95%", "改善中"],
                        ["一次验收通过率", "88%", "93%", "改善中"],
                        ["客户满意度", "4.7", "4.8", "稳定"],
                        ["平均响应时间", "18min", "15min", "需关注"],
                    ],
                },
                {
                    "type": "formula",
                    "x_cm": 21.0,
                    "y_cm": 5.0,
                    "width_cm": 10.0,
                    "height_cm": 3.0,
                    "expression": {
                        "type": "fraction",
                        "numerator": {"type": "nary", "operator": "∑", "lower": "i=1", "upper": "n", "expression": "xᵢ"},
                        "denominator": "n",
                    },
                },
                {
                    "type": "formula",
                    "x_cm": 21.0,
                    "y_cm": 10.0,
                    "width_cm": 10.0,
                    "height_cm": 3.0,
                    "expression": {
                        "type": "radical",
                        "degree": 3,
                        "radicand": {
                            "type": "superscript",
                            "base": "x",
                            "superscript": 2,
                        },
                    },
                },
            ],
        },
        {
            "type": "content",
            "title": "媒体、转场与对象动画",
            "transition": {
                "type": "split",
                "direction": "out",
                "orientation": "vertical",
                "speed": "slow",
            },
            "elements": [
                {
                    "type": "media",
                    "media_kind": "audio",
                    "workspace_path": "work/compatibility-tone.wav",
                    "x_cm": 2.0,
                    "y_cm": 5.0,
                    "width_cm": 7.0,
                    "height_cm": 4.0,
                },
                {
                    "type": "shape",
                    "shape": "round_rect",
                    "x_cm": 12.0,
                    "y_cm": 5.0,
                    "width_cm": 8.0,
                    "height_cm": 4.0,
                    "fill_color": "176B5B",
                    "text": "淡入",
                    "text_color": "FFFFFF",
                    "font_size_pt": 20,
                    "bold": True,
                    "animation": {"effect": "fade", "trigger": "on_click", "duration_ms": 600},
                },
                {
                    "type": "shape",
                    "shape": "round_rect",
                    "x_cm": 22.0,
                    "y_cm": 5.0,
                    "width_cm": 8.0,
                    "height_cm": 4.0,
                    "fill_color": "527A9F",
                    "text": "飞入",
                    "text_color": "FFFFFF",
                    "font_size_pt": 20,
                    "bold": True,
                    "animation": {
                        "effect": "fly",
                        "direction": "left",
                        "trigger": "after_previous",
                        "duration_ms": 600,
                        "delay_ms": 120,
                    },
                },
                {
                    "type": "text",
                    "text": "音频应可播放；切页应有原生转场；两个卡片应按顺序出现。",
                    "x_cm": 3.0,
                    "y_cm": 12.0,
                    "width_cm": 27.8,
                    "height_cm": 2.0,
                    "size_pt": 18,
                    "align": "center",
                    "color": "48645A",
                },
            ],
            "notes": "播放内嵌测试音频，并验证转场与对象进入动画。",
        },
    ]
    return {
        "page": {"size": "wide"},
        "properties": {
            "title": "小美 PPT 全面兼容性验收",
            "subject": "Desktop、WPS 与 PowerPoint 兼容性测试",
            "author": "Xiaomei-Brain",
            "keywords": "PPTX, Desktop, WPS, compatibility",
        },
        "theme": {
            "background_color": "FFFFFF",
            "title_color": "17372D",
            "text_color": "334A42",
            "accent_color": "176B5B",
            "font_family": "Microsoft YaHei",
            "title_size_pt": 30,
            "body_size_pt": 17,
        },
        "slides": slides,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "tmp" / "PPT全面兼容性验收.pptx",
    )
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xiaomei-ppt-acceptance-") as temp_dir:
        tone_path = Path(temp_dir) / "compatibility-tone.wav"
        _write_test_tone(tone_path)
        result = PresentationWriter().write(
            _specification(),
            output,
            asset_paths={"workspace:work/compatibility-tone.wav": tone_path},
        )
    validation = result["validation"]
    print(f"Generated: {output}")
    print(
        "Validation: "
        f"valid={validation['valid']} "
        f"delivery_ready={validation['delivery_ready']} "
        f"slides={validation['slide_count']} "
        f"charts={validation['chart_count']} "
        f"formulas={validation['formula_count']} "
        f"media={validation['media_count']} "
        f"issues={validation['issue_count']}"
    )
    for issue in validation["issues"]:
        print(
            f"- page {issue['page']} [{issue['severity']}] "
            f"{issue['code']}: {issue['reason']}"
        )


if __name__ == "__main__":
    main()
