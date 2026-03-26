import pandas as pd

# 1. 模拟人寿的保单数据
data = {
    '保单号': ['CN001', 'CN002', 'CN003', 'CN004', 'CN005'],
    '投保人': ['张三', '李四', '王五', '赵六', '孙七'],
    '应收金额': [1000.50, 2500.00, 300.20, 5000.00, 1200.00],
    '实收金额': [1000.50, 2400.00, 300.20, 5000.00, 1100.00]  # 故意制造两个差错
}

# 2. 转换成 Pandas 的数据结构 (DataFrame)
df = pd.DataFrame(data)

# 3. 保存为 Excel 文件
file_name = '人寿对账单_20260326.xlsx'
df.to_excel(file_name, index=False)

print(f"✅ 成功生成模拟对账单：{file_name}")
print("💡 提示：可以看到李四和孙七的金额是不对的")
