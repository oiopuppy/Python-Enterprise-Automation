import pandas as pd
import os
import datetime
# 注意：这行会调用你写的算法文件 claim_calculator.py
from claim_calculator import calculate_insurance_payout 

def check_env():
    """
    第一阶段：健康检查 (你的原创代码升级版)
    负责扫描环境，确保数据文件已就绪
    """
    print("\n" + "="*60)
    print(f"--- 中国人寿理赔数据自动化审计工具 (RUDN-Intern-Edition) ---")
    print(f"执行时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")
    
    # 扫描目录项目
    files = os.listdir('.')
    print(f"[扫描结果] 当前目录共有 {len(files)} 个项目：")
    for f in files:
        if f.endswith('.py'):
            print(f"  - [脚本文件]: {f}")
        elif f.endswith('.xlsx'):
            print(f"  - [数据报表]: {f}")

    # 核心检查：是否有待处理的数据源
    input_file = 'sample_claim_data.xlsx'
    if input_file in files:
        print(f"\n✅ 检测到待处理报表：{input_file}")
        return True
    else:
        print(f"\n❌ 错误：未检测到 {input_file}")
        print("💡 战略提示：请先运行 'python create_mock_data.py' 生成模拟数据。")
        return False

def run_reconciliation():
    """
    第二阶段：自动化审计核心
    读取Excel -> 调用内核算法 -> 自动对账 -> 导出报告
    """
    input_file = 'sample_claim_data.xlsx'
    output_file = 'final_settlement_report.xlsx'

    print("\n🚀 正在载入 Pandas 引擎进行大规模数据对账...")
    
    # 1. 读取模拟数据工厂生成的 Excel
    df = pd.read_excel(input_file)

    # 2. 批量调用算法进行二次核算
    # 这体现了“计算与业务分离”的专业思想
    df['系统核算金额'] = df['报案金额'].apply(
        lambda x: calculate_insurance_payout(x, deductible=500, ratio=0.8)
    )

    # 3. 自动对账逻辑 (Reconciliation)
    # 比较“原表结果”和“程序核算结果”，发现差异立即标出
    df['审计状态'] = df.apply(
        lambda row: "✅ 一致" if row['系统核算金额'] == row['实际赔付金额'] else "❌ 异常", 
        axis=1
    )

    # 4. 导出最终审计报告
    df.to_excel(output_file, index=False)
    
    print("-" * 40)
    print(f"✨ 审计工作流执行成功！")
    print(f"📊 已处理记录总数: {len(df)} 条")
    print(f"📁 报告保存路径: {os.path.abspath(output_file)}")
    print("-" * 40)

if __name__ == "__main__":
    # 按照：检查环境 -> 执行审计 的顺序进行
    if check_env():
        try:
            run_reconciliation()
        except Exception as e:
            print(f"❌ 运行过程中出现致命错误: {e}")
