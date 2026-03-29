import pandas as pd
import random
import os

def generate_mock_claim_data(num_records=50, output_file='sample_claim_data.xlsx'):
    """
    生成模拟理赔账单数据
    :param num_records: 生成记录数量
    :param output_file: 输出文件名
    """
    try:
        # 生成保单号（从 CL9900100 开始）
        policy_ids = [f'CL9900{i:03d}' for i in range(100, 100 + num_records)]

        # 生成客户姓名
        customer_names = [f'客户{i}' for i in range(1, num_records + 1)]

        # 生成报案金额（随机 100-5000）
        claim_amounts = [random.randint(100, 5000) for _ in range(num_records)]

        # 免赔额（随机 300-800）
        deductibles = [random.randint(300, 800) for _ in range(num_records)]

        # 赔付比例（随机 0.7-0.9）
        payout_ratios = [round(random.uniform(0.7, 0.9), 2) for _ in range(num_records)]

        # 计算实际赔付金额
        payout_amounts = []
        for amount, ded, ratio in zip(claim_amounts, deductibles, payout_ratios):
            if amount <= ded:
                payout = 0.0
            else:
                payout = round((amount - ded) * ratio, 2)
            payout_amounts.append(payout)

        # 创建 DataFrame
        data = {
            '保单号': policy_ids,
            '客户姓名': customer_names,
            '报案金额': claim_amounts,
            '免赔额': deductibles,
            '赔付比例': payout_ratios,
            '实际赔付金额': payout_amounts
        }
        df = pd.DataFrame(data)

        # 保存为 Excel 文件
        df.to_excel(output_file, index=False)

        print(f"✅ 成功生成 {num_records} 条模拟理赔数据：{output_file}")
        print(f"📁 文件保存路径: {os.path.abspath(output_file)}")

        return df

    except ImportError:
        print("❌ 错误：需要安装 pandas 库。运行 'pip install pandas openpyxl'")
        return None
    except Exception as e:
        print(f"❌ 生成数据时出错: {e}")
        return None

if __name__ == "__main__":
    # 生成 50 条数据
    generate_mock_claim_data(50)

