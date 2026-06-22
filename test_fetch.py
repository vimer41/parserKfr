import requests
import re
import json

url = 'https://www.kufar.by/item/1073852561'
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
url = 'https://cre-api-v2.kufar.by/items-stats/1073852561'
r = requests.get(url, headers=headers)
print("Stats API 1 status:", r.status_code)
print(r.text[:200] if r.status_code==200 else '')

url2 = 'https://api.kufar.by/item-api/v1/items/1073852561/statistics'
r2 = requests.get(url2, headers=headers)
print("Stats API 2 status:", r2.status_code)
print(r2.text[:200] if r2.status_code==200 else '')
