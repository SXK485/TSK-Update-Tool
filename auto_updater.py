"""
Twinkle Star Knights X 离线版资源自动更新工具
版本: v1.6.3 (Stable)
说明: 自动化同步、精简并转换游戏资源至离线播放器格式。
新增: 彻底阻断中间态碎片文件(.chapter)落盘，保障剧本目录极限纯净。
"""

import os
import requests
import UnityPy
import logging
import time
import json
from AddressablesTools import parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ================= 工具配置区 =================
SERVER_URL = "https://dz87n5pasv7ep.cloudfront.net/assetbundle/game/"
CATALOG_URL = SERVER_URL + "catalog_0.0.0.json"

# 默认相对于脚本运行目录的资源路径
OUTPUT_DIR = "Twinkle Star Knights X_Data/StreamingAssets/Twinkle Star Knights X"
# ============================================

# 初始化日志系统
logger = logging.getLogger("TSK_Updater")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("update_log.txt", mode="a", encoding="utf-8")
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(file_handler)

progress_lock = Lock()
global_progress = 0
total_bundles_to_dl = 0

def sanitize_dict(obj_data):
    """递归序列化引擎：将 C# 对象安全转换为标准 JSON 字典"""
    if isinstance(obj_data, (int, float, str, bool, type(None))):
        return obj_data
    elif isinstance(obj_data, dict):
        return {str(k): sanitize_dict(v) for k, v in obj_data.items()}
    elif isinstance(obj_data, list):
        return[sanitize_dict(v) for v in obj_data]
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

def get_target_relative_path(key):
    """核心路径解析器：将打包路径映射到本地离线目录，实施严格拦截与精简"""
    path = key
    for prefix in ["Assets/AssetBundles/", "Assets/"]:
        if path.startswith(prefix):
            path = path[len(prefix):]
            
    parts = path.split('/')
    tags_to_remove = {"HighQuality", "LowQuality", "adult", "general"}
    parts = [p for p in parts if p not in tags_to_remove]
    
    if not parts: return None
        
    valid_roots_map = {
        "Adventure": "Adventure", "Adv": "Adventure",
        "Characters": "Characters", "Character": "Characters",
        "Cutin": "Cutin",
        "GachaCharaAnim": "GachaCharaAnim", "GachaAnim": "GachaCharaAnim",
        "Sound": "Sound", "Sounds": "Sound",
        "Sprites": "Sprites", "Sprite": "Sprites",
        "Stills": "Stills", "Still": "Stills"
    }
    
    found_idx = -1
    root_name = None
    for i, p in enumerate(parts):
        if p in valid_roots_map:
            found_idx = i
            root_name = valid_roots_map[p]
            break
            
    if found_idx == -1: return None 
        
    parts = parts[found_idx:]
    parts[0] = root_name 
    root = root_name
    basename = parts[-1]
    
    # 路径裁切：去除 Cutin 多余的子目录
    if root == "Cutin":
        if len(parts) > 1 and parts[1].lower() in["characters", "character"]:
            parts.pop(1)
            
    # 头像精简系统：仅保留 L 级大图的觉醒形态（_2_1），剥离冗余层级、剔除无 R18 的 ID 及 SD 小人
    if root == "Sprites" and len(parts) > 2 and parts[1].lower() == "chara" and parts[2].startswith("Thumb_"):
        if "_2_1" not in basename:
            return None
        if "S" in parts[:-1]:
            return None
        if basename.lower().startswith("sd_"):
            return None
            
        if basename.lower().startswith("chara_"):
            name_parts = basename.split('_')
            if len(name_parts) >= 2 and name_parts[1].isdigit():
                chara_id = int(name_parts[1])
                if chara_id >= 1900001:
                    return None
                    
        if "L" in parts[:-1]:
            parts.remove("L")
            
    # 【完美修正】剧本专项路由：只放行 .book 剧本实体和 Master.chapter，拦截一切碎片！
    if root == "Adventure":
        if basename == "Master.chapter.asset" or basename == "Master.chapter.json":
            return "Adventure/Master.chapter.json"
        elif ".book" in basename:
            b_name = basename.replace('.asset', '.json')
            if basename.startswith("CharaScenario"): return f"Adventure/CharaScenario/{b_name}"
            elif basename.startswith("MainScenario"): return f"Adventure/MainScenario/{b_name}"
            elif basename.startswith("StoryEventScenario"): return f"Adventure/StoryEventScenario/{b_name}"
            elif basename.startswith("SubjugationEventScenario"): return f"Adventure/SubjugationEventScenario/{b_name}"
            else: return None
        else:
            # 彻底拉黑诸如 1001001.chapter.asset 等中间态文件
            return None 

    if root == "GachaCharaAnim" and len(parts) >= 2 and parts[1].startswith("tf_"):
        parts.insert(1, "GachaCharaAnim")
        
    valid_structure = {
        "Adventure": {"BackGrounds", "CharaScenario", "Effects", "MainScenario", 
                      "Spine", "StoryEventScenario", "SubjugationEventScenario", "Textures"},
        "Characters": None, 
        "Cutin": None,
        "GachaCharaAnim": {"GachaCharaAnim", "gacha_bg_effect", "gacha_intro", 
                           "new_chara_staging", "transform_eff", "ReferenceAssets"},
        "Sound": {"Bgm", "BgSe", "BgVoice", "Se", "Voice"},
        "Sprites": {"Bg", "Jukebox", "OutGame", "Chara", "PictureBook"},
        "Stills": None
    }
    
    allowed_subs = valid_structure[root]
    
    if allowed_subs is not None and len(parts) > 1:
        sub = parts[1]
        if len(parts) == 2 and '.' in sub:
            pass
        else:
            sub_lower = sub.lower()
            allowed_subs_lower = {s.lower(): s for s in allowed_subs}
            if sub_lower not in allowed_subs_lower: return None 
            parts[1] = allowed_subs_lower[sub_lower] 
            
    final_path = "/".join(parts)
    
    # 转换为离线播放器适配后缀
    if '.atlas' in final_path: final_path = final_path.split('.atlas')[0] + '.atlas.txt'
    elif '.skel' in final_path: final_path = final_path.split('.skel')[0] + '.skel.bytes'
    elif '.book' in final_path: final_path = final_path.split('.book')[0] + '.book.json'
    elif '.chapter' in final_path: final_path = final_path.split('.chapter')[0] + '.chapter.json'
        
    return final_path

def process_bundle(bundle_url, missing_files, max_retries=3):
    global global_progress
    local_extracted = 0
    
    for attempt in range(max_retries):
        try:
            bundle_res = requests.get(bundle_url, timeout=60)
            bundle_res.raise_for_status()
            env = UnityPy.load(bundle_res.content)
            
            for obj in env.objects:
                if obj.type.name in["Texture2D", "Sprite", "TextAsset", "AudioClip", "MonoBehaviour"]:
                    data = obj.read()
                    name = str(getattr(data, "m_Name", getattr(data, "name", "")))
                    if not name: continue
                    
                    norm_name = name.split('.')[0]
                    target_path = None
                    
                    # 1. 常规后缀匹配
                    for s in["", ".png", ".jpg", ".txt", ".bytes", ".json", ".atlas", ".skel", ".book", ".chapter"]:
                        if f"{norm_name}{s}" in missing_files:
                            target_path = missing_files[f"{norm_name}{s}"]
                            break
                            
                    # 2. 内存级剧本关联贪婪提取
                    if not target_path and obj.type.name == "MonoBehaviour":
                        if name.startswith("CharaScenario") and name.endswith(".book"):
                            target_path = f"Adventure/CharaScenario/{name}.json"
                        elif name.startswith("MainScenario") and name.endswith(".book"):
                            target_path = f"Adventure/MainScenario/{name}.json"
                        elif name.startswith("StoryEventScenario") and name.endswith(".book"):
                            target_path = f"Adventure/StoryEventScenario/{name}.json"
                        elif name.startswith("SubjugationEventScenario") and name.endswith(".book"):
                            target_path = f"Adventure/SubjugationEventScenario/{name}.json"
                        elif name == "Master.chapter":
                            target_path = "Adventure/Master.chapter.json"
                            
                    if not target_path:
                        continue
                        
                    full_save_path = os.path.join(OUTPUT_DIR, target_path)
                    
                    # 统一图片扩展名为小写 png
                    if obj.type.name in ["Texture2D", "Sprite"]:
                        if not full_save_path.lower().endswith(".png"):
                            full_save_path = os.path.splitext(full_save_path)[0] + ".png"
                            
                    # Master.chapter.json 拥有绝对覆盖特权，其余文件防重复写入
                    if os.path.exists(full_save_path) and not full_save_path.endswith("Master.chapter.json"):
                        continue
                        
                    os.makedirs(os.path.dirname(full_save_path), exist_ok=True)
                    
                    try:
                        if obj.type.name in["Texture2D", "Sprite"]:
                            data.image.save(full_save_path)
                            local_extracted += 1
                            
                        elif obj.type.name == "TextAsset":
                            content = getattr(data, "script", getattr(data, "m_Script", b""))
                            if isinstance(content, str): content = content.encode('utf-8', errors='surrogateescape')
                            with open(full_save_path, "wb") as f: f.write(content)
                            local_extracted += 1
                            
                        elif obj.type.name == "AudioClip":
                            samples = data.samples
                            if samples:
                                with open(full_save_path, "wb") as f: f.write(list(samples.values())[0])
                                local_extracted += 1
                                
                        elif obj.type.name == "MonoBehaviour":
                            tree = None
                            if hasattr(data, "read_dict"):
                                try: tree = data.read_dict()
                                except: pass
                            if not tree and hasattr(data, "read_typetree"):
                                try: tree = data.read_typetree()
                                except: pass
                            if not tree and hasattr(obj, "read_typetree"):
                                try: tree = obj.read_typetree()
                                except: pass
                                
                            if not tree:
                                tree = data.__dict__
                                
                            if tree:
                                safe_tree = sanitize_dict(tree)
                                with open(full_save_path, "w", encoding="utf-8") as f:
                                    json.dump(safe_tree, f, ensure_ascii=False, indent=2)
                                local_extracted += 1
                                    
                    except Exception as e:
                        logger.error(f"提取失败 [{name}]: {e}")
            break 
        except Exception as e:
            if attempt < max_retries - 1: time.sleep(2)
            
    with progress_lock:
        global_progress += 1
        if local_extracted > 0:
            print(f"[{global_progress}/{total_bundles_to_dl}] 成功提取资源项: {local_extracted}")

    return local_extracted

def main():
    global total_bundles_to_dl
    print("=================================================================")
    print("    Twinkle Star Knights X 离线版资源自动更新工具 v1.6.3")
    print("=================================================================")
    print(f"[*] 资源输出目录: {os.path.abspath(OUTPUT_DIR)}")
    print(f"[*] 运行状态日志: update_log.txt\n")
    
    # 历史遗留文件智能清理系统
    cleaned_count = 0
    if os.path.exists(OUTPUT_DIR):
        for root_dir, dirs, files in os.walk(OUTPUT_DIR):
            for f in files:
                # 1. 清理假骨骼
                if f.endswith(".skel.bytes"):
                    full_path = os.path.join(root_dir, f)
                    try:
                        with open(full_path, "r", encoding="utf-8") as file:
                            head = file.read(2048)
                            if "size:" in head and "filter:" in head:
                                file.close()
                                os.remove(full_path) 
                                cleaned_count += 1
                    except Exception: pass 
                # 2. 自动清理被弃用的 .chapter.json 碎片文件
                if f.endswith(".chapter.json") and f != "Master.chapter.json":
                    full_path = os.path.join(root_dir, f)
                    try:
                        os.remove(full_path)
                        cleaned_count += 1
                    except Exception: pass
                    
    if cleaned_count > 0:
        print(f"[*] 启动自检: 已自动清理历史遗留及冲突文件 {cleaned_count} 项\n")

    print("[1/4] 正在连接服务器获取最新资源索引...")
    try:
        res = requests.get(CATALOG_URL, timeout=30)
        res.raise_for_status()
        catalog_data = res.text
    except Exception as e:
        print(f"[!] 网络异常，无法获取清单: {e}")
        os.system("pause")
        return

    print("[2/4] 正在解析并构建双轨合并资源依赖树...")
    catalog = parse(catalog_data)
    valid_exts = {".png", ".txt", ".bytes", ".json", ".ogg", ".wav", ".asset", ".atlas", ".skel"}
    
    best_keys = {}
    for key in catalog.Resources.keys():
        if not isinstance(key, str): continue
        if "LowQuality" in key: continue 
        
        ext = os.path.splitext(key)[-1].lower()
        if ext not in valid_exts: continue

        basename = key.split('/')[-1]
        if any(ignore in basename for ignore in["_Atlas", "_SkeletonData", "_Material"]):
            continue

        clean_path = get_target_relative_path(key)
        
        # 保留 chapter 作为引导猎犬
        if not clean_path and ".chapter" not in basename:
            continue
        
        if clean_path:
            if clean_path not in best_keys:
                best_keys[clean_path] = key
            else:
                if "/adult/" in key or "_adult" in key:
                    best_keys[clean_path] = key
        else:
            best_keys[basename] = key

    allowed_keys = set(best_keys.values())
    target_bundles = {} 
    
    for key, locs in catalog.Resources.items():
        if key not in allowed_keys: continue
        
        ext = os.path.splitext(key)[-1].lower()
        basename = key.split('/')[-1]
        clean_path = get_target_relative_path(key)
        
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
            if not bundle_url.endswith(".bundle"): continue
            
            if bundle_url not in target_bundles:
                target_bundles[bundle_url] = {}
                
            if clean_path:
                target_bundles[bundle_url][norm_key] = clean_path

            # 【隐性依赖拉取】发现 .chapter 时挂上 .book 的逮捕令
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
                    target_bundles[bundle_url][synth_key] = synth_path

    print("[3/4] 正在执行本地文件差分比对 (排查遗漏与更新项)...")
    bundles_to_download = {}
    for url, files in target_bundles.items():
        missing_files = {}
        for norm_key, rel_path in files.items():
            full_path = os.path.join(OUTPUT_DIR, rel_path)
            
            check_path = full_path
            if os.path.splitext(check_path)[1].lower() not in['.png', '.jpg', '.jpeg']:
                png_path = os.path.splitext(check_path)[0] + '.png'
                if os.path.exists(png_path): continue 
                    
            # Master.chapter.json 无条件强制更新
            if not os.path.exists(check_path) or check_path.endswith("Master.chapter.json"):
                missing_files[norm_key] = rel_path
                
        if missing_files:
            bundles_to_download[url] = missing_files

    total_bundles_to_dl = len(bundles_to_download)
    if total_bundles_to_dl == 0:
        print("\n[+] 校验完成，本地资源已全部是最新版本。")
        os.system("pause")
        return

    print(f" -> 对比完成！本次共计需要增量同步/强制更新 {total_bundles_to_dl} 个包裹。")
    print(f"\n[4/4] 启动多核并发下载引擎...")
    logger.info(f"Update started. Targets: {total_bundles_to_dl}")
    
    extracted_total = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures =[executor.submit(process_bundle, url, files) for url, files in bundles_to_download.items()]
        for future in as_completed(futures):
            extracted_total += future.result()

    print(f"\n[+] 资源同步成功！本次共计新增/覆盖文件 {extracted_total} 项。")
    logger.info(f"Update finished. Files written: {extracted_total}")
    os.system("pause")

if __name__ == "__main__":
    main()