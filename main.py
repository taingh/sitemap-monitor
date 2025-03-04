import os
import json
import requests
import yaml
import gzip
import logging
from datetime import datetime, timedelta
from pathlib import Path
from bs4 import BeautifulSoup

# 设置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_config(config_path='config.yaml'):
    with open(config_path) as f:
        return yaml.safe_load(f)

def process_sitemap(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        content = response.content
        # 智能检测gzip格式
        if content[:2] == b'\x1f\x8b':  # gzip magic number
            content = gzip.decompress(content)

        if b'<urlset' in content:
            return parse_xml(content)
        else:
            return parse_txt(content.decode('utf-8'))
    except requests.RequestException as e:
        logging.error(f"Error processing {url}: {str(e)}")
        return []
    except Exception as e:
        logging.error(f"Unexpected error processing {url}: {str(e)}")
        return []

def parse_xml(content):
    urls = []
    soup = BeautifulSoup(content, 'xml')
    for loc in soup.find_all('loc'):
        url = loc.get_text().strip()
        if url:
            urls.append(url)
    return urls

def parse_txt(content):
    return [line.strip() for line in content.splitlines() if line.strip()]

def save_latest(site_name, new_urls):
    base_dir = Path('latest')
    
    # 创建latest目录（与日期目录同级）
    latest_dir = base_dir
    latest_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存latest.json
    latest_file = latest_dir / f'{site_name}.json'
    with open(latest_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_urls))

def save_diff(site_name, new_urls):
    base_dir = Path('diff')
        
    # 创建日期目录
    today = datetime.now().strftime('%Y%m%d')
    date_dir = base_dir / today
    date_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存当日新增数据
    file_path = date_dir / f'{site_name}.json'
    mode = 'a' if file_path.exists() else 'w'
    with open(file_path, mode, encoding='utf-8') as f:
        if mode == 'a':
            f.write('\n--------------------------------\n')  # 添加分隔符
        f.write('\n'.join(new_urls) + '\n')  # 确保每个URL后都有换行

def compare_data(site_name, new_urls):
    latest_file = Path('latest') / f'{site_name}.json'
    
    if not latest_file.exists():
        return []
        
    with open(latest_file) as f:
        last_urls = set(f.read().splitlines())
    
    return [url for url in new_urls if url not in last_urls]

def send_feishu_notification(new_urls, config, site_name):
    if not new_urls:
        return
    
    webhook_url = config['feishu']['webhook_url']
    secret = config['feishu'].get('secret')
    
    message = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"🎮 {site_name} 游戏上新通知"},
                "template": "green"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**今日新增 {len(new_urls)} 款游戏**\n\n" + "\n".join(f"• {url}" for url in new_urls[:10])
                    }
                }
            ]
        }
    }
    
    for attempt in range(3):  # 重试机制
        try:
            resp = requests.post(webhook_url, json=message)
            resp.raise_for_status()
            logging.info("飞书通知发送成功")
            return
        except requests.RequestException as e:
            logging.error(f"飞书通知发送失败: {str(e)}")
            if attempt < 2:
                logging.info("重试发送通知...")

def main(config_path='config.yaml'):
    config = load_config(config_path)
    
    for site in config['sites']:
        if not site['active']:
            continue
            
        logging.info(f"处理站点: {site['name']}")
        all_urls = []
        for sitemap_url in site['sitemap_urls']:
            urls = process_sitemap(sitemap_url)
            all_urls.extend(urls)
            
        # 去重处理
        unique_urls = list({url: None for url in all_urls}.keys())
        new_urls = compare_data(site['name'], unique_urls)
        
        save_latest(site['name'], unique_urls)
        if new_urls:
            save_diff(site['name'], new_urls)
            send_feishu_notification(new_urls, config, site['name'])
            
        # 清理旧数据
        cleanup_old_data(site['name'], config)

def cleanup_old_data(site_name, config):
    data_dir = Path('diff')
    if not data_dir.exists():
        return
        
    # 获取配置中的保留天数
    retention_days = config.get('retention_days', 7)
    cutoff = datetime.now() - timedelta(days=retention_days)
    
    # 遍历所有日期文件夹
    for date_dir in data_dir.glob('*'):
        if not date_dir.is_dir():
            continue
            
        try:
            # 解析文件夹名称为日期
            dir_date = datetime.strptime(date_dir.name, '%Y%m%d')
            if dir_date < cutoff:
                # 删除整个日期文件夹
                for f in date_dir.glob('*.json'):
                    f.unlink()
                date_dir.rmdir()
                logging.info(f"已删除过期文件夹: {date_dir.name}")
        except ValueError:
            # 忽略非日期格式的文件夹
            continue
        except Exception as e:
            logging.error(f"删除文件夹时出错: {str(e)}")

if __name__ == '__main__':
    main()
