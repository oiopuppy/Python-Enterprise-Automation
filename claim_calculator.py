import sys

def calculate_insurance_payout(bill_amount, deductible=500, ratio=0.8):
    """
    核心业务逻辑：理赔金计算
    公式：应赔额 = (账单金额 - 免赔额) * 赔付比例
    知识点：逻辑边界处理（防止赔付额为负数）
    """
    # 1. 业务逻辑判断：如果账单还没免赔额高，直接赔付0
    if bill_amount <= deductible:
        return 0.0
    
    # 2. 计算赔付
    payout = (bill_amount - deductible) * ratio
    
    # 3. 结果返回（保留两位小数，符合财务规范）
    return round(payout, 2)

def main():
    print("--- 中国人寿理赔自动化核算原型 (v1.0) ---")
    
    try:
        # 模拟用户输入数据
        # 知识点：输入校验。如果用户输入非数字，程序不崩溃（健壮性）
        raw_input = input("请输入报案账单金额: ")
        bill = float(raw_input)
        # 调用核心算法
        result = calculate_insurance_payout(bill)
        
        print(f"核算结果：")
        print(f"- 原始账单: {bill} 元")
        print(f"- 免赔额(固定): 500 元")
        print(f"- 最终应赔付金额: {result} 元")
        
    except ValueError:
        print("错误：请输入有效的数字金额！(数据类型非法)")
    except Exception as e:
        print(f"系统运行异常: {e}")

if __name__ == "__main__":
    # 知识点：冯·诺依曼架构中的“程序执行入口”
    main()
