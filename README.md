# TSK 资源更新工具

一个简单的 Twinkle Star Knights X 离线播放器资源更新脚本。

> **声明**：仅提供更新脚本，不提供播放器和游戏资源。

## 功能

- 自动从官方服务器下载最新资源
- 智能解析和转换 Unity 资源文件
- 音频自动转换为 OGG 格式（Vorbis 编码）
- 增量更新（只下载需要的文件）
- 多线程下载和处理
- 自动清理旧文件

## 更新日志

### v1.8.5 (2026-06-20)
- 📊 增强日志输出，记录每个文件的提取详情
- 🎯 Master.chapter.json 智能内容对比，避免无变化时重复更新
- 🔍 添加详细的文件处理日志，便于排查问题
- 📝 日志记录文件类型、跳过原因等关键信息

### v1.8.4 (2026-06-20)
- 🐛 修复 Spine 动画和 CG 图片分辨率错误问题
- ✨ 新增"修复模式"可选功能，用户可选择是否强制覆盖
- ⚡ 修复模式会强制重新下载并覆盖以下目录的所有 PNG：
  - Characters/ (角色 Spine 动画)
  - Adventure/Spine/ (剧情 Spine 动画)
  - GachaCharaAnim/ (抽卡动画)
  - Stills/ (CG 图片)
- 🎯 解决 Sprite 和 Texture2D 分辨率不一致问题（仅提取 Texture2D）
- 💡 正常更新模式保持快速增量更新，只下载缺失文件

### v1.8.3 (2026-03-30)
- ✨ 新增音频自动转换功能（WAV → OGG Vorbis）
- ⚡ 优化多线程处理，动态分配转码线程
- 🔧 改进音频提取逻辑，使用 ffmpeg 进行格式转换
- 📦 EXE 版本包含所有必要依赖（fmod.dll, ffmpeg）

### v1.6.3
- 初始版本发布

## 播放器资源文件结构

更新后的资源将按照以下目录结构组织：

```
Twinkle Star Knights X_Data/StreamingAssets/Twinkle Star Knights X/
├── Adventure/                    # 剧情相关
│   ├── BackGrounds/             # 背景图片
│   ├── CharaScenario/           # 角色剧情脚本
│   ├── MainScenario/            # 主线剧情脚本
│   ├── StoryEventScenario/      # 活动剧情脚本
│   ├── SubjugationEventScenario/# 讨伐活动剧情
│   ├── Effects/                 # 特效资源
│   ├── Spine/                   # Spine 动画
│   ├── Textures/                # 纹理资源
│   └── Master.chapter.json      # 章节索引
├── Characters/                   # 角色 Spine 动画
│   └── ch_[ID]/                 # 角色动画文件
├── Cutin/                       # 立绘资源
│   └── [ID]/                    # 角色立绘文件
├── GachaCharaAnim/              # 抽卡动画
│   ├── GachaCharaAnim/          # 角色转换动画
│   ├── gacha_bg_effect/         # 背景特效
│   ├── gacha_intro/             # 抽卡开场
│   ├── new_chara_staging/       # 新角色演出
│   └── transform_eff/           # 变身特效
├── Sound/                       # 音频资源
│   ├── Bgm/                     # 背景音乐
│   ├── BgSe/                    # 背景音效
│   ├── BgVoice/                 # 背景语音
│   ├── Se/                      # 音效
│   └── Voice/                   # 角色语音
├── Sprites/                     # 精灵图片
│   ├── Bg/                      # 背景图
│   ├── Chara/                   # 角色头像
│   ├── Jukebox/                 # 音乐盒图标
│   ├── OutGame/                 # 游戏外界面
│   └── PictureBook/             # 图鉴
└── Stills/                      # CG 图片
    └── st_[ID]/                 # CG 文件
```

## 使用方法

### 方法一：使用 EXE（Windows）

1. 下载 `TSK_Updater.exe`
2. 放在播放器根目录（包含 `Twinkle Star Knights X_Data` 文件夹）
3. 双击运行
4. 根据提示选择模式：
   - **修复模式 (Y)**：强制覆盖所有动画和 CG 图片，解决分辨率错误（耗时较长）
   - **正常模式 (N)**：只下载缺失文件，速度更快（推荐日常使用）

### 方法二：Python 脚本

#### 使用 uv（推荐）

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
uv run auto_updater.py
```

#### 使用 pip

```bash
pip install -r requirements.txt
python auto_updater.py
```

## 打包 EXE

```bash
uv pip install pyinstaller
uv run python build_exe.py
```

生成的 EXE 在 `dist/TSK_Updater.exe`

## 说明

- 脚本会自动下载缺失的资源文件
- 支持断点续传，中断后重新运行即可
- 日志保存在 `update_log.txt`
- 默认输出目录：`Twinkle Star Knights X_Data/StreamingAssets/Twinkle Star Knights X`

## 依赖

### EXE 版本
无需安装任何依赖，开箱即用。

### Python 脚本版本
- Python 3.12+
- addressablestools
- requests
- UnityPy
- fsspec
- imageio-ffmpeg（音频转换）
- fmod_toolkit（音频解码）

完整依赖列表见 `requirements.txt`
