"""
Wiki爬虫工具打包脚本
将 spider.py 打包成独立的 exe 可执行文件
"""
import PyInstaller.__main__
import os

def build_spider():
    """打包 spider.py 为独立的 exe 文件"""
    
    script_name = "spider.py"
    exe_name = "角色数据爬取工具"
    
    # 检查源文件是否存在
    if not os.path.exists(script_name):
        print(f"错误: 找不到 {script_name}")
        return
    
    print(f"开始打包 {script_name}...")
    print(f"输出文件名: {exe_name}.exe")
    print("-" * 60)
    
    # PyInstaller 参数
    args = [
        script_name,                          # 源文件
        '--onefile',                          # 打包成单个文件
        '--console',                          # 显示控制台窗口
        f'--name={exe_name}',                 # 输出文件名（中文）
        '--clean',                            # 清理临时文件
        '--noconfirm',                        # 不询问确认
        '--icon=NONE',                        # 不使用图标
    ]
    
    try:
        PyInstaller.__main__.run(args)
        print("-" * 60)
        print(f"✓ 打包完成！")
        print(f"输出路径: dist/{exe_name}.exe")
        print()
        print("使用说明:")
        print(f"  1. 运行 dist/{exe_name}.exe")
        print("  2. 等待程序抓取数据")
        print("  3. 生成的文件在 exe 所在目录:")
        print("     - 角色数据.csv")
        print("     - 角色数据.json")
        print("     - 角色检索.html")
        print("     - 角色头像/ 文件夹")
    except Exception as e:
        print(f"打包失败: {e}")

if __name__ == "__main__":
    build_spider()
