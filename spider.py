import os
import csv
import json
import time
import re  
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# 线程安全的计数器
avatar_lock = Lock()
avatar_success = 0
avatar_fail = 0
avatar_skip = 0

# 19 个中文表头定义
headers_list_zh = [
    "角色ID", "星级", "头像", "角色名称", "名字(日文读音)", "属性", "阵营", "所属团队", 
    "类型", "攻击类型", "生命值(HP)", "攻击力(ATK)", "EX", "EX上升", "最小CT", "最大CT", "暴击率(%)", "实装日期", "获取方式"
]

def get_true_img_src(img_tag):
    """获取真实的图片 URL（处理懒加载）"""
    # 尝试多个可能的属性
    for attr in ['data-src', 'data-original', 'data-lazy-src', 'src']:
        src = img_tag.get(attr)
        if src and not src.startswith('data:'):  # 排除 base64 占位符
            return src
    return None

def download_avatar_from_wiki(char_id, img_url, base_url, image_dir, session, id_suffix=1):
    """从 Wiki 下载单个角色头像"""
    global avatar_success, avatar_fail, avatar_skip
    
    # 如果有重复ID，添加后缀
    if id_suffix > 1:
        output_filename = f"{char_id}_{id_suffix}.png"
    else:
        output_filename = f"{char_id}.png"
    
    output_path = os.path.join(image_dir, output_filename)
    
    # 如果文件已存在，跳过
    if os.path.exists(output_path):
        with avatar_lock:
            avatar_skip += 1
        return f"角色头像/{output_filename}"
    
    if not img_url:
        with avatar_lock:
            avatar_fail += 1
        return ""
    
    # 构造完整 URL
    full_url = urljoin(base_url, img_url)
    
    # 检查是否是占位符图片（data: 开头或包含 lazy）
    if full_url.startswith('data:') or 'lazy' in full_url:
        with avatar_lock:
            avatar_fail += 1
        return ""
    
    try:
        img_res = session.get(full_url, timeout=10)
        if img_res.status_code == 200 and len(img_res.content) > 1000:  # 确保不是占位符
            with open(output_path, 'wb') as f:
                f.write(img_res.content)
            with avatar_lock:
                avatar_success += 1
            return f"角色头像/{output_filename}"
        else:
            with avatar_lock:
                avatar_fail += 1
            return ""
    except Exception:
        with avatar_lock:
            avatar_fail += 1
        return ""

def clean_cell_text(cell):
    """
    智能清洗单元格文本。
    1. 使用 \\n 分割子标签（如 <br>），保留换行。
    2. 逐行执行首尾 strip()，去除多余空白和缩进（例如大欲の女帝后一行的前置缩进）。
    3. 重新用 \\n 拼接，过滤掉空行。
    """
    if not cell:
        return ""
    raw_text = cell.get_text(separator="\n")
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    return "\n".join(lines)

def get_image_ext(img_url):
    """提取图片后缀，优先解析URL查询参数以防被.php截断"""
    parsed_url = urlparse(img_url)
    ext = os.path.splitext(parsed_url.path)[1]
    if ext.lower() in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
        return ext.lower()
    
    query_params = parse_qs(parsed_url.query)
    for param_name in ["src", "file", "ref"]:
        val = query_params.get(param_name)
        if val:
            potential_ext = os.path.splitext(val[0])[1]
            if potential_ext.lower() in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
                return potential_ext.lower()
    return ".png"

def get_true_img_src(img_tag):
    """
    处理懒加载图片的专属函数。
    依次检查各种常见的懒加载标签，并排除 Base64 和空像素占位图。
    如果都没有，尝试从父级 <a> 标签的 href 中提取，最后才退回到 src 属性。
    """
    if not img_tag:
        return None
    
    lazy_attrs = ["data-src", "data-original", "data-lazy-src", "data-lazy", "data-original-src"]
    for attr in lazy_attrs:
        val = img_tag.get(attr)
        if val and not any(p in val.lower() for p in ["blank.gif", "pixel.gif", "clear.gif", "spacer.gif", "1x1", "base64", "data:"]):
            return val
            
    parent_a = img_tag.find_parent("a")
    if parent_a:
        href = parent_a.get("href")
        if href:
            href_lower = href.lower()
            if any(ext in href_lower for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]):
                return href
            parsed_href = urlparse(href)
            query_params = parse_qs(parsed_href.query)
            for param in ["src", "file", "ref"]:
                val_list = query_params.get(param)
                if val_list:
                    val_lower = val_list[0].lower()
                    if any(ext in val_lower for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]):
                        return href
                        
    src = img_tag.get("src")
    if src:
        src_lower = src.lower()
        if not any(p in src_lower for p in ["blank.gif", "pixel.gif", "clear.gif", "spacer.gif", "1x1", "base64", "data:"]):
            return src
            
    return None

def parse_date(date_str):
    """解析日期字符串，统一转换为 YYYY-MM-DD 格式，用于安全排序"""
    if not date_str:
        return "0000-00-00"
    clean_str = "".join([c for c in date_str if c.isdigit() or c in ["/", "-", "."]])
    clean_str = clean_str.replace("/", "-").replace(".", "-")
    match = re.search(r'\d{4}-\d{2}-\d{2}', clean_str)
    if match:
        return match.group(0)
    return "0000-00-00"

def find_column_indices(header_cells):
    """动态建立列索引，防止日后 Wiki 增删列导致解析错位"""
    mapping = {}
    def find_index(keywords, exact=False):
        for idx, cell in enumerate(header_cells):
            cell_clean = cell.replace("\n", "").replace(" ", "").strip()
            if exact:
                if any(kw == cell_clean for kw in keywords):
                    return idx
            else:
                if any(kw in cell_clean for kw in keywords):
                    return idx
        return None

    mapping["攻撃タイプ"] = find_index(["攻撃タイプ"])
    mapping["EX上昇"] = find_index(["EX上昇"])
    mapping["最小CT"] = find_index(["最小CT", "最小.CT", "最小"])
    mapping["最大CT"] = find_index(["最大CT", "最大.CT", "最大"])
    mapping["クリ(%)"] = find_index(["クリ", "クリ(%)"])
    mapping["No"] = find_index(["No"], exact=True) or find_index(["No"])
    mapping["★"] = find_index(["☆", "★", "星"])
    mapping["画像"] = find_index(["画像"])
    mapping["キャラ名"] = find_index(["キャラ名"])
    mapping["名前(ヨミ)"] = find_index(["名前(ヨミ)", "名前"])
    mapping["属性"] = find_index(["属性"], exact=True)
    mapping["陣営"] = find_index(["陣営"], exact=True)
    mapping["所属"] = find_index(["所属"], exact=True)
    mapping["HP"] = find_index(["HP"], exact=True)
    mapping["ATK"] = find_index(["ATK"], exact=True)
    mapping["実装日"] = find_index(["実装日"])
    mapping["入手方法"] = find_index(["入手方法"])
    
    for idx, cell in enumerate(header_cells):
        cell_clean = cell.replace("\n", "").replace(" ", "").strip()
        if cell_clean == "タイプ":
            mapping["タイプ"] = idx
        elif cell_clean == "EX":
            mapping["EX"] = idx
            
    return mapping

def scrape_wiki():
    url = "https://twinklestarknights.wikiru.jp/?%E3%82%AD%E3%83%A3%E3%83%A9%E3%82%AF%E3%82%BF%E3%83%BC%E4%B8%80%E8%A6%A7"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://twinklestarknights.wikiru.jp/"
    }
    
    image_dir = "角色头像"
    os.makedirs(image_dir, exist_ok=True)
    
    print("正在请求 Wiki 页面...")
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"页面请求失败: {e}")
        return

    soup = BeautifulSoup(response.content, "html.parser")
    tables = soup.find_all("table")
    all_rows_data = []
    
    for table_idx, table in enumerate(tables):
        rows = table.find_all("tr")
        if not rows:
            continue
            
        first_row_cells = [th.get_text() for th in rows[0].find_all(["th", "td"])]
        first_row_text = "".join(first_row_cells)
        if "No" not in first_row_text or "画像" not in first_row_text:
            continue
            
        print(f"正在解析匹配的表格 #{table_idx + 1}...")
        mapping = find_column_indices(first_row_cells)
        if "No" not in mapping or "画像" not in mapping:
            continue
            
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 10:
                continue
            
            if mapping["No"] >= len(cells):
                continue
                
            raw_no = cells[mapping["No"]].get_text(strip=True)
            no_digits = "".join(filter(str.isdigit, raw_no))
            if not no_digits:
                continue
                
            # 在 ID 最前面加 1
            modified_no = f"1{no_digits}"
            
            # 使用新逻辑 clean_cell_text，完美保留多行结构并清洗空白
            def get_val(key):
                idx = mapping.get(key)
                if idx is not None and idx < len(cells):
                    return clean_cell_text(cells[idx])
                return ""
            
            # 提取图片 URL（暂不下载）
            img_url = None
            img_idx = mapping.get("画像")
            if img_idx is not None and img_idx < len(cells):
                img_tag = cells[img_idx].find("img")
                if img_tag:
                    img_url = get_true_img_src(img_tag)
            
            row_data = {
                "角色ID": modified_no,
                "星级": get_val("★"),
                "头像": "",  # 稍后批量下载
                "角色名称": get_val("キャラ名"),
                "名字(日文读音)": get_val("名前(ヨミ)"),
                "属性": get_val("属性"),
                "阵营": get_val("陣営"),
                "所属团队": get_val("所属"),
                "类型": get_val("タイプ"),
                "攻击类型": get_val("攻撃タイプ"),
                "生命值(HP)": get_val("HP"),
                "攻击力(ATK)": get_val("ATK"),
                "EX": get_val("EX"),
                "EX上升": get_val("EX上昇"),
                "最小CT": get_val("最小CT"),
                "最大CT": get_val("最大CT"),
                "暴击率(%)": get_val("クリ(%)"),
                "实装日期": get_val("実装日"),
                "获取方式": get_val("入手方法"),
                "_img_url": img_url  # 临时存储图片URL
            }
            
            # 检查ID是否重复，如果重复则给新的记录编号
            duplicate_count = sum(1 for existing in all_rows_data if existing.get('角色ID') == modified_no)
            if duplicate_count > 0:
                # 有重复，给当前记录添加后缀
                row_data['_id_suffix'] = duplicate_count + 1
            else:
                row_data['_id_suffix'] = 1
            
            all_rows_data.append(row_data)

    if not all_rows_data:
        print("未抓取到有效数据。")
        return
        
    all_rows_data.sort(key=lambda x: (parse_date(x.get("实装日期", "")), x.get("角色ID", "")), reverse=True)
    print(f"数据已按 [实装日期] 降序排序完毕。")
    print()
    
    # 批量下载头像（从 Wiki，使用并发）
    print("=" * 60)
    print("开始从 Wiki 批量下载角色头像...")
    print("=" * 60)
    
    # 创建 session（复用连接）
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://twinklestarknights.wikiru.jp/"
    })
    
    # 准备下载任务（包含重复ID的处理）
    download_tasks = []
    for item in all_rows_data:
        char_id = item.get('角色ID')
        img_url = item.get('_img_url')
        id_suffix = item.get('_id_suffix', 1)
        if char_id and img_url:
            download_tasks.append((char_id, img_url, id_suffix))
    
    print(f"共 {len(download_tasks)} 个角色头像待下载")
    
    # 使用 15 线程并发下载（提高速度）
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {}
        for char_id, img_url, id_suffix in download_tasks:
            future = executor.submit(download_avatar_from_wiki, char_id, img_url, url, image_dir, session, id_suffix)
            futures[future] = (char_id, id_suffix)
        
        for idx, future in enumerate(as_completed(futures), 1):
            char_id, id_suffix = futures[future]
            avatar_path = future.result()
            # 更新对应的角色头像路径
            if avatar_path:
                for item in all_rows_data:
                    if item['角色ID'] == char_id and item.get('_id_suffix') == id_suffix:
                        item['头像'] = avatar_path
                        break
            if idx % 20 == 0:
                print(f"进度: {idx}/{len(download_tasks)}")
    
    # 清理所有临时字段
    for item in all_rows_data:
        item.pop('_img_url', None)
        item.pop('_id_suffix', None)
    
    print()
    print(f"头像下载完成: 成功 {avatar_success}, 失败 {avatar_fail}, 跳过 {avatar_skip}")
    print()

    # 格式 1: CSV 文件 (CSV标准能够完美支持双引号括起来的多行数据)
    try:
        with open("角色数据.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=headers_list_zh)
            writer.writeheader()
            for r_data in all_rows_data:
                writer.writerow(r_data)
        print("CSV 文件保存成功: 角色数据.csv")
    except Exception as e:
        print(f"CSV 保存异常: {e}")

    # 格式 2: JSON 文件
    try:
        with open("角色数据.json", "w", encoding="utf-8") as f:
            json.dump(all_rows_data, f, ensure_ascii=False, indent=4)
        print("JSON 文件保存成功: 角色数据.json")
    except Exception as e:
        print(f"JSON 保存异常: {e}")

    # 格式 3: 交互式本地检索网页 HTML
    generate_html(all_rows_data)

def generate_html(data):
    """生成具有搜索、过滤、动态升降序，且【完美支持多行名称换行显示】功能的本地单页 HTML"""
    json_data_str = json.dumps(data, ensure_ascii=False)
    
    html_template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Twinkle Star Knights 角色快速检索工具</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f3f4f6; margin: 0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { text-align: center; color: #1f2937; margin-bottom: 20px; }
        .search-container { margin-bottom: 20px; display: flex; gap: 10px; flex-wrap: wrap; }
        #search-input { flex: 1; min-width: 200px; padding: 10px; font-size: 16px; border: 1px solid #d1d5db; border-radius: 6px; }
        select { padding: 10px; font-size: 16px; border: 1px solid #d1d5db; border-radius: 6px; background-color: white; cursor: pointer; }
        #sort-by { border-color: #3b82f6; background-color: #eff6ff; font-weight: 500; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
        .card { background: white; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); padding: 15px; display: flex; flex-direction: column; border: 1px solid #e5e7eb; transition: transform 0.15s; }
        .card:hover { transform: translateY(-3px); box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); }
        .card-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
        .avatar { width: 64px; height: 64px; border-radius: 8px; object-fit: cover; border: 1px solid #e5e7eb; background: #f9fafb; }
        .info { flex: 1; min-width: 0; }
        
        /* 核心改进：支持 white-space: pre-line 渲染多行文本 */
        .chara-name { font-weight: bold; font-size: 16px; color: #111827; white-space: pre-line; line-height: 1.3; word-break: break-all; }
        .chara-yomi { font-size: 11px; color: #6b7280; margin-top: 4px; white-space: pre-line; line-height: 1.2; word-break: break-all; }
        
        .id-badge { display: inline-block; background-color: #e0f2fe; color: #0369a1; padding: 2px 6px; border-radius: 4px; font-size: 12px; font-family: monospace; font-weight: bold; margin-top: 6px; cursor: pointer; transition: background 0.2s; }
        .id-badge:hover { background-color: #bae6fd; }
        .id-badge::after { content: " 📋"; font-size: 10px; }
        .badge-container { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
        .badge { font-size: 11px; padding: 2px 8px; border-radius: 12px; font-weight: 500; }
        .badge-rarity { background-color: #fef3c7; color: #d97706; }
        .badge-attr { background-color: #f3e8ff; color: #7e22ce; }
        .badge-type { background-color: #ecfdf5; color: #047857; }
        .details { font-size: 12px; color: #4b5563; display: grid; grid-template-columns: 1fr 1fr; gap: 4px; border-top: 1px solid #f3f4f6; padding-top: 8px; margin-top: auto; }
        .copied-toast { position: fixed; bottom: 20px; right: 20px; background-color: #10b981; color: white; padding: 10px 20px; border-radius: 6px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); display: none; z-index: 100; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Twinkle Star Knights 角色快速检索</h1>
        <div class="search-container">
            <input type="text" id="search-input" placeholder="输入 角色ID、中文名称、片假名读音进行检索...">
            
            <select id="sort-by">
                <option value="date-desc">🗓️ 实装日期：最新 → 最早 (降序)</option>
                <option value="date-asc">🗓️ 实装日期：最早 → 最新 (升序)</option>
                <option value="id-desc">🆔 角色ID：从大 → 从小 (降序)</option>
                <option value="id-asc">🆔 角色ID：从小 → 从大 (升序)</option>
            </select>

            <select id="rarity-filter">
                <option value="">所有星级</option>
                <option value="1">1星</option>
                <option value="2">2星</option>
                <option value="3">3星</option>
            </select>
            <select id="attribute-filter">
                <option value="">所有属性</option>
            </select>
            <select id="type-filter">
                <option value="">所有类型</option>
            </select>
        </div>
        <div class="grid" id="chara-grid"></div>
    </div>
    <div id="toast" class="copied-toast">ID 已成功复制到剪贴板！</div>
    
    <script>
        const characters = DATA_PLACEHOLDER;
        
        const attrs = [...new Set(characters.map(c => c["属性"]).filter(Boolean))];
        const types = [...new Set(characters.map(c => c["类型"]).filter(Boolean))];
        
        const attrFilter = document.getElementById("attribute-filter");
        attrs.forEach(a => {
            const opt = document.createElement("option"); opt.value = a; opt.textContent = a;
            attrFilter.appendChild(opt);
        });
        
        const typeFilter = document.getElementById("type-filter");
        types.forEach(t => {
            const opt = document.createElement("option"); opt.value = t; opt.textContent = t;
            typeFilter.appendChild(opt);
        });

        const grid = document.getElementById("chara-grid");
        const searchInput = document.getElementById("search-input");
        const rarityFilter = document.getElementById("rarity-filter");
        const sortBySelect = document.getElementById("sort-by");
        
        function render(filtered) {
            grid.innerHTML = "";
            filtered.forEach(c => {
                const card = document.createElement("div");
                card.className = "card";
                card.innerHTML = `
                    <div class="card-header">
                        <img class="avatar" src="${c["头像"] || ''}" alt="${c["角色名称"]}" onerror="this.src='https://placehold.co/64x64?text=?';this.onerror=null;">
                        <div class="info">
                            <div class="chara-name">${c["角色名称"]}</div>
                            <div class="chara-yomi">${c["名字(日文读音)"] || ''}</div>
                            <div class="id-badge" onclick="copyText('${c["角色ID"]}')">${c["角色ID"]}</div>
                        </div>
                    </div>
                    <div class="badge-container">
                        <span class="badge badge-rarity">★${c["星级"]}</span>
                        ${c["属性"] ? `<span class="badge badge-attr">${c["属性"]}</span>` : ''}
                        ${c["类型"] ? `<span class="badge badge-type">${c["类型"]}</span>` : ''}
                    </div>
                    <div class="details">
                        <div><b>生命值:</b> ${c["生命值(HP)"] || '-'}</div>
                        <div><b>攻击力:</b> ${c["攻击力(ATK)"] || '-'}</div>
                        <div><b>阵营:</b> ${c["阵营"] || '-'}</div>
                        <div><b>所属团队:</b> ${c["所属团队"] || '-'}</div>
                        <div><b>最小CT:</b> ${c["最小CT"] || '-'}</div>
                        <div><b>最大CT:</b> ${c["最大CT"] || '-'}</div>
                    </div>
                `;
                grid.appendChild(card);
            });
        }
        
        function sortData(list) {
            const sortBy = sortBySelect.value;
            return list.sort((a, b) => {
                if (sortBy.startsWith("date")) {
                    const dateA = a["实装日期"] || "0000-00-00";
                    const dateB = b["实装日期"] || "0000-00-00";
                    if (dateA !== dateB) {
                        return sortBy === "date-desc" 
                            ? dateB.localeCompare(dateA) 
                            : dateA.localeCompare(dateB);
                    }
                }
                const idA = a["角色ID"] || "";
                const idB = b["角色ID"] || "";
                return sortBy.endsWith("desc") 
                    ? idB.localeCompare(idA) 
                    : idA.localeCompare(idB);
            });
        }
        
        function filterData() {
            const query = searchInput.value.toLowerCase();
            const selectedRarity = rarityFilter.value;
            const selectedAttr = attrFilter.value;
            const selectedType = typeFilter.value;
            
            let filtered = characters.filter(c => {
                const matchQuery = !query || 
                    c["角色ID"].includes(query) || 
                    c["角色名称"].toLowerCase().includes(query) || 
                    (c["名字(日文读音)"] && c["名字(日文读音)"].toLowerCase().includes(query));
                
                const matchRarity = !selectedRarity || String(c["星级"]) === selectedRarity;
                const matchAttr = !selectedAttr || c["属性"] === selectedAttr;
                const matchType = !selectedType || c["类型"] === selectedType;
                
                return matchQuery && matchRarity && matchAttr && matchType;
            });
            
            filtered = sortData(filtered);
            render(filtered);
        }
        
        function copyText(text) {
            navigator.clipboard.writeText(text).then(() => {
                const toast = document.getElementById("toast");
                toast.style.display = "block";
                setTimeout(() => { toast.style.display = "none"; }, 1200);
            });
        }
        
        searchInput.addEventListener("input", filterData);
        rarityFilter.addEventListener("change", filterData);
        attrFilter.addEventListener("change", filterData);
        typeFilter.addEventListener("change", filterData);
        sortBySelect.addEventListener("change", filterData);
        
        filterData();
    </script>
</body>
</html>"""
    
    html_content = html_template.replace("DATA_PLACEHOLDER", json_data_str)
    try:
        with open("角色检索.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print("本地交互式检索网页保存成功: 角色检索.html")
    except Exception as e:
        print(f"HTML 页面保存异常: {e}")

if __name__ == "__main__":
    print("=" * 60)
    print("Twinkle Star Knights Wiki 角色数据爬取工具")
    print("=" * 60)
    print()
    
    scrape_wiki()
    
    print()
    print("=" * 60)
    print("数据抓取完成！")
    print("生成的文件：")
    print("  - 角色数据.csv （Excel可打开）")
    print("  - 角色数据.json （开发者使用）")
    print("  - 角色检索.html （在浏览器中打开可搜索）")
    print("  - 角色头像/ （角色头像图片文件夹）")
    print("=" * 60)
    input("\n按回车键退出...")