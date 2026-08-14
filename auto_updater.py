"""
Twinkle Star Knights X 离线版资源自动更新工具
版本: v1.11.0 (Stable)
说明: 自动化同步、精简并转换游戏资源至离线播放器格式。
优化: 引入温和的动态多线程调度算法,完美适配低配与高配电脑，防止 I/O 阻塞卡死。
修复: Spine 动画 PNG 仅从 Texture2D 提取，自动强制覆盖确保正确分辨率。
改进: 增强日志输出，Master.chapter.json 智能内容对比避免重复更新。
重要: 切换到新的 catalog.bundle 地址，解决 6 月 1 日后新角色缺失问题 (Issue #2)。
修复: 修正 bundle URL 模板字符串替换逻辑，解决下载 0 文件的严重 Bug (v1.8.8)。
增强: 修复模式现在覆盖 Spine 所有文件（PNG + atlas.txt + skel.bytes），彻底解决动画错乱问题 (v1.8.9)。
新增: 过滤不完整角色资源（无剧情的角色），避免其在播放器角色列表中显示 (v1.9.0)。
修复: 修正 Adventure 目录资源过滤逻辑，解决背景图片、特效等资源无法下载的严重 Bug (v1.9.1)。
优化: 过滤无用的 .chapter.json 文件（仅保留 Master.chapter.json），减少不必要的下载 (v1.9.2)。
新增: 角色完整更新模式（模式3），可指定角色重新下载其全部资源 (v1.10.0)。
优化: 音频转码改用真实 m4a 格式、对象级失败隔离、日志全流程记录、CDN 支持环境变量 (v1.11.0)。
"""

import os
import requests
import UnityPy
import logging
import time
import json
import subprocess
from AddressablesTools import parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ================= 依赖检查与初始化 =================
try:
    import imageio_ffmpeg
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    print("="*65)
    print("[!!!] 致命错误: 缺少核心音频转码引擎！")
    print(" -> 离线播放器严格要求原生的 Ogg Vorbis 编码，必须转码。")
    print(" -> 请先在终端中运行以下命令安装:")
    print("    uv pip install imageio-ffmpeg")
    print(" -> 安装完成后再次运行本脚本即可！")
    print("="*65)
    input("\n按回车键退出...")
    exit(1)

# ================= 工具配置区 =================
# CDN 地址支持环境变量覆盖（服务器换地址时无需改代码重打包）：
#   set TSK_CATALOG_BUNDLE_URL=...   set TSK_RUNTIME_PATH=...
CATALOG_BUNDLE_URL = os.environ.get(
    "TSK_CATALOG_BUNDLE_URL",
    "https://d3mya90gbacu0m.cloudfront.net/prod/StreamingAssets/aa/catalog.bundle",
)
RUNTIME_PATH = os.environ.get(
    "TSK_RUNTIME_PATH",
    "https://d3mya90gbacu0m.cloudfront.net/prod/StreamingAssets/aa",
)
OUTPUT_DIR = "Twinkle Star Knights X_Data/StreamingAssets/Twinkle Star Knights X"
INCOMPLETE_CHARS_CACHE = "incomplete_character_ids.txt"
# ============================================

logger = logging.getLogger("TSK_Updater")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("update_log.txt", mode="a", encoding="utf-8")
file_handler.setFormatter(logging.Formatter('%(asctime)s[%(levelname)s] %(message)s'))
logger.addHandler(file_handler)


def log_progress(msg):
    """同时输出到控制台和 update_log.txt，用于记录执行流程里程碑"""
    print(msg)
    logger.info(msg)

class AppState:
    """全局共享状态（多线程共享的字段用锁保护）"""

    def __init__(self):
        self.progress_lock = Lock()
        self.queue_lock = Lock()
        self.global_progress = 0
        self.total_bundles_to_dl = 0
        self.audio_convert_queue = []
        self.incomplete_character_ids = set()  # 动态检测的不完整角色 ID 集合
        self.force_update_characters = []  # 需要强制完整更新的角色ID列表


state = AppState()

def detect_incomplete_characters():
    """
    检测不完整角色（有 Spine/头像，但没有剧情文件的角色）
    只检测玩家角色 ID 范围（1000000 ~ 1999999），其他范围（敌人、NPC、素材等）不管
    优先从缓存文件读取，如果缓存不存在则扫描游戏目录
    """
    
    # 尝试从缓存文件读取
    if os.path.exists(INCOMPLETE_CHARS_CACHE):
        try:
            with open(INCOMPLETE_CHARS_CACHE, 'r', encoding='utf-8') as f:
                state.incomplete_character_ids = set()
                for line in f:
                    line = line.strip()
                    if line and line.isdigit():
                        state.incomplete_character_ids.add(int(line))
            if state.incomplete_character_ids:
                print(f"[信息] 从缓存加载了 {len(state.incomplete_character_ids)} 个不完整角色 ID")
                logger.info(f"从缓存加载了 {len(state.incomplete_character_ids)} 个不完整角色 ID: {sorted(state.incomplete_character_ids)}")
                return
        except Exception as e:
            print(f"[警告] 读取缓存文件失败: {e}，将重新扫描")
            logger.warning(f"读取缓存文件失败: {e}")
    
    # 缓存不存在或读取失败，执行扫描
    print("[信息] 正在扫描游戏目录，检测不完整的玩家角色...")
    logger.info("开始扫描游戏目录检测不完整角色")
    
    characters_dir = os.path.join(OUTPUT_DIR, "Characters")
    adventure_char_dir = os.path.join(OUTPUT_DIR, "Adventure", "CharaScenario")
    
    if not os.path.exists(characters_dir):
        print("[信息] Characters 目录不存在，跳过检测")
        logger.info("Characters 目录不存在，跳过不完整角色检测")
        return
    
    # 获取所有有 Spine 动画的玩家角色 ID（只检测 1000000 ~ 1999999 范围）
    character_ids_with_spine = set()
    try:
        for item in os.listdir(characters_dir):
            if item.startswith("ch_") and os.path.isdir(os.path.join(characters_dir, item)):
                try:
                    char_id = int(item[3:])
                    # 只检测玩家角色 ID 范围（1000000 ~ 1999999）
                    if 1000000 <= char_id <= 1999999:
                        character_ids_with_spine.add(char_id)
                except ValueError:
                    continue
    except Exception as e:
        print(f"[警告] 扫描 Characters 目录失败: {e}")
        logger.warning(f"扫描 Characters 目录失败: {e}")
        return
    
    # 获取所有有剧情文件的角色 ID
    character_ids_with_scenario = set()
    if os.path.exists(adventure_char_dir):
        try:
            for item in os.listdir(adventure_char_dir):
                if item.startswith("CharaScenario") and item.endswith(".book.json"):
                    # 提取角色 ID（格式：CharaScenarioXXXXXXX.book.json）
                    try:
                        char_id = int(item.replace("CharaScenario", "").replace(".book.json", ""))
                        character_ids_with_scenario.add(char_id)
                    except ValueError:
                        continue
        except Exception as e:
            print(f"[警告] 扫描 Adventure/CharaScenario 目录失败: {e}")
            logger.warning(f"扫描 Adventure/CharaScenario 目录失败: {e}")
    
    # 不完整角色 = 有 Spine 但没有剧情（仅限玩家角色范围）
    state.incomplete_character_ids = character_ids_with_spine - character_ids_with_scenario
    
    if state.incomplete_character_ids:
        print(f"[信息] 检测到 {len(state.incomplete_character_ids)} 个不完整的玩家角色: {sorted(state.incomplete_character_ids)}")
        logger.info(f"检测到不完整的玩家角色: {sorted(state.incomplete_character_ids)}")
        
        # 保存到缓存文件
        try:
            with open(INCOMPLETE_CHARS_CACHE, 'w', encoding='utf-8') as f:
                f.write("# 不完整角色 ID 列表（自动生成）\n")
                f.write("# 这些角色只有 Spine 动画和头像，但没有剧情文件\n")
                f.write("# 只包含玩家角色 ID 范围（1000000 ~ 1999999），不包含敌人、NPC、素材等\n")
                f.write("# 如需重新扫描，请删除此文件\n")
                f.write("\n")
                for char_id in sorted(state.incomplete_character_ids):
                    f.write(f"{char_id}\n")
            print(f"[信息] 已保存到缓存文件: {INCOMPLETE_CHARS_CACHE}")
            logger.info(f"已保存不完整角色列表到缓存文件: {INCOMPLETE_CHARS_CACHE}")
        except Exception as e:
            print(f"[警告] 保存缓存文件失败: {e}")
            logger.warning(f"保存缓存文件失败: {e}")
    else:
        print("[信息] 未检测到不完整的玩家角色")
        logger.info("未检测到不完整的玩家角色")

def is_character_file(rel_path, char_ids):
    """
    判断文件是否属于指定的角色
    
    参数:
        rel_path: 相对路径，例如 "Characters/ch_1124001/ch_1124001_b.png"
        char_ids: 角色ID列表，例如 ["1124001", "1124002"]
    
    返回:
        bool: 如果文件属于指定角色则返回True
    """
    if not char_ids:
        return False
    
    rel_path_lower = rel_path.lower()
    
    for char_id in char_ids:
        # 检查各种可能的路径模式
        patterns = [
            f"characters/ch_{char_id}",
            f"cutin/{char_id}",
            f"gachacharaanim/gachacharaanim/tf_{char_id}",
            f"sound/voice/{char_id}",
            f"stills/st_{char_id}",
            f"adventure/charascenario/charascenario{char_id}",
        ]
        
        # 检查直接路径匹配
        for pattern in patterns:
            if pattern in rel_path_lower:
                return True
        
        # Sprites特殊处理（文件名包含角色ID）
        if "sprites/chara/thumb_" in rel_path_lower:
            filename = os.path.basename(rel_path_lower)
            if f"_{char_id}_" in filename or f"_{char_id}." in filename:
                return True
    
    return False

def choose_update_mode():
    """
    让用户选择更新模式
    
    返回:
        tuple: (mode, force_update_characters)
            mode: '1' (正常), '2' (Spine修复), '3' (角色完整更新)
            force_update_characters: 需要强制更新的角色ID列表
    """
    print("\n" + "="*70)
    print("【更新模式选择】")
    print("="*70)
    print("1. 正常更新模式")
    print("   • 只下载缺失的文件")
    print("   • 速度快，适合日常更新")
    print()
    print("2. Spine动画修复模式")
    print("   • 强制覆盖所有角色的Spine动画文件（PNG + atlas + skel）")
    print("   • 解决动画显示错误、分辨率不对等问题")
    print("   • 影响范围: Characters、Adventure/Spine、GachaCharaAnim、Stills")
    print("   • 下载量: 约50-100MB")
    print()
    print("3. 角色完整更新模式")
    print("   • 指定角色ID，重新下载该角色的所有资源")
    print("   • 解决角色从未实装变成已实装后资源不完整的问题")
    print("   • 影响范围: 指定角色的立绘、语音、Spine、头像、CG、剧本等")
    print("   • 下载量: 每个角色约100-200MB")
    print("="*70)
    
    # 选择模式
    while True:
        choice = input("\n请选择模式 (1/2/3): ").strip()
        if choice in ['1', '2', '3']:
            break
        print("输入无效，请输入 1、2 或 3")
    
    force_chars = []
    
    # 如果选择模式3，询问角色ID
    if choice == '3':
        print("\n" + "-"*70)
        print("【角色ID输入】")
        print("-"*70)
        print("请输入需要完整更新的角色ID（多个ID用逗号分隔）")
        print("示例: 1124001  或  1124001,1124002,1124003")
        print("提示: 如果不知道角色ID，可以先输入回车使用正常模式，")
        print("      然后查看游戏目录下的 Characters/ch_XXXXXX 文件夹名")
        print("-"*70)
        
        char_input = input("\n角色ID: ").strip()
        
        if char_input:
            # 解析输入的角色ID
            for item in char_input.split(','):
                item = item.strip()
                if item.isdigit() and len(item) == 7:  # 角色ID是7位数字
                    force_chars.append(item)
                elif item:
                    print(f"[警告] 忽略无效的角色ID: {item} (角色ID应为7位数字)")
        
        if not force_chars:
            print("\n[提示] 未输入有效的角色ID，将切换为正常更新模式")
            choice = '1'
        else:
            print(f"\n[确认] 将强制完整更新以下角色: {', '.join(force_chars)}")
            confirm = input("确认继续？(Y/N): ").strip().upper()
            if confirm not in ['Y', 'YES', '是']:
                print("[取消] 切换为正常更新模式")
                choice = '1'
                force_chars = []
    
    # 输出最终选择
    mode_names = {
        '1': '正常更新模式',
        '2': 'Spine动画修复模式',
        '3': f'角色完整更新模式 (角色: {", ".join(force_chars)})'
    }
    print(f"\n[√] 已选择: {mode_names[choice]}\n")
    logger.info(f"已选择更新模式: {mode_names[choice]}")
    
    return choice, force_chars

def sanitize_dict(obj_data):
    if isinstance(obj_data, (int, float, str, bool, type(None))):
        return obj_data
    elif isinstance(obj_data, dict):
        return {str(k): sanitize_dict(v) for k, v in obj_data.items()}
    elif isinstance(obj_data, list):
        return [sanitize_dict(v) for v in obj_data]
    elif isinstance(obj_data, bytes):
        return list(obj_data)
    elif hasattr(obj_data, "file_id") and hasattr(obj_data, "path_id"):
        return {"m_FileID": obj_data.file_id, "m_PathID": obj_data.path_id}
    elif hasattr(obj_data, "__dict__"):
        res = {}
        for k, v in obj_data.__dict__.items():
            if k.startswith("_") or k in["reader", "assets_file", "type", "object_reader", "version", "build_type", "platform"]:
                continue
            res[k] = sanitize_dict(v)
        return res
    else:
        return str(obj_data)

# ===== 路径映射规则表（数据驱动，供 get_target_relative_path 使用） =====
_PATH_PREFIXES = ["Assets/AssetBundles/", "Assets/"]
_PATH_TAGS_TO_REMOVE = {"HighQuality", "LowQuality", "adult", "general"}
_VALID_ROOTS_MAP = {
    "Adventure": "Adventure", "Adv": "Adventure",
    "Characters": "Characters", "Character": "Characters",
    "Cutin": "Cutin",
    "GachaCharaAnim": "GachaCharaAnim", "GachaAnim": "GachaCharaAnim",
    "Sound": "Sound", "Sounds": "Sound",
    "Sprites": "Sprites", "Sprite": "Sprites",
    "Stills": "Stills", "Still": "Stills",
}
_VALID_STRUCTURE = {
    "Adventure": {"BackGrounds", "CharaScenario", "Effects", "MainScenario",
                  "Spine", "StoryEventScenario", "SubjugationEventScenario", "Textures"},
    "Characters": None,
    "Cutin": None,
    "GachaCharaAnim": {"GachaCharaAnim", "gacha_bg_effect", "gacha_intro",
                       "new_chara_staging", "transform_eff", "ReferenceAssets"},
    "Sound": {"Bgm", "BgSe", "BgVoice", "Se", "Voice"},
    "Sprites": {"Bg", "Jukebox", "OutGame", "Chara", "PictureBook"},
    "Stills": None,
}


def _strip_prefix_and_tags(key):
    """去掉资源前缀并切分路径，过滤质量标签"""
    path = key
    for prefix in _PATH_PREFIXES:
        if path.startswith(prefix):
            path = path[len(prefix):]
    parts = path.split('/')
    return [p for p in parts if p not in _PATH_TAGS_TO_REMOVE]


def _locate_root(parts):
    """定位根目录并归一化名称；返回 (root_name, parts)，未找到返回 (None, None)"""
    for i, p in enumerate(parts):
        if p in _VALID_ROOTS_MAP:
            parts = parts[i:]
            parts[0] = _VALID_ROOTS_MAP[p]
            return _VALID_ROOTS_MAP[p], parts
    return None, None


def _apply_special_rules(root_name, parts, bypass_blacklist):
    """应用各根目录特殊规则；返回 (parts, early_final)。
    parts 为 None 表示应过滤；early_final 非 None 表示已得到最终路径"""
    basename = parts[-1]

    if root_name == "Cutin":
        if len(parts) > 1 and parts[1].lower() in ["characters", "character"]:
            parts.pop(1)

    if root_name == "Sprites" and len(parts) > 2 and parts[1].lower() == "chara" and parts[2].startswith("Thumb_"):
        if "_2_1" not in basename:
            return None, None
        if "S" in parts[:-1]:
            return None, None
        if basename.lower().startswith("sd_"):
            return None, None
        if basename.lower().startswith("chara_"):
            name_parts = basename.split('_')
            if len(name_parts) >= 2 and name_parts[1].isdigit():
                char_id = int(name_parts[1])
                # 过滤不完整角色（动态检测），但模式3可以绕过
                if not bypass_blacklist and char_id in state.incomplete_character_ids:
                    return None, None
                # 过滤高 ID 角色（>= 1900001）
                if char_id >= 1900001:
                    return None, None
        if "L" in parts[:-1]:
            parts.remove("L")

    if root_name == "Adventure":
        if basename == "Master.chapter.asset" or basename == "Master.chapter.json":
            return parts, "Adventure/Master.chapter.json"
        elif ".book" in basename:
            b_name = basename.replace('.asset', '.json')
            if basename.startswith("CharaScenario"):
                return parts, f"Adventure/CharaScenario/{b_name}"
            elif basename.startswith("MainScenario"):
                return parts, f"Adventure/MainScenario/{b_name}"
            elif basename.startswith("StoryEventScenario"):
                return parts, f"Adventure/StoryEventScenario/{b_name}"
            elif basename.startswith("SubjugationEventScenario"):
                return parts, f"Adventure/SubjugationEventScenario/{b_name}"
            else:
                return None, None
        # 其他 Adventure 资源（BackGrounds、Spine、Effects 等）继续往下处理

    if root_name == "GachaCharaAnim" and len(parts) >= 2 and parts[1].startswith("tf_"):
        parts.insert(1, "GachaCharaAnim")

    return parts, None


def _validate_structure(root_name, parts):
    """校验二级子目录结构并归一化大小写；不合法返回 None"""
    allowed_subs = _VALID_STRUCTURE[root_name]
    if allowed_subs is not None and len(parts) > 1:
        sub = parts[1]
        if len(parts) == 2 and '.' in sub:
            pass
        else:
            sub_lower = sub.lower()
            allowed_subs_lower = {s.lower(): s for s in allowed_subs}
            if sub_lower not in allowed_subs_lower:
                return None
            parts[1] = allowed_subs_lower[sub_lower]
    return parts


def _is_incomplete_character(root_name, parts, bypass_blacklist):
    """判断是否为不完整角色的 Spine 动画文件（模式3可绕过）"""
    if not bypass_blacklist and root_name == "Characters" and len(parts) >= 2:
        char_folder = parts[1]
        if char_folder.startswith("ch_"):
            try:
                char_id = int(char_folder[3:])  # 提取 ch_ 后面的数字
                if char_id in state.incomplete_character_ids:
                    return True
            except ValueError:
                pass  # 如果不是数字，继续处理
    return False


def _convert_extension(final_path):
    """转换目标文件扩展名；应过滤的返回 None"""
    if '.atlas' in final_path:
        return final_path.split('.atlas')[0] + '.atlas.txt'
    elif '.skel' in final_path:
        return final_path.split('.skel')[0] + '.skel.bytes'
    elif '.book' in final_path:
        return final_path.split('.book')[0] + '.book.json'
    elif '.chapter' in final_path:
        # 只保留 Master.chapter.json，其他 .chapter 文件都过滤掉（它们只有 1KB，没有用）
        final_path = final_path.split('.chapter')[0] + '.chapter.json'
        if final_path != "Adventure/Master.chapter.json":
            return None
    return final_path


def get_target_relative_path(key, bypass_blacklist=False):
    """
    将资源key转换为目标相对路径

    参数:
        key: 资源路径key
        bypass_blacklist: 是否绕过黑名单过滤（模式3使用）
    """
    parts = _strip_prefix_and_tags(key)
    if not parts:
        return None

    root_name, parts = _locate_root(parts)
    if root_name is None:
        return None

    parts, early_final = _apply_special_rules(root_name, parts, bypass_blacklist)
    if parts is None:
        return None
    if early_final is not None:
        return early_final

    parts = _validate_structure(root_name, parts)
    if parts is None:
        return None

    final_path = "/".join(parts)

    if _is_incomplete_character(root_name, parts, bypass_blacklist):
        return None

    return _convert_extension(final_path)

def process_bundle(bundle_url, missing_files, max_retries=3):
    local_extracted = 0
    
    for attempt in range(max_retries):
        try:
            bundle_res = requests.get(bundle_url, timeout=60)
            bundle_res.raise_for_status()
            env = UnityPy.load(bundle_res.content)
            
            for obj in env.objects:
                if obj.type.name in["Texture2D", "Sprite", "TextAsset", "AudioClip", "MonoBehaviour"]:
                    try:
                        data = obj.read()
                    except Exception as e:
                        logger.warning(f"跳过无法读取的对象 [{obj.type.name}]: {e}")
                        continue
                    name = str(getattr(data, "m_Name", getattr(data, "name", "")))
                    if not name: continue
                    
                    norm_name = name.split('.')[0]
                    target_path = None
                    
                    if obj.type.name in ["Texture2D", "Sprite"]:
                        for suffix in[".png", ".jpg", ".jpeg"]:
                            if f"{norm_name}{suffix}" in missing_files:
                                target_path = missing_files[f"{norm_name}{suffix}"]
                                break
                                
                    elif obj.type.name == "TextAsset":
                        content = getattr(data, "script", getattr(data, "m_Script", b""))
                        if isinstance(content, str):
                            content = content.encode('utf-8', errors='surrogateescape')
                            
                        is_bin = False
                        try:
                            content.decode('utf-8')
                        except UnicodeDecodeError:
                            is_bin = True
                            
                        if is_bin:
                            suffixes_to_try =[".skel", ".bytes"]
                        else:
                            content_str = content.decode('utf-8', errors='ignore')
                            if "size:" in content_str and "filter:" in content_str and "bounds:" in content_str:
                                suffixes_to_try = [".atlas"]
                            elif '"skeleton"' in content_str and '"bones"' in content_str:
                                suffixes_to_try = [".skel"]
                            else:
                                suffixes_to_try =[".book", ".chapter", ".json", ".txt"]
                                
                        for suffix in suffixes_to_try:
                            if f"{norm_name}{suffix}" in missing_files:
                                target_path = missing_files[f"{norm_name}{suffix}"]
                                break
                                    
                    elif obj.type.name == "AudioClip":
                        for suffix in [".ogg", ".wav"]:
                            if f"{norm_name}{suffix}" in missing_files:
                                target_path = missing_files[f"{norm_name}{suffix}"]
                                break
                                
                    elif obj.type.name == "MonoBehaviour":
                        for suffix in[".book", ".chapter", ".json"]:
                            if f"{norm_name}{suffix}" in missing_files:
                                target_path = missing_files[f"{norm_name}{suffix}"]
                                break
                                
                        if not target_path:
                            name_lower = name.lower()
                            if "scenario" in name_lower and name.endswith(".book"):
                                if name.startswith("CharaScenario"): target_path = f"Adventure/CharaScenario/{name}.json"
                                elif name.startswith("MainScenario"): target_path = f"Adventure/MainScenario/{name}.json"
                                elif name.startswith("StoryEventScenario"): target_path = f"Adventure/StoryEventScenario/{name}.json"
                                elif name.startswith("SubjugationEventScenario"): target_path = f"Adventure/SubjugationEventScenario/{name}.json"
                            elif name == "Master.chapter":
                                target_path = "Adventure/Master.chapter.json"
                                
                    if not target_path: continue
                        
                    full_save_path = os.path.join(OUTPUT_DIR, target_path)
                    
                    if obj.type.name in["Texture2D", "Sprite"]:
                        if not full_save_path.lower().endswith(".png"):
                            full_save_path = os.path.splitext(full_save_path)[0] + ".png"
                    
                    # 检查是否是需要优先从 Texture2D 提取的 PNG（Spine 动画和 CG）
                    is_texture2d_priority = False
                    if full_save_path.lower().endswith(".png"):
                        rel_path_lower = target_path.lower()
                        is_texture2d_priority = (
                            rel_path_lower.startswith("characters/") or
                            rel_path_lower.startswith("adventure/spine/") or
                            rel_path_lower.startswith("gachacharaanim/") or
                            rel_path_lower.startswith("stills/")
                        )
                    
                    # Sprite 类型的特殊 PNG 直接跳过，只保留 Texture2D（解决分辨率问题）
                    if obj.type.name == "Sprite" and is_texture2d_priority:
                        logger.debug(f"Skipped Sprite (Texture2D priority): {norm_name}")
                        continue
                    
                    # Spine 相关文件在修复模式下强制覆盖，其他文件跳过已存在的
                    is_spine_file = (
                        full_save_path.lower().endswith(".png") or
                        full_save_path.lower().endswith(".atlas.txt") or
                        full_save_path.lower().endswith(".skel.bytes")
                    )
                    is_spine_dir = (
                        target_path.lower().startswith("characters/") or
                        target_path.lower().startswith("adventure/spine/") or
                        target_path.lower().startswith("gachacharaanim/") or
                        target_path.lower().startswith("stills/")
                    )
                    skip_existing = (
                        os.path.exists(full_save_path) and
                        not (is_spine_file and is_spine_dir) and
                        not full_save_path.endswith("Master.chapter.json")
                    )
                    
                    if skip_existing:
                        logger.debug(f"Skipped existing: {os.path.basename(full_save_path)}")
                        continue
                        
                    os.makedirs(os.path.dirname(full_save_path), exist_ok=True)
                    
                    try:
                        if obj.type.name in["Texture2D", "Sprite"]:
                            data.image.save(full_save_path)
                            local_extracted += 1
                            logger.info(f"Saved: {os.path.basename(full_save_path)} ({obj.type.name})")
                            
                        elif obj.type.name == "TextAsset":
                            with open(full_save_path, "wb") as f: f.write(content)
                            local_extracted += 1
                            logger.info(f"Saved: {os.path.basename(full_save_path)} (TextAsset)")
                            
                        elif obj.type.name == "AudioClip":
                            samples = data.samples
                            if samples:
                                raw_audio_data = list(samples.values())[0]
                                # 源音频实际是 m4a/aac（UnityPy samples 的 key 带真实扩展名），
                                # 用真实扩展名做临时文件，让 FFmpeg 明确按该格式解码，不再靠嗅探
                                sample_key = next(iter(samples), "")
                                temp_ext = os.path.splitext(sample_key)[1] or ".m4a"
                                temp_audio_path = full_save_path + ".temp" + temp_ext
                                with open(temp_audio_path, "wb") as f: 
                                    f.write(raw_audio_data)
                                
                                with state.queue_lock:
                                    state.audio_convert_queue.append((temp_audio_path, full_save_path, name))
                                local_extracted += 1
                                logger.info(f"Queued for conversion: {os.path.basename(full_save_path)} (AudioClip)")
                                
                        elif obj.type.name == "MonoBehaviour":
                            tree = None
                            for method in["read_dict", "read_typetree"]:
                                if hasattr(data, method):
                                    try: tree = getattr(data, method)()
                                    except Exception: pass
                                if not tree and hasattr(obj, method):
                                    try: tree = getattr(obj, method)()
                                    except Exception: pass
                            if not tree:
                                tree = data.__dict__
                                
                            if tree:
                                safe_tree = sanitize_dict(tree)
                                new_content = json.dumps(safe_tree, ensure_ascii=False, indent=2)
                                
                                # Master.chapter.json 内容对比
                                if full_save_path.endswith("Master.chapter.json") and os.path.exists(full_save_path):
                                    try:
                                        with open(full_save_path, "r", encoding="utf-8") as f:
                                            old_content = f.read()
                                        if old_content == new_content:
                                            logger.info("Master.chapter.json content unchanged, skipped")
                                            continue  # 内容相同，跳过
                                        else:
                                            logger.info("Master.chapter.json content changed, updating")
                                    except Exception as e:
                                        logger.warning(f"读取 Master.chapter.json 失败，将重新下载: {e}")
                                
                                with open(full_save_path, "w", encoding="utf-8") as f:
                                    f.write(new_content)
                                local_extracted += 1
                                logger.info(f"Saved: {os.path.basename(full_save_path)} (MonoBehaviour)")
                                    
                    except Exception as e:
                        logger.error(f"提取失败 [{name}]: {e}")
            break 
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"资源包下载/解析失败，第 {attempt + 1} 次重试 [{bundle_url}]: {e}")
                time.sleep(2)
            else:
                logger.error(f"资源包最终失败（已重试 {max_retries} 次）[{bundle_url}]: {e}")
            
    with state.progress_lock:
        state.global_progress += 1
        if local_extracted > 0:
            log_progress(f"[{state.global_progress}/{state.total_bundles_to_dl}] 成功提取资源包文件: {local_extracted} 项")

    return local_extracted

def convert_audio_task(temp_audio, final_ogg, name):
    """独立的 FFmpeg 音频转码任务"""
    try:
        cmd =[
            FFMPEG_EXE, "-y", "-loglevel", "error",
            "-i", temp_audio, 
            "-c:a", "libvorbis", 
            "-q:a", "4", 
            final_ogg
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            stderr_msg = result.stderr.decode('utf-8', errors='replace').strip()
            logger.warning(f"音频转码失败 [{name}]: {stderr_msg[:500]}")
    except Exception as e:
        logger.warning(f"音频转码异常 [{name}]: {e}")
    finally:
        if os.path.exists(temp_audio):
            try: os.remove(temp_audio)
            except Exception as e:
                logger.debug(f"清理临时文件失败 [{temp_audio}]: {e}")

def main():
    print("=================================================================")
    print("    Twinkle Star Knights X 离线版资源自动更新工具 v1.11.0")
    print("=================================================================")
    print(f"[*] 资源存放路径: {os.path.abspath(OUTPUT_DIR)}")
    print(f"[*] 运行状态日志: update_log.txt\n")
    logger.info(f"========== 启动 v1.11.0，资源路径: {os.path.abspath(OUTPUT_DIR)} ==========")
    
    # 检测不完整角色
    detect_incomplete_characters()
    print()
    
    # 选择更新模式
    update_mode, state.force_update_characters = choose_update_mode()
    
    cleaned_count = 0
    if os.path.exists(OUTPUT_DIR):
        for root_dir, dirs, files in os.walk(OUTPUT_DIR):
            for f in files:
                full_path = os.path.join(root_dir, f)
                if f.endswith(".skel.bytes"):
                    try:
                        with open(full_path, "r", encoding="utf-8") as file:
                            head = file.read(2048)
                            if "size:" in head and "filter:" in head:
                                file.close()
                                os.remove(full_path) 
                                cleaned_count += 1
                    except Exception as e:
                        logger.debug(f"清理 .skel.bytes 失败 [{full_path}]: {e}")
                elif f.endswith(".chapter.json") and f != "Master.chapter.json":
                    try:
                        os.remove(full_path)
                        cleaned_count += 1
                    except Exception as e:
                        logger.debug(f"清理 .chapter.json 失败 [{full_path}]: {e}")
                elif ".temp." in f:
                    try:
                        os.remove(full_path)
                    except Exception as e:
                        logger.debug(f"清理音频临时文件失败 [{full_path}]: {e}")
                    
    if cleaned_count > 0:
        log_progress(f"[*] 启动自检: 已自动清理历史冲突及无用碎片 {cleaned_count} 项")

    log_progress("[1/5] 正在连接服务器获取最新资源索引...")
    try:
        # 下载 catalog.bundle
        res = requests.get(CATALOG_BUNDLE_URL, timeout=60)
        res.raise_for_status()
        
        # 解析 Unity Bundle 提取 catalog JSON
        env = UnityPy.load(res.content)
        catalog_json = None
        
        for obj in env.objects:
            if obj.type.name == "TextAsset":
                data = obj.read()
                # 兼容不同的属性名
                raw_data = getattr(data, "m_Script", getattr(data, "script", None))
                
                if raw_data is None:
                    continue
                    
                # 处理不同的数据类型
                if isinstance(raw_data, str):
                    json_text = raw_data
                elif isinstance(raw_data, bytes):
                    json_text = raw_data.decode('utf-8', errors='ignore')
                else:
                    continue
                
                # 清理末尾的空字符
                json_text = json_text.strip('\x00')
                
                try:
                    catalog_json = json.loads(json_text)
                    log_progress(f"✓ 成功解析资源索引，共 {len(catalog_json.get('m_InternalIds', []))} 个资源")
                    break
                except Exception:
                    continue
                    
        if not catalog_json:
            raise Exception("无法从 catalog.bundle 中提取资源索引")
            
        catalog_data = catalog_json
    except Exception as e:
        print(f"[!] 网络异常，无法获取清单: {e}")
        print(f"    当前 catalog 地址: {CATALOG_BUNDLE_URL}")
        print("    提示: 若地址已失效，请开网页/游戏用 F12 确认新地址后，")
        print("    通过环境变量 TSK_CATALOG_BUNDLE_URL / TSK_RUNTIME_PATH 覆盖，")
        print("    或直接修改脚本顶部『工具配置区』的常量。")
        logger.error(f"获取资源索引失败: {e}")
        input("\n按回车键退出...")
        return

    log_progress("[2/5] 正在解析并构建双轨合并资源树...")
    catalog = parse(json.dumps(catalog_data))
    valid_exts = {".png", ".txt", ".bytes", ".json", ".ogg", ".wav", ".asset", ".atlas", ".skel"}
    
    # 模式3需要绕过黑名单过滤
    bypass_blacklist = (update_mode == '3')
    
    best_keys = {}
    for key in catalog.Resources.keys():
        if not isinstance(key, str): continue
        if "LowQuality" in key: continue 
        
        ext = os.path.splitext(key)[-1].lower()
        if ext not in valid_exts: continue

        basename = key.split('/')[-1]
        if any(ignore in basename for ignore in["_Atlas", "_SkeletonData", "_Material"]):
            continue

        clean_path = get_target_relative_path(key, bypass_blacklist)
        
        # 跳过无法映射到目标路径的资源（但保留 Master.chapter 用于后续合成）
        if not clean_path and ".chapter" not in basename:
            continue
        
        # 只添加有效映射的资源
        if clean_path:
            if clean_path not in best_keys:
                best_keys[clean_path] = key
            else:
                if "/adult/" in key or "_adult" in key:
                    best_keys[clean_path] = key
        elif ".chapter" in basename:
            # Master.chapter 文件即使没有 clean_path 也保留（用于后续合成 .book 文件）
            # 其他 .chapter 文件已在 get_target_relative_path 中被过滤
            best_keys[basename] = key

    allowed_keys = set(best_keys.values())
    target_bundles = {} 
    
    for key, locs in catalog.Resources.items():
        if key not in allowed_keys: continue
        
        ext = os.path.splitext(key)[-1].lower()
        basename = key.split('/')[-1]
        clean_path = get_target_relative_path(key, bypass_blacklist)
        
        norm_key = basename.split('.')[0]
        if ".atlas" in basename: norm_key += ".atlas"
        elif ".skel" in basename: norm_key += ".skel"
        elif ".book" in basename: norm_key += ".book"
        elif ".chapter" in basename: norm_key += ".chapter"
        elif ext in[".png", ".jpg", ".jpeg"]: norm_key += ".png"
        elif ext in[".ogg", ".wav"]: norm_key += ".ogg"
        
        dep_key = locs[0].DependencyKey
        if dep_key in catalog.Resources:
            bundle_url = catalog.Resources[dep_key][0].InternalId
            # 替换模板字符串为实际 CDN 地址
            bundle_url = bundle_url.replace("{UnityEngine.AddressableAssets.Addressables.RuntimePath}", RUNTIME_PATH)
            if not bundle_url.endswith(".bundle"): continue
            
            # 只有确实有文件要添加时，才创建 bundle（避免空 bundle）
            if clean_path:
                if bundle_url not in target_bundles:
                    target_bundles[bundle_url] = {}
                target_bundles[bundle_url][norm_key] = clean_path

            # .chapter 文件的特殊处理：合成对应的 .book 文件
            if ".chapter" in norm_key and "Master.chapter" not in norm_key:
                base_num = norm_key.split(".")[0] 
                synth_key = None
                synth_path = None
                if base_num.isdigit():
                    synth_key = f"CharaScenario{base_num}.book"
                    synth_path = f"Adventure/CharaScenario/{synth_key}.json"
                elif base_num.startswith("MainScenario"):
                    synth_key = f"{base_num}.book"
                    synth_path = f"Adventure/MainScenario/{synth_key}.json"
                elif base_num.startswith("StoryEventScenario"):
                    synth_key = f"{base_num}.book"
                    synth_path = f"Adventure/StoryEventScenario/{synth_key}.json"
                elif base_num.startswith("SubjugationEventScenario"):
                    synth_key = f"{base_num}.book"
                    synth_path = f"Adventure/SubjugationEventScenario/{synth_key}.json"
                    
                if synth_key:
                    if bundle_url not in target_bundles:
                        target_bundles[bundle_url] = {}
                    target_bundles[bundle_url][synth_key] = synth_path

    log_progress("[3/5] 正在扫描本地文件差异 (智能跳过已下载内容)...")
    bundles_to_download = {}
    for url, files in target_bundles.items():
        missing_files = {}
        for norm_key, rel_path in files.items():
            full_path = os.path.join(OUTPUT_DIR, rel_path)
            
            # 统一的文件存在性检查：优先检查 PNG 格式（因为很多资源会被转换为 PNG）
            check_path = full_path
            if not check_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                # 非图片文件，可能会被转换为 PNG，检查 PNG 版本
                png_path = os.path.splitext(check_path)[0] + '.png'
                if os.path.exists(png_path):
                    # PNG 版本已存在，跳过
                    continue
            
            # 检查是否是 Spine 文件（PNG, atlas.txt, skel.bytes）
            rel_path_lower = rel_path.lower()
            is_spine_dir = (
                rel_path_lower.startswith("characters/") or
                rel_path_lower.startswith("adventure/spine/") or
                rel_path_lower.startswith("gachacharaanim/") or
                rel_path_lower.startswith("stills/")
            )
            is_spine_file = (
                check_path.lower().endswith(".png") or
                check_path.lower().endswith(".atlas.txt") or
                check_path.lower().endswith(".skel.bytes")
            )
            is_fixable_spine = is_spine_dir and is_spine_file
            
            # 判断是否需要更新
            needs_update = False
            
            # 1. Master.chapter.json 特殊处理（所有模式共享）
            if check_path.endswith("Master.chapter.json"):
                if os.path.exists(check_path):
                    logger.info("Master.chapter.json exists, will compare after download")
                    needs_update = True  # 先下载，提取时对比
                else:
                    logger.info("Master.chapter.json not found locally, will download")
                    needs_update = True
            
            # 2. 根据更新模式判断
            elif update_mode == '1':  # 正常更新模式
                if not os.path.exists(check_path):
                    needs_update = True
                    
            elif update_mode == '2':  # Spine修复模式
                if not os.path.exists(check_path):
                    needs_update = True
                elif is_fixable_spine:
                    # 修复模式下强制更新 Spine 文件
                    logger.info(f"Spine fix mode: force update {rel_path}")
                    needs_update = True
                    
            elif update_mode == '3':  # 角色完整更新模式
                if not os.path.exists(check_path):
                    needs_update = True
                elif is_character_file(rel_path, state.force_update_characters):
                    # 属于指定角色，强制更新
                    logger.info(f"Character update mode: force update {rel_path}")
                    needs_update = True
            
            if needs_update:
                missing_files[norm_key] = rel_path
                
        if missing_files:
            bundles_to_download[url] = missing_files
            logger.info(f"Bundle queued: {len(missing_files)} files - {list(missing_files.keys())[:10]}")

    state.total_bundles_to_dl = len(bundles_to_download)
    if state.total_bundles_to_dl == 0:
        log_progress("[+] 校验完成，本地各项资源均已是最新版本！")
        input("\n按回车键退出...")
        return

    log_progress(f" -> 对比完成！本次需要更新或下载 {state.total_bundles_to_dl} 个资源包。")
    log_progress("[4/5] 启动多线程资源下载与解析引擎...")
    logger.info(f"Update started. Targets: {state.total_bundles_to_dl}")
    
    extracted_total = 0
    # 下载解包阶段：网络 IO 密集型，保持 10 线程并发
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures =[executor.submit(process_bundle, url, files) for url, files in bundles_to_download.items()]
        for future in as_completed(futures):
            extracted_total += future.result()
            
    if state.audio_convert_queue:
        log_progress(f"[5/5] 启动音频安全转码引擎，待处理音频: {len(state.audio_convert_queue)} 个")
        # 【核心修正】根据网友电脑的 CPU 核心数动态分配安全线程，防止 I/O 卡死
        # 最大不超过 16 线程，最少 2 线程
        safe_workers = min(16, max(2, (os.cpu_count() or 4) + 2))
        logger.info(f"分配转码线程数: {safe_workers}")
        
        converted_count = 0
        with ThreadPoolExecutor(max_workers=safe_workers) as audio_executor:
            futures =[audio_executor.submit(convert_audio_task, temp, final, name) for temp, final, name in state.audio_convert_queue]
            for future in as_completed(futures):
                converted_count += 1
                if converted_count % 100 == 0 or converted_count == len(state.audio_convert_queue):
                    print(f" -> 转码进度:[{converted_count}/{len(state.audio_convert_queue)}]")

    log_progress(f"[+] 更新与转码任务圆满完成！本次共计新增/修复文件: {extracted_total} 个。")
    logger.info(f"Update finished. Files processed: {extracted_total}")
    input("\n按回车键退出...")

if __name__ == "__main__":
    main()