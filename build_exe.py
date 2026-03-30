"""简单的 EXE 打包脚本"""
import subprocess
import sys
import os

print("正在打包 TSK_Updater.exe...")

# 查找必要的资源目录
data_args = []
binary_args = []

# 1. UnityPy 资源目录
try:
    import UnityPy
    unitypy_path = os.path.dirname(UnityPy.__file__)
    resources_path = os.path.join(unitypy_path, "resources")
    
    if os.path.exists(resources_path):
        data_args.append(f"--add-data={resources_path};UnityPy/resources")
        print(f"✓ 找到 UnityPy 资源目录: {resources_path}")
    else:
        print("⚠ 警告: 未找到 UnityPy 资源目录")
        
except Exception as e:
    print(f"⚠ 警告: 无法定位 UnityPy 资源: {e}")

# 2. fmod_toolkit 的 fmod.dll
try:
    import fmod_toolkit
    fmod_toolkit_path = os.path.dirname(fmod_toolkit.__file__)
    fmod_dll_path = os.path.join(fmod_toolkit_path, "libfmod", "Windows", "x64", "fmod.dll")
    
    if os.path.exists(fmod_dll_path):
        # 保持原始目录结构
        binary_args.append(f"--add-binary={fmod_dll_path};fmod_toolkit/libfmod/Windows/x64")
        print(f"✓ 找到 fmod.dll: {fmod_dll_path}")
    else:
        print("⚠ 警告: 未找到 fmod.dll")
except Exception as e:
    print(f"⚠ 警告: 无法定位 fmod_toolkit: {e}")

# 3. imageio-ffmpeg 二进制文件
try:
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    if os.path.exists(ffmpeg_exe):
        binary_args.append(f"--add-binary={ffmpeg_exe};imageio_ffmpeg/binaries")
        print(f"✓ 找到 ffmpeg 可执行文件: {ffmpeg_exe}")
    else:
        print("⚠ 警告: 未找到 ffmpeg 可执行文件")
except Exception as e:
    print(f"⚠ 警告: 无法定位 imageio-ffmpeg: {e}")

cmd = [
    "pyinstaller",
    "--onefile",
    "--name=TSK_Updater",
    "--console",
    "--collect-data=UnityPy",
    "--collect-data=imageio_ffmpeg",
    "--collect-data=archspec",
    "--collect-binaries=imageio_ffmpeg",
    "--hidden-import=imageio_ffmpeg",
    "--hidden-import=fmod_toolkit",
    "--hidden-import=archspec",
    *data_args,
    *binary_args,
    "auto_updater.py"
]

print(f"\n执行打包命令...\n")

try:
    subprocess.check_call(cmd)
    print("\n✓ 打包完成！文件位于: dist/TSK_Updater.exe")
except Exception as e:
    print(f"\n✗ 打包失败: {e}")
    sys.exit(1)
