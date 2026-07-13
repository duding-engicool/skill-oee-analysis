#!/usr/bin/env python3
"""
OEE计算与诊断脚本
输入设备运行数据，计算OEE三大指标，诊断六大损失，检测数据可信度
"""

import argparse
import json
import sys

def calculate_oee(args):
    """计算OEE指标"""
    results = {
        "status": "success",
        "data_completeness": "complete",
        "metrics": {},
        "six_losses": {},
        "data_credibility": [],
        "improvement_priority": {},
        "roi_estimation": {},
        "warnings": []
    }
    
    # 检查数据完整性
    required_fields = ['planned_time', 'actual_time', 'total_output', 'qualified_output']
    optional_fields = ['downtime_failure', 'downtime_changover', 'standard_cycle_time', 
                       'startup_time', 'quality_loss_time', 'idle_time', 'speed_loss_time']
    
    missing_required = []
    for field in required_fields:
        if getattr(args, field, None) is None:
            missing_required.append(field)
    
    if missing_required:
        results["status"] = "incomplete"
        results["data_completeness"] = "incomplete"
        results["warnings"].append(f"缺少必要数据: {', '.join(missing_required)}，OEE仅供参考")
        # 用0填充缺失值
        for field in required_fields:
            if not hasattr(args, field) or getattr(args, field, None) is None:
                setattr(args, field, 0)
    
    # 检查可选数据
    for field in optional_fields:
        if not hasattr(args, field) or getattr(args, field, None) is None:
            setattr(args, field, 0)
    
    # ========== OEE三大指标计算 ==========
    planned_time = args.planned_time  # 计划运行时间
    actual_time = args.actual_time    # 实际运行时间
    total_output = args.total_output  # 总产量
    qualified_output = args.qualified_output  # 合格品数
    
    # 时间开动率 = 实际运行时间 / 计划运行时间 × 100%
    time_rate = (actual_time / planned_time * 100) if planned_time > 0 else 0
    
    # 性能开动率 = (实际产量 × 标准节拍) / 实际运行时间 × 100%
    standard_cycle = args.standard_cycle_time if args.standard_cycle_time > 0 else 60  # 默认60秒
    ideal_production = (actual_time * 3600 / standard_cycle) if standard_cycle > 0 else 0  # 理想产量
    performance_rate = min((total_output / ideal_production * 100), 100) if ideal_production > 0 else 0  # 限制上限100%
    performance_rate_raw = (total_output / ideal_production * 100) if ideal_production > 0 else 0  # 原始值用于检测
    
    # 合格品率 = 合格品数量 / 总产量 × 100%
    quality_rate = (qualified_output / total_output * 100) if total_output > 0 else 0
    
    # OEE = 时间开动率 × 性能开动率 × 合格品率
    oee = time_rate * performance_rate * quality_rate / 10000
    
    results["metrics"] = {
        "time_rate": round(time_rate, 2),
        "performance_rate": round(performance_rate, 2),
        "quality_rate": round(quality_rate, 2),
        "oee": round(oee, 2)
    }
    
    # ========== 六大损失计算 ==========
    downtime_failure = args.downtime_failure  # 设备故障损失
    downtime_changover = args.downtime_changover  # 换模调整损失
    startup_time = args.startup_time  # 启动损失
    quality_loss_time = args.quality_loss_time  # 质量损失
    idle_time = args.idle_time  # 空转暂停损失
    speed_loss_time = args.speed_loss_time  # 减速损失
    
    total_downtime = downtime_failure + downtime_changover + startup_time + quality_loss_time + idle_time + speed_loss_time
    unplanned_downtime = planned_time - actual_time  # 非计划停机时间
    
    # 如果六大损失时间总和与实际停机时间不符，按实际停机分配
    if total_downtime > 0:
        loss_distribution = {
            "设备故障损失": round(downtime_failure, 2),
            "换模调整损失": round(downtime_changover, 2),
            "空转暂停损失": round(idle_time, 2),
            "减速损失": round(speed_loss_time, 2),
            "启动损失": round(startup_time, 2),
            "质量损失": round(quality_loss_time, 2)
        }
    else:
        # 无法识别六大损失
        loss_distribution = {
            "设备故障损失": 0,
            "换模调整损失": 0,
            "空转暂停损失": 0,
            "减速损失": 0,
            "启动损失": 0,
            "质量损失": 0
        }
    
    # 计算各损失占比
    if planned_time > 0:
        loss_ratios = {k: round(v / planned_time * 100, 2) for k, v in loss_distribution.items()}
    else:
        loss_ratios = {k: 0 for k in loss_distribution.keys()}
    
    # 按损失大小排序
    sorted_losses = sorted(loss_ratios.items(), key=lambda x: x[1], reverse=True)
    
    results["six_losses"] = {
        "absolute_values": loss_distribution,
        "ratios_percent": loss_ratios,
        "ranking": [{"rank": i+1, "loss_type": name, "ratio": ratio} for i, (name, ratio) in enumerate(sorted_losses)]
    }
    
    # ========== 数据可信度检测 ==========
    credibility_issues = []
    
    # 规则1: 时间开动率虚高检测
    if time_rate > 95 and (downtime_failure + downtime_changover + idle_time) > 0.5:
        credibility_issues.append({
            "indicator": "时间开动率",
            "value": time_rate,
            "issue": "⚠️ 计划运行时间可能被缩水",
            "detail": f"时间开动率{time_rate}%属于优秀水平，但现场存在{downtime_failure+downtime_changover+idle_time}小时的停机记录，请核实计划运行时间是否被调整",
            "risk_level": "high"
        })
    
    # 规则2: 性能开动率虚高检测
    if performance_rate_raw > 95 and total_output < ideal_production * 0.9:
        credibility_issues.append({
            "indicator": "性能开动率",
            "value": performance_rate,
            "issue": "⚠️ 标准节拍可能被放宽",
            "detail": f"性能开动率{performance_rate}%显示效率极高，但实际产量仅为理想产量的{total_output/ideal_production*100:.1f}%，请核实标准节拍是否被调高",
            "risk_level": "high"
        })
    
    # 规则3: 合格品率虚高检测
    if quality_rate > 99 and quality_loss_time > 0:
        credibility_issues.append({
            "indicator": "合格品率",
            "value": quality_rate,
            "issue": "⚠️ 统计口径可能不含返工品",
            "detail": f"合格品率{quality_rate}%接近完美，但存在{quality_loss_time}小时的质量损失时间，请核实不良品统计范围是否包含返工品",
            "risk_level": "medium"
        })
    
    # 规则4: OEE与损失不匹配检测
    if oee < 60 and time_rate > 85:
        credibility_issues.append({
            "indicator": "综合指标",
            "value": f"OEE={oee}%",
            "issue": "⚠️ OEE偏低但时间开动率正常",
            "detail": "可能存在性能损失或质量损失未被准确记录，建议检查六大损失的统计完整性",
            "risk_level": "medium"
        })
    
    results["data_credibility"] = credibility_issues
    
    # ========== 改善优先级建议 ==========
    # 计算各维度损失贡献（确保非负）
    time_loss = max(100 - time_rate, 0)
    performance_loss = max(100 - performance_rate, 0)
    quality_loss = max(100 - quality_rate, 0)
    
    improvement_suggestions = []
    
    # oee已经是百分比形式(84.14)
    current_oee_percent = round(oee, 2)
    
    if time_loss > performance_loss + quality_loss:
        priority = "时间开动率"
        reason = f"时间损失({time_loss}%)超过性能损失({performance_loss}%)与质量损失({quality_loss}%)之和"
        measures = [
            {"action": "设备故障减少", "method": "建立MTBF/MTTR追踪体系，设备故障平均时间控制在2小时以内"},
            {"action": "换模效率提升", "method": "导入快速换模(SMED)法，将换型时间缩短50%"},
            {"action": "设备保养闭环", "method": "每周定保全点检，小问题当天清不过夜"}
        ]
    elif performance_loss > quality_loss:
        priority = "性能开动率"
        reason = f"性能损失({performance_loss}%)是最大短板"
        measures = [
            {"action": "消除空转暂停", "method": "分析待料、断料、堵料原因，建立物料预警机制"},
            {"action": "解决减速损失", "method": "排查设备老化降速原因，优化工艺参数"},
            {"action": "换模效率翻倍", "method": "用快速换模法分解换型步骤，外部作业与内部作业并行"}
        ]
    else:
        priority = "合格品率"
        reason = f"质量损失({quality_loss}%)占比最高"
        measures = [
            {"action": "降低不良率", "method": "分析不良类型分布，针对性改善工艺控制点"},
            {"action": "减少返工品", "method": "建立首件确认机制，减少批量质量事故"},
            {"action": "异常响应加速", "method": "安灯一响，10分钟内到场，30分钟内给出处置方案"}
        ]
    
    # 预估改善效果（确保不超过合理上限）
    # 基准：各指标与100%的差距
    
    if priority == "时间开动率":
        improved_time_rate = min(time_rate + 5, 92)
        # 只提升时间开动率
        improved_oee_percent = improved_time_rate * performance_rate * quality_rate / 100
        improved_oee_percent = min(improved_oee_percent, 85)
    elif priority == "性能开动率":
        improved_performance_rate = min(performance_rate + 5, 95)
        improved_oee_percent = time_rate * improved_performance_rate * quality_rate / 100
        improved_oee_percent = min(improved_oee_percent, 85)
    else:
        improved_quality_rate = min(quality_rate + 1, 99)
        improved_oee_percent = time_rate * performance_rate * improved_quality_rate / 100
        improved_oee_percent = min(improved_oee_percent, 85)
    
    # 转换为小数形式存储
    improved_oee = improved_oee_percent / 100
    
    results["improvement_priority"] = {
        "priority": priority,
        "reason": reason,
        "measures": measures,
        "current_oee": round(current_oee_percent, 2),
        "expected_oee_after_improvement": round(improved_oee_percent, 2),
        "oee_improvement": round(improved_oee_percent - current_oee_percent, 2)
    }
    
    # ========== ROI估算 ==========
    # 假设数据: 设备每小时产值5000元，目标OEE 85%
    hourly_output_value = args.hourly_output_value if hasattr(args, 'hourly_output_value') and args.hourly_output_value > 0 else 5000
    
    # 估算实施改善的成本和收益
    # 假设改善措施实施周期3个月，设备年运行2400小时
    annual_hours = 2400
    target_oee = 85  # 行业标杆OEE
    oee_gap = max(target_oee - oee, 0)  # 与目标OEE 85%的差距（非负）
    
    # 如果当前OEE已达目标，减少的损失时间减少
    if oee_gap <= 0:
        annual_recovery_value = 0
        roi_message = "当前OEE已达标，维持现状即可"
    else:
        # OEE每提升1%对应的产值提升
        value_per_percent = annual_hours * hourly_output_value / 100
        annual_recovery_value = value_per_percent * oee_gap
    
    # 改善措施成本估算(简化模型)
    improvement_cost = {
        "备件储备": 5000,
        "换模工装改进": 8000,
        "操作培训": 3000,
        "数据采集系统": 15000
    }
    total_investment = sum(improvement_cost.values())
    
    if annual_recovery_value > 0:
        payback_months = round(total_investment / (annual_recovery_value / 12), 1)
        roi_percentage = round((annual_recovery_value - total_investment) / total_investment * 100, 1)
    else:
        payback_months = "已达标"
        roi_percentage = 0
    
    results["roi_estimation"] = {
        "annual_production_hours": annual_hours,
        "hourly_output_value": hourly_output_value,
        "target_oee": target_oee,
        "current_oee": round(oee, 2),
        "oee_gap_to_target": round(oee_gap, 2),
        "estimated_annual_recovery": round(annual_recovery_value, 2),
        "estimated_investment": total_investment,
        "investment_breakdown": improvement_cost,
        "payback_months": payback_months,
        "roi_percentage": roi_percentage,
        "message": roi_message if oee_gap <= 0 else None
    }
    
    return results

def main():
    parser = argparse.ArgumentParser(description='OEE计算与诊断工具')
    
    # 必需参数
    parser.add_argument('--planned_time', type=float, required=True, help='计划运行时间(小时)')
    parser.add_argument('--actual_time', type=float, required=True, help='实际运行时间(小时)')
    parser.add_argument('--total_output', type=int, required=True, help='总产量(件)')
    parser.add_argument('--qualified_output', type=int, required=True, help='合格品数量(件)')
    
    # 可选参数 - 六大损失
    parser.add_argument('--downtime_failure', type=float, default=0, help='设备故障停机时间(小时)')
    parser.add_argument('--downtime_changover', type=float, default=0, help='换模调整时间(小时)')
    parser.add_argument('--idle_time', type=float, default=0, help='空转暂停时间(小时)')
    parser.add_argument('--speed_loss_time', type=float, default=0, help='减速损失时间(小时)')
    parser.add_argument('--startup_time', type=float, default=0, help='启动损失时间(小时)')
    parser.add_argument('--quality_loss_time', type=float, default=0, help='质量损失时间(小时)')
    
    # 其他参数
    parser.add_argument('--standard_cycle_time', type=float, default=60, help='标准节拍(秒/件)')
    parser.add_argument('--hourly_output_value', type=float, default=5000, help='设备每小时产值(元)')
    
    args = parser.parse_args()
    
    # 执行计算
    results = calculate_oee(args)
    
    # 输出JSON结果
    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
