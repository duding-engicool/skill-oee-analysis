#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OEE 诊断报告生成器（报告装配层）
读取用户投喂的运行数据 JSON → 调用 oee_calculator 计算引擎 → 装配 MD + HTML 双版诊断报告。

输入 JSON 字段（data 为必需，enterprise 可选）：
{
  "device": "设备A",
  "period": "2026年3月",
  "data": {
    "planned_time": 528, "actual_time": 458, "total_output": 18500, "qualified_output": 17945,
    "standard_cycle_time": 90, "downtime_failure": 32, "downtime_changover": 18,
    "idle_time": 8, "speed_loss_time": 6, "startup_time": 4, "quality_loss_time": 2,
    "hourly_output_value": 5000
  },
  "enterprise": {"company": "待企业补充", "annual_hours": "待企业补充", "target_oee": "待企业补充"},
  "notes": ""
}

用法：
  python build_report.py -i input.json -o output_prefix
  → 生成 output_prefix.md 与 output_prefix.html
"""

import argparse
import json
import os
import sys
import html
import subprocess

# 导入同目录的计算引擎
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oee_calculator

# OEE 目标值（行业通行参考，非企业强制标准）
TARGETS = {
    "time_rate": 90.0,      # 时间开动率目标 > 90%
    "performance_rate": 95.0,  # 性能开动率目标 > 95%
    "quality_rate": 99.0,   # 合格品率目标 > 99%
    "oee": 85.0,            # OEE 标杆 > 85%
}

C = oee_calculator  # 别名


def sget(d, k, default=None):
    """安全取值"""
    try:
        v = d.get(k, default)
        return v if v is not None else default
    except Exception:
        return default


def build_args(data):
    """从 data 字典构造引擎所需的 args 对象"""
    args = argparse.Namespace()
    # 必需
    args.planned_time = float(sget(data, "planned_time", 0) or 0)
    args.actual_time = float(sget(data, "actual_time", 0) or 0)
    args.total_output = int(sget(data, "total_output", 0) or 0)
    args.qualified_output = int(sget(data, "qualified_output", 0) or 0)
    # 可选六大损失
    args.downtime_failure = float(sget(data, "downtime_failure", 0) or 0)
    args.downtime_changover = float(sget(data, "downtime_changover", 0) or 0)
    args.idle_time = float(sget(data, "idle_time", 0) or 0)
    args.speed_loss_time = float(sget(data, "speed_loss_time", 0) or 0)
    args.startup_time = float(sget(data, "startup_time", 0) or 0)
    args.quality_loss_time = float(sget(data, "quality_loss_time", 0) or 0)
    # 其他
    args.standard_cycle_time = float(sget(data, "standard_cycle_time", 60) or 60)
    args.hourly_output_value = float(sget(data, "hourly_output_value", 0) or 0)
    return args


def status_tag(value, target, higher_better=True):
    """返回 (达标文本, 是否达标)"""
    if value is None:
        return ("数据缺失", False)
    if higher_better:
        ok = value >= target
    else:
        ok = value <= target
    return ("达标" if ok else "未达标", ok)


def fmt(v, suffix=""):
    if v is None:
        return "—"
    try:
        return f"{v}{suffix}"
    except Exception:
        return str(v)


def generate_md(result, meta, enterprise):
    """装配纯文字 MD 报告"""
    device = meta.get("device", "未命名设备")
    period = meta.get("period", "未指定周期")
    notes = meta.get("notes", "")

    m = result.get("metrics", {})
    sl = result.get("six_losses", {})
    cred = result.get("data_credibility", [])
    imp = result.get("improvement_priority", {})
    roi = result.get("roi_estimation", {})
    warnings = result.get("warnings", [])

    lines = []
    lines.append(f"# OEE 诊断报告 · {device}")
    lines.append("")
    lines.append(f"- **设备**：{device}")
    lines.append(f"- **统计周期**：{period}")
    lines.append(f"- **企业**：{enterprise.get('company', '待企业补充')}")
    if notes:
        lines.append(f"- **备注**：{notes}")
    lines.append("")

    # 一、OEE 三大指标
    lines.append("## 一、OEE 三大指标")
    lines.append("")
    lines.append("| 指标 | 实际值 | 目标值 | 达标 |")
    lines.append("|------|--------|--------|------|")
    tr, tr_ok = status_tag(m.get("time_rate"), TARGETS["time_rate"])
    pr, pr_ok = status_tag(m.get("performance_rate"), TARGETS["performance_rate"])
    qr, qr_ok = status_tag(m.get("quality_rate"), TARGETS["quality_rate"])
    oe, oe_ok = status_tag(m.get("oee"), TARGETS["oee"])
    lines.append(f"| 时间开动率 | {fmt(m.get('time_rate'))}% | {TARGETS['time_rate']}% | {tr} |")
    lines.append(f"| 性能开动率 | {fmt(m.get('performance_rate'))}% | {TARGETS['performance_rate']}% | {pr} |")
    lines.append(f"| 合格品率 | {fmt(m.get('quality_rate'))}% | {TARGETS['quality_rate']}% | {qr} |")
    lines.append(f"| **OEE（综合）** | **{fmt(m.get('oee'))}%** | {TARGETS['oee']}% | **{oe}** |")
    lines.append("")
    if warnings:
        lines.append("> ⚠️ 数据完整性提示：" + "；".join(warnings))
        lines.append("")

    # 二、六大损失分布
    lines.append("## 二、六大损失分布")
    lines.append("")
    ratios = sl.get("ratios_percent", {})
    ranking = sl.get("ranking", [])
    if ratios:
        lines.append("| 排名 | 损失类型 | 占计划运行时间比 |")
        lines.append("|------|----------|------------------|")
        for i, item in enumerate(ranking):
            lines.append(f"| {i+1} | {item.get('loss_type')} | {fmt(item.get('ratio'))}% |")
        lines.append("")
        if ranking:
            top = ranking[0]
            lines.append(f"> 最大损失项：**{top.get('loss_type')}**（占比 {fmt(top.get('ratio'))}%），为优先改善对象。")
            lines.append("")
    else:
        lines.append("> 未提供六大损失明细数据，无法拆解损失构成。建议补充停机/降速/质量损失时间以定位改善重点。")
        lines.append("")

    # 三、数据可信度检测
    lines.append("## 三、数据可信度检测")
    lines.append("")
    if cred:
        lines.append("| 指标 | 检测值 | 风险 | 说明 |")
        lines.append("|------|--------|------|------|")
        for c in cred:
            lines.append(f"| {c.get('indicator')} | {fmt(c.get('value'))} | {c.get('risk_level', '').upper()} | {c.get('issue')} {c.get('detail', '')} |")
        lines.append("")
        lines.append("> 以上为基于统计逻辑的自动预警，最终判断需结合现场实际情况核实。")
        lines.append("")
    else:
        lines.append("> 未触发可信度预警。仍建议交叉核对计划运行时间与停机记录的一致性。")
        lines.append("")

    # 四、改善优先级建议
    lines.append("## 四、改善优先级建议")
    lines.append("")
    if imp:
        lines.append(f"- **优先改善方向**：{imp.get('priority')}")
        lines.append(f"- **判定依据**：{imp.get('reason')}")
        lines.append(f"- **当前 OEE**：{fmt(imp.get('current_oee'))}% → **改善后预估**：{fmt(imp.get('expected_oee_after_improvement'))}%（+{fmt(imp.get('oee_improvement'))}pt）")
        lines.append("")
        lines.append("**推荐措施**：")
        for ms in imp.get("measures", []):
            lines.append(f"- {ms.get('action')}：{ms.get('method')}")
        lines.append("")

    # 五、ROI 估算（假设显式标注）
    lines.append("## 五、ROI 估算（含假设说明）")
    lines.append("")
    if roi:
        # 判断哪些是企业提供的、哪些是默认/待补充
        hov_provided = bool(meta.get("_provided", {}).get("hourly_output_value"))
        ah_provided = bool(meta.get("_provided", {}).get("annual_hours"))
        to_provided = bool(meta.get("_provided", {}).get("target_oee"))
        hov_mark = "" if hov_provided else "（默认值·待企业补充）"
        ah_mark = "" if ah_provided else "（默认 2400h·待企业补充）"
        to_mark = "" if to_provided else "（默认 85%·待企业补充）"
        lines.append(f"- 设备每小时产值：{fmt(roi.get('hourly_output_value'))} 元 {hov_mark}")
        lines.append(f"- 年运行工时假设：{fmt(roi.get('annual_production_hours'))} h {ah_mark}")
        lines.append(f"- 目标 OEE 假设：{fmt(roi.get('target_oee'))}% {to_mark}")
        lines.append(f"- 当前 OEE 与目标差距：{fmt(roi.get('oee_gap_to_target'))} pt")
        lines.append(f"- 预估年度可挽回产值：{fmt(roi.get('estimated_annual_recovery'))} 元")
        lines.append(f"- 预估改善投入：{fmt(roi.get('estimated_investment'))} 元")
        lines.append(f"- 投资回收期：{fmt(roi.get('payback_months'))} 个月；ROI：{fmt(roi.get('roi_percentage'))}%")
        lines.append("")
        lines.append("> ⚠️ ROI 为基于上述假设的简化估算，实际数值需以企业真实工时、产值与目标为准。")
        lines.append("")
    else:
        lines.append("> 无 ROI 数据。")
        lines.append("")

    # 六、改善措施库参考
    lines.append("## 六、改善措施库参考")
    lines.append("")
    lines.append("- 时间开动率短板：建立 MTBF/MTTR 追踪、导入快速换模(SMED)、周保全点检闭环")
    lines.append("- 性能开动率短板：物料预警机制消除空转、优化工艺参数解决降速、外内作业并行的换模")
    lines.append("- 合格品率短板：不良类型针对性改善、首件确认减少批量事故、安灯快速异常响应")
    lines.append("")
    lines.append("---")
    lines.append("> 本报告由 OEE 分析改善技能生成，计算基于用户投喂数据；所有企业专属参数缺失处已标注「待企业补充」。最终决策以现场为准。")
    lines.append("")

    return "\n".join(lines)


def generate_html(result, meta, enterprise):
    """装配 HTML 双版报告（含条形图与指标仪表，纯内联样式，可离线打开）"""
    device = html.escape(str(meta.get("device", "未命名设备")))
    period = html.escape(str(meta.get("period", "未指定周期")))
    company = html.escape(str(enterprise.get("company", "待企业补充")))

    m = result.get("metrics", {})
    sl = result.get("six_losses", {})
    cred = result.get("data_credibility", [])
    imp = result.get("improvement_priority", {})
    roi = result.get("roi_estimation", {})
    warnings = result.get("warnings", [])

    def bar(value, target, color):
        v = max(0.0, min(100.0, float(value or 0)))
        t = float(target or 0)
        mark = "✓" if v >= t else "✗"
        return f"""
        <div class="metric">
          <div class="metric-head"><span>{color[0]}</span><b>{v:.1f}%</b> <span class="tag {'ok' if v>=t else 'no'}">{mark}</span></div>
          <div class="track"><div class="fill" style="width:{v:.1f}%;background:{color[1]}"></div><div class="target-line" style="left:{t:.1f}%"></div></div>
          <div class="sub">目标 {t:.0f}%</div>
        </div>"""

    oee_html = bar(m.get("oee"), TARGETS["oee"], ("OEE", "#C8102E"))
    tr_html = bar(m.get("time_rate"), TARGETS["time_rate"], ("时间开动率", "#2E74B5"))
    pr_html = bar(m.get("performance_rate"), TARGETS["performance_rate"], ("性能开动率", "#2E9E5B"))
    qr_html = bar(m.get("quality_rate"), TARGETS["quality_rate"], ("合格品率", "#E8A33D"))

    # 六大损失条形图
    ratios = sl.get("ratios_percent", {})
    max_ratio = max([float(v) for v in ratios.values()] + [1.0])
    loss_bars = ""
    for name, val in sorted(ratios.items(), key=lambda x: float(x[1]), reverse=True):
        pct = float(val or 0)
        w = pct / max_ratio * 100
        loss_bars += f"""
        <div class="loss-row">
          <span class="loss-name">{html.escape(str(name))}</span>
          <div class="loss-track"><div class="loss-fill" style="width:{w:.1f}%"></div></div>
          <span class="loss-val">{pct:.1f}%</span>
        </div>"""

    # 可信度
    cred_html = ""
    if cred:
        for c in cred:
            cred_html += f'<div class="cred high">⚠️ <b>{html.escape(str(c.get("indicator")))}</b>：{html.escape(str(c.get("issue")))} {html.escape(str(c.get("detail","")))}</div>'
    else:
        cred_html = '<div class="cred ok">未触发可信度预警，建议仍交叉核对计划运行时间与停机记录。</div>'

    # 改善
    measures_html = ""
    if imp:
        for ms in imp.get("measures", []):
            measures_html += f"<li><b>{html.escape(str(ms.get('action')))}</b>：{html.escape(str(ms.get('method')))}</li>"

    # ROI
    roi_html = ""
    if roi:
        hov_provided = bool(meta.get("_provided", {}).get("hourly_output_value"))
        ah_provided = bool(meta.get("_provided", {}).get("annual_hours"))
        to_provided = bool(meta.get("_provided", {}).get("target_oee"))
        hov_mark = "" if hov_provided else "（默认值·待企业补充）"
        ah_mark = "" if ah_provided else "（默认2400h·待企业补充）"
        to_mark = "" if to_provided else "（默认85%·待企业补充）"
        roi_html = f"""
        <ul class="roi">
          <li>每小时产值：<b>{fmt(roi.get('hourly_output_value'))}</b> 元 {hov_mark}</li>
          <li>年运行工时：<b>{fmt(roi.get('annual_production_hours'))}</b> h {ah_mark}</li>
          <li>目标 OEE：<b>{fmt(roi.get('target_oee'))}</b>% {to_mark}</li>
          <li>年度可挽回产值：<b>{fmt(roi.get('estimated_annual_recovery'))}</b> 元</li>
          <li>预估改善投入：<b>{fmt(roi.get('estimated_investment'))}</b> 元</li>
          <li>投资回收期：<b>{fmt(roi.get('payback_months'))}</b> 个月；ROI：<b>{fmt(roi.get('roi_percentage'))}</b>%</li>
        </ul>
        <p class="warn">⚠️ ROI 为基于上述假设的简化估算，实际数值需以企业真实数据为准。</p>"""

    warn_html = ""
    if warnings:
        warn_html = '<div class="cred high">⚠️ ' + html.escape("；".join(warnings)) + '</div>'

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OEE 诊断报告 · {device}</title>
<style>
*{{box-sizing:border-box;font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;margin:0;padding:0;color:#1f2329}}
body{{background:#f5f6f8;padding:24px}}
.wrap{{max-width:880px;margin:0 auto;background:#fff;border-radius:12px;padding:28px 32px;box-shadow:0 2px 12px rgba(0,0,0,.06)}}
h1{{font-size:22px;color:#C8102E;border-bottom:3px solid #C8102E;padding-bottom:10px}}
.meta{{color:#666;font-size:13px;margin:12px 0 20px}}
.metrics-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:18px 0}}
.metric{{background:#fafbfc;border:1px solid #e8eaed;border-radius:8px;padding:12px 14px}}
.metric-head{{font-size:14px;display:flex;align-items:center;gap:6px}}
.metric-head b{{font-size:20px;margin-left:auto}}
.tag{{font-size:12px;padding:2px 8px;border-radius:10px;color:#fff}}
.tag.ok{{background:#2E9E5B}}.tag.no{{background:#C8102E}}
.track{{position:relative;height:10px;background:#eef0f3;border-radius:6px;margin:8px 0 4px}}
.fill{{height:100%;border-radius:6px}}
.target-line{{position:absolute;top:-3px;width:2px;height:16px;background:#333}}
.sub{{font-size:11px;color:#999}}
.section{{margin:22px 0}}
.section h2{{font-size:16px;color:#2E74B5;border-left:4px solid #2E74B5;padding-left:8px}}
.loss-row{{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:13px}}
.loss-name{{width:110px;color:#444}}
.loss-track{{flex:1;height:18px;background:#eef0f3;border-radius:4px;overflow:hidden}}
.loss-fill{{height:100%;background:linear-gradient(90deg,#C8102E,#E8A33D)}}
.loss-val{{width:48px;text-align:right;color:#666}}
.cred{{border-radius:8px;padding:10px 14px;margin:8px 0;font-size:13px}}
.cred.high{{background:#fdecea;color:#a8201a;border:1px solid #f5c6c0}}
.cred.ok{{background:#eafaf0;color:#1d7a44;border:1px solid #bfe9cd}}
ul.roi{{list-style:none;padding:0}}
ul.roi li{{padding:6px 0;border-bottom:1px dashed #eee;font-size:14px}}
.measures li{{margin:6px 0;font-size:14px}}
.warn{{color:#a8201a;font-size:12px}}
</style></head>
<body><div class="wrap">
<h1>OEE 诊断报告 · {device}</h1>
<div class="meta">统计周期：{period} ｜ 企业：{company}</div>
<div class="metrics-grid">
  {oee_html}{tr_html}{pr_html}{qr_html}
</div>
<div class="section"><h2>六大损失分布</h2>{loss_bars}</div>
{warn_html}
<div class="section"><h2>数据可信度检测</h2>{cred_html}</div>
<div class="section"><h2>改善优先级建议</h2>
<p>优先方向：<b>{html.escape(str(imp.get('priority','—')))}</b> ｜ 依据：{html.escape(str(imp.get('reason','—')))}</p>
<p>当前 OEE {fmt(imp.get('current_oee'))}% → 预估改善后 {fmt(imp.get('expected_oee_after_improvement'))}%（+{fmt(imp.get('oee_improvement'))}pt）</p>
<ul class="measures">{measures_html}</ul></div>
<div class="section"><h2>ROI 估算（含假设说明）</h2>{roi_html}</div>
<p style="color:#999;font-size:12px;margin-top:24px">本报告由 OEE 分析改善技能生成，计算基于用户投喂数据，企业专属参数缺失处已标注「待企业补充」。</p>
</div></body></html>"""
    return html_doc


def main():
    ap = argparse.ArgumentParser(description="OEE 诊断报告生成器（MD + HTML 双版）")
    ap.add_argument("-i", "--input", required=True, help="用户数据 JSON 路径")
    ap.add_argument("-o", "--output", required=True, help="输出前缀（生成 .md 与 .html）")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        payload = json.load(f)

    data = payload.get("data", {}) or {}
    meta = {
        "device": payload.get("device", "未命名设备"),
        "period": payload.get("period", "未指定周期"),
        "notes": payload.get("notes", ""),
        "_provided": payload.get("_provided", {}),
    }
    enterprise = payload.get("enterprise", {}) or {}

    # 调用计算引擎
    eng_args = build_args(data)
    result = C.calculate_oee(eng_args)

    md = generate_md(result, meta, enterprise)
    htm = generate_html(result, meta, enterprise)

    md_path = args.output + ".md"
    html_path = args.output + ".html"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(htm)

    print(f"✅ 报告已生成：\n  MD : {md_path}\n  HTML: {html_path}")
    print(f"   OEE={result.get('metrics',{}).get('oee')}%  优先改善：{result.get('improvement_priority',{}).get('priority')}")


if __name__ == "__main__":
    main()
