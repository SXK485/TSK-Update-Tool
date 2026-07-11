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

### v1.10.0 (2026-07-11)
- ✨ **新增功能**: 角色完整更新模式（模式3）
- 🎯 **解决问题**: 角色从未实装变成已实装后资源不完整的问题
- 📋 **三种模式**: 启动时可选择正常更新、Spine修复、角色完整更新
- 🔧 **精确控制**: 模式3只更新指定角色，不影响其他角色
- 🚀 **黑名单绕过**: 模式3可以更新黑名单中的角色

### v1.8.8 (2026-07-10)
- 🐛 **修复严重 Bug**: 修正 bundle URL 模板字符串替换逻辑
- 🔧 **核心修复**: 添加 RUNTIME_PATH 替换，将 `{UnityEngine.AddressableAssets.Addressables.RuntimePath}` 替换为实际 CDN 地址
- ⚡ **问题解决**: 彻底解决"显示需要下载 N 个资源包，但实际提取 0 个文件"的问题
- 📊 **根本原因**: v1.8.6/v1.8.7 使用新 catalog.bundle 后，未处理模板字符串导致下载失败

### v1.8.7 (2026-07-10)
- 🐛 **修复 Bug**: 修正扫描阶段文件存在性检查逻辑，避免重复下载已存在文件
- ⚡ **优化性能**: 统一扫描和处理阶段的文件检查逻辑，减少不必要的网络请求
- 🔍 **问题修复**: 解决"显示需要下载 N 个资源包，但实际提取 0 个文件"的问题

### v1.8.6 (2026-07-10)
- 🔧 **修复严重 Bug**: 切换到新的 catalog.bundle 地址，解决 6 月 1 日后新资源无法下载的问题
- ✨ **Issue #2 解决**: 修复 6/5 后新角色（1062003, 1065004 等）无法下载的问题
- 🎯 **新资源索引**: 从旧的 catalog_0.0.0.json（220k资源）升级到 catalog.bundle（277k资源）
- 📊 **新增资源**: 7,769 个新资源（包含 6 月 1 日后的所有更新内容）

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
   - **模式1 - 正常更新模式**：只下载缺失文件，速度最快（推荐日常使用）
   - **模式2 - Spine动画修复模式**：强制覆盖所有Spine动画文件，解决动画显示错误（约50-100MB）
   - **模式3 - 角色完整更新模式**：指定角色ID，重新下载该角色所有资源，解决角色实装问题（每个角色约100-200MB）

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
- **模式3使用提示**：如果不知道角色ID，可以查看游戏目录下的 `Characters/ch_XXXXXX` 文件夹名（XXXXXX就是角色ID）

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


---

## 附加工具：Wiki 角色数据爬取工具

本项目还包含一个**独立的辅助工具**，用于从官方 Wiki 爬取角色信息，方便查询和参考。

### 功能特性

- 📊 从 [Twinkle Star Knights Wiki](https://twinklestarknights.wikiru.jp/) 自动爬取角色数据
- 🎯 提取角色ID、名称、属性、阵营、数值等完整信息
- 📁 生成三种格式输出：
  - **角色数据.csv** - Excel 可直接打开，方便查看和筛选
  - **角色数据.json** - 开发者友好格式
  - **角色检索.html** - 本地交互式网页，支持搜索、筛选、排序
- 🖼️ 自动下载角色头像到 `角色头像/` 文件夹
- 📅 按实装日期自动排序

### 使用方法

#### 方法一：使用 EXE（推荐小白用户）

1. 双击运行 `角色数据爬取工具.exe`
2. 等待程序自动抓取数据（约 1-2 分钟）
3. 完成后按回车键退出
4. 查看生成的文件：
   - `角色数据.csv` - 用 Excel 打开查看
   - `角色检索.html` - 用浏览器打开，可搜索和筛选

#### 方法二：Python 脚本

```bash
# 使用 uv（需要安装 beautifulsoup4）
uv pip install beautifulsoup4 requests
uv run spider.py

# 或使用 pip
pip install beautifulsoup4 requests
python spider.py
```

### 打包爬虫工具为 EXE

```bash
uv pip install pyinstaller
uv run python build_spider.py
```

生成的文件在 `dist/角色数据爬取工具.exe`

### 输出说明

#### 角色数据.csv
包含以下字段（中文表头，Excel 友好）：
- 角色ID、星级、角色名称、名字(日文读音)
- 属性、阵营、所属团队
- 类型、攻击类型
- 生命值(HP)、攻击力(ATK)
- EX、EX上升、最小CT、最大CT、暴击率(%)
- 实装日期、获取方式

#### 角色检索.html
功能特性：
- 🔍 实时搜索（支持角色ID、中文名、日文读音）
- 🏷️ 多维度筛选（星级、属性、类型）
- 📋 点击角色ID快速复制到剪贴板
- 💾 完全本地运行，无需联网
- 📱 响应式设计，手机也能用

### 注意事项

- ⚠️ 这是**独立的辅助工具**，与主更新程序无关
- 📌 爬取的是 Wiki 数据，仅供参考，实际游戏数据以游戏内为准
- 🖼️ 图片下载可能失败（Wiki 使用懒加载技术），不影响文本数据
- 🌐 需要能访问日本 Wiki 网站

### 常见问题

**Q: 图片为什么下载失败？**  
A: Wiki 使用了懒加载技术，初始加载时图片是占位符。不影响角色数据本身的完整性。

**Q: 角色ID前为什么多了个"1"？**  
A: 这是脚本自动添加的，与游戏内资源ID保持一致（例如：角色001在游戏内ID为1001001）。

**Q: 如何找到特定角色？**  
A: 打开 `角色检索.html`，使用搜索框输入角色名或ID即可快速定位。
