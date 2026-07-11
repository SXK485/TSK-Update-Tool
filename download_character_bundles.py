"""
下载指定角色的所有 bundle 文件
用法: python download_character_bundles.py 1114001
"""
import sys
import os
import requests
import UnityPy
import json
from AddressablesTools import parse

CATALOG_BUNDLE_URL = "https://d3mya90gbacu0m.cloudfront.net/prod/StreamingAssets/aa/catalog.bundle"
RUNTIME_PATH = "https://d3mya90gbacu0m.cloudfront.net/prod/StreamingAssets/aa"

def download_character_bundles(character_id):
    import time
    output_dir = f"character_{character_id}_bundles"
    
    # 如果目录存在且被占用，使用带时间戳的新目录
    if os.path.exists(output_dir):
        try:
            # 尝试删除旧目录
            import shutil
            shutil.rmtree(output_dir)
        except:
            # 删除失败（被占用），使用新目录名
            timestamp = int(time.time())
            output_dir = f"character_{character_id}_bundles_{timestamp}"
            print(f"注意: 原目录被占用，将下载到新目录: {output_dir}\n")
    
    os.makedirs(output_dir, exist_ok=True)
    
    print("=" * 80)
    print(f"下载角色 {character_id} 的所有 bundle 文件")
    print("=" * 80)
    
    print("\n[1] 下载并解析 catalog.bundle...")
    res = requests.get(CATALOG_BUNDLE_URL, timeout=60)
    env = UnityPy.load(res.content)
    
    catalog_json = None
    for obj in env.objects:
        if obj.type.name == "TextAsset":
            data = obj.read()
            raw_data = getattr(data, "m_Script", getattr(data, "script", None))
            if raw_data is None:
                continue
            if isinstance(raw_data, str):
                json_text = raw_data
            elif isinstance(raw_data, bytes):
                json_text = raw_data.decode('utf-8', errors='ignore')
            else:
                continue
            json_text = json_text.strip('\x00')
            try:
                catalog_json = json.loads(json_text)
                print(f"✓ 成功解析资源索引")
                break
            except:
                continue
    
    if not catalog_json:
        print("✗ 无法解析 catalog")
        return
    
    catalog = parse(json.dumps(catalog_json))
    
    print(f"\n[2] 查找角色 {character_id} 相关的资源...")
    
    # 收集所有相关的 bundle URL
    bundle_info = {}  # {bundle_url: [resource_keys]}
    
    for key, locs in catalog.Resources.items():
        if not isinstance(key, str):
            continue
        
        # 检查是否包含角色 ID
        if character_id in key:
            print(f"  找到资源: {key}")
            
            # 获取依赖的 bundle
            dep_key = locs[0].DependencyKey
            if dep_key in catalog.Resources:
                original_url = catalog.Resources[dep_key][0].InternalId
                bundle_url = original_url.replace(
                    "{UnityEngine.AddressableAssets.Addressables.RuntimePath}",
                    RUNTIME_PATH
                )
                
                if bundle_url not in bundle_info:
                    bundle_info[bundle_url] = []
                bundle_info[bundle_url].append(key)
    
    if not bundle_info:
        print(f"\n✗ 未找到角色 {character_id} 的资源")
        return
    
    print(f"\n[3] 共找到 {len(bundle_info)} 个 bundle，开始下载...")
    
    # 统计各类型的数量
    category_stats = {}
    
    for i, (bundle_url, resources) in enumerate(bundle_info.items(), 1):
        bundle_filename = os.path.basename(bundle_url)
        
        # 确定资源类型（更精确的分类逻辑）
        category = "其他"
        resource_types = []
        
        for res in resources:
            res_lower = res.lower()
            
            # 按优先级判断主要类型
            if "spine" in res_lower or "/characters/" in res_lower.replace("\\", "/"):
                if "spine" in res_lower:
                    category = "Spine动画"
                    resource_types.append("Spine动画")
                elif "/characters/" in res_lower.replace("\\", "/"):
                    category = "角色Spine"
                    resource_types.append("角色Spine")
            elif "still" in res_lower or "st_" in res_lower:
                category = "CG图片"
                resource_types.append("CG")
            elif "voice" in res_lower or "cv_" in res_lower:
                category = "语音"
                resource_types.append("语音")
            elif "scenario" in res_lower or "adv" in res_lower:
                category = "剧情文本"
                resource_types.append("剧情")
            elif "thumb" in res_lower or "icon" in res_lower:
                category = "头像图标"
                resource_types.append("头像")
            elif "gacha" in res_lower:
                category = "抽卡动画"
                resource_types.append("抽卡")
            elif "cutin" in res_lower:
                category = "立绘"
                resource_types.append("立绘")
        
        # 如果没有明确分类，尝试从资源名推断
        if category == "其他" and resources:
            first_res = resources[0].lower()
            if "chara" in first_res or "character" in first_res:
                category = "角色相关"
        
        # 创建分类子目录
        category_dir = os.path.join(output_dir, category)
        os.makedirs(category_dir, exist_ok=True)
        
        save_path = os.path.join(category_dir, bundle_filename)
        
        # 统计
        if category not in category_stats:
            category_stats[category] = 0
        category_stats[category] += 1
        
        types_str = ", ".join(set(resource_types)) if resource_types else "未分类"
        
        print(f"\n[{i}/{len(bundle_info)}] {bundle_filename}")
        print(f"  分类: {category}")
        print(f"  包含资源: {len(resources)} 个")
        for res in resources[:3]:  # 只显示前3个
            print(f"    - {res}")
        if len(resources) > 3:
            print(f"    ... 还有 {len(resources) - 3} 个")
        
        try:
            print(f"  下载中...")
            bundle_res = requests.get(bundle_url, timeout=60)
            bundle_res.raise_for_status()
            
            with open(save_path, 'wb') as f:
                f.write(bundle_res.content)
            
            print(f"  ✓ 已保存到: {category}/{bundle_filename} ({len(bundle_res.content)} bytes)")
        except Exception as e:
            print(f"  ✗ 下载失败: {e}")
    
    print("\n" + "=" * 80)
    print("下载统计:")
    print("-" * 80)
    for cat, count in sorted(category_stats.items()):
        print(f"  {cat}: {count} 个 bundle")
    print("-" * 80)
    
    print("\n" + "=" * 80)
    print(f"完成！所有 bundle 已保存到: {os.path.abspath(output_dir)}")
    print("=" * 80)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python download_character_bundles.py <角色ID>")
        print("例如: python download_character_bundles.py 1114001")
        sys.exit(1)
    
    character_id = sys.argv[1]
    download_character_bundles(character_id)
