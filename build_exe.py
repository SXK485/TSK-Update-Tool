"""简单的 EXE 打包脚本"""
import subprocess
import sys

print("正在打包 TSK_Updater.exe...")

try:
    subprocess.check_call([
        "pyinstaller",
        "--onefile",
        "--name=TSK_Updater",
        "--console",
        "auto_updater.py"
    ])
    print("\n✓ 打包完成！文件位于: dist/TSK_Updater.exe")
except Exception as e:
    print(f"\n✗ 打包失败: {e}")
    sys.exit(1)
