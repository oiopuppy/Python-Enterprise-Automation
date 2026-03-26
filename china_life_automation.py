import os
import datetime

def check_reports():
    # 1. 打印启动信息
    print("\n" + "="*50)
    print(f"--- 正在启动中国人寿数据对账自动化工具 ---")
    print(f"当前时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50 + "\n")

    # 2. 获取当前文件夹下的所有文件
    try:
        files = os.listdir('.')
        print(f"[扫描结果] 当前目录共有 {len(files)} 个项目：")
        
        for f in files:
            if f.endswith('.py'):
                print(f"  - [脚本文件]: {f}")
            else:
                print(f"  - [其他资产]: {f}")
                
        print("\n[战略提示]: Python 环境已就绪。下一步可接入 Pandas 进行 Excel 自动审计。")
    except Exception as e:
        print(f"扫描出错: {e}")

if __name__ == "__main__":
    check_reports()
