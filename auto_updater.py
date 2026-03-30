"""
Twinkle Star Knights X 离线版资源自动更新工具
版本: v1.8.3 (Stable)
说明: 自动化同步、精简并转换游戏资源至离线播放器格式。
优化: 引入温和的动态多线程调度算法，完美适配低配与高配电脑，防止 I/O 阻塞卡死。
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
    os.system("pause")
    exit(1)

# ================= 工具配置区 =================
SERVER_URL = "https://dz87n5pasv7ep.cloudfront.net/assetbundle/game/"
CATALOG_URL = SERVER_URL + "catalog_0.0.0.json"
OUTPUT_DIR = "Twinkle Star Knights X_Data/StreamingAssets/Twinkle Star Knights X"
# ============================================

logger = logging.getLogger("TSK_Updater")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("update_log.txt", mode="a", encoding="utf-8")
file_handler.setFormatter(logging.Formatter('%(asctime)s[%(levelname)s] %(message)s'))
logger.addHandler(file_handler)

progress_lock = Lock()
queue_lock = Lock()
global_progress = 0
total_bundles_to_dl = 0
audio_convert_queue =[]

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

def get_target_relative_path(key):
    path = key
    for prefix in ["Assets/AssetBundles/", "Assets/"]:
        if path.startswith(prefix):
            path = path[len(prefix):]
            
    parts = path.split('/')
    tags_to_remove = {"HighQuality", "LowQuality", "adult", "general"}
    parts =[p for p in parts if p not in tags_to_remove]
    
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
    basename = parts[-1]
    
    if root_name == "Cutin":
        if len(parts) > 1 and parts[1].lower() in ["characters", "character"]:
            parts.pop(1)
            
    if root_name == "Sprites" and len(parts) > 2 and parts[1].lower() == "chara" and parts[2].startswith("Thumb_"):
        if "_2_1" not in basename: return None
        if "S" in parts[:-1]: return None
        if basename.lower().startswith("sd_"): return None
        if basename.lower().startswith("chara_"):
            name_parts = basename.split('_')
            if len(name_parts) >= 2 and name_parts[1].isdigit():
                if int(name_parts[1]) >= 1900001:
                    return None
        if "L" in parts[:-1]:
            parts.remove("L")
            
    if root_name == "Adventure":
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
            return None 

    if root_name == "GachaCharaAnim" and len(parts) >= 2 and parts[1].startswith("tf_"):
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
    
    allowed_subs = valid_structure[root_name]
    
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
                            
                    if os.path.exists(full_save_path) and not full_save_path.endswith("Master.chapter.json"):
                        continue
                        
                    os.makedirs(os.path.dirname(full_save_path), exist_ok=True)
                    
                    try:
                        if obj.type.name in["Texture2D", "Sprite"]:
                            data.image.save(full_save_path)
                            local_extracted += 1
                            
                        elif obj.type.name == "TextAsset":
                            with open(full_save_path, "wb") as f: f.write(content)
                            local_extracted += 1
                            
                        elif obj.type.name == "AudioClip":
                            samples = data.samples
                            if samples:
                                raw_audio_data = list(samples.values())[0]
                                temp_wav_path = full_save_path + ".temp.wav"
                                with open(temp_wav_path, "wb") as f: 
                                    f.write(raw_audio_data)
                                
                                with queue_lock:
                                    audio_convert_queue.append((temp_wav_path, full_save_path, name))
                                local_extracted += 1
                                
                        elif obj.type.name == "MonoBehaviour":
                            tree = None
                            for method in["read_dict", "read_typetree"]:
                                if hasattr(data, method):
                                    try: tree = getattr(data, method)()
                                    except: pass
                                if not tree and hasattr(obj, method):
                                    try: tree = getattr(obj, method)()
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
            print(f"[{global_progress}/{total_bundles_to_dl}] 成功提取资源包文件: {local_extracted} 项")

    return local_extracted

def convert_audio_task(temp_wav, final_ogg, name):
    """独立的 FFmpeg 音频转码任务"""
    try:
        cmd =[
            FFMPEG_EXE, "-y", 
            "-i", temp_wav, 
            "-c:a", "libvorbis", 
            "-q:a", "4", 
            final_ogg
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception as e:
        logger.warning(f"音频转码异常 [{name}]: {e}")
    finally:
        if os.path.exists(temp_wav):
            try: os.remove(temp_wav)
            except: pass

def main():
    global total_bundles_to_dl
    print("=================================================================")
    print("    Twinkle Star Knights X 离线版资源自动更新工具 v1.8.3")
    print("=================================================================")
    print(f"[*] 资源存放路径: {os.path.abspath(OUTPUT_DIR)}")
    print(f"[*] 运行状态日志: update_log.txt\n")
    
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
                    except Exception: pass 
                elif f.endswith(".chapter.json") and f != "Master.chapter.json":
                    try:
                        os.remove(full_path)
                        cleaned_count += 1
                    except Exception: pass
                elif f.endswith(".temp.wav"):
                    try:
                        os.remove(full_path)
                    except Exception: pass
                    
    if cleaned_count > 0:
        print(f"[*] 启动自检: 已自动清理历史冲突及无用碎片 {cleaned_count} 项\n")

    print("[1/5] 正在连接服务器获取最新资源索引...")
    try:
        res = requests.get(CATALOG_URL, timeout=30)
        res.raise_for_status()
        catalog_data = res.text
    except Exception as e:
        print(f"[!] 网络异常，无法获取清单: {e}")
        os.system("pause")
        return

    print("[2/5] 正在解析并构建双轨合并资源树...")
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

    print("[3/5] 正在扫描本地文件差异 (智能跳过已下载内容)...")
    bundles_to_download = {}
    for url, files in target_bundles.items():
        missing_files = {}
        for norm_key, rel_path in files.items():
            full_path = os.path.join(OUTPUT_DIR, rel_path)
            
            check_path = full_path
            if os.path.splitext(check_path)[1].lower() not in['.png', '.jpg', '.jpeg']:
                png_path = os.path.splitext(check_path)[0] + '.png'
                if os.path.exists(png_path): continue 
                    
            if not os.path.exists(check_path) or check_path.endswith("Master.chapter.json"):
                missing_files[norm_key] = rel_path
                
        if missing_files:
            bundles_to_download[url] = missing_files

    total_bundles_to_dl = len(bundles_to_download)
    if total_bundles_to_dl == 0:
        print("\n[+] 校验完成，本地各项资源均已是最新版本！")
        os.system("pause")
        return

    print(f" -> 对比完成！本次需要更新或下载 {total_bundles_to_dl} 个资源包。")
    print(f"\n[4/5] 启动多线程资源下载与解析引擎...")
    logger.info(f"Update started. Targets: {total_bundles_to_dl}")
    
    extracted_total = 0
    # 下载解包阶段：网络 IO 密集型，保持 10 线程并发
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures =[executor.submit(process_bundle, url, files) for url, files in bundles_to_download.items()]
        for future in as_completed(futures):
            extracted_total += future.result()
            
    if audio_convert_queue:
        print(f"\n[5/5] 启动音频安全转码引擎，待处理音频: {len(audio_convert_queue)} 个")
        # 【核心修正】根据网友电脑的 CPU 核心数动态分配安全线程，防止 I/O 卡死
        # 最大不超过 16 线程，最少 2 线程
        safe_workers = min(16, max(2, (os.cpu_count() or 4) + 2))
        logger.info(f"分配转码线程数: {safe_workers}")
        
        converted_count = 0
        with ThreadPoolExecutor(max_workers=safe_workers) as audio_executor:
            futures =[audio_executor.submit(convert_audio_task, temp, final, name) for temp, final, name in audio_convert_queue]
            for future in as_completed(futures):
                converted_count += 1
                if converted_count % 100 == 0 or converted_count == len(audio_convert_queue):
                    print(f" -> 转码进度:[{converted_count}/{len(audio_convert_queue)}]")

    print(f"\n[+] 更新与转码任务圆满完成！本次共计新增/修复文件: {extracted_total} 个。")
    logger.info(f"Update finished. Files processed: {extracted_total}")
    os.system("pause")

if __name__ == "__main__":
    main()