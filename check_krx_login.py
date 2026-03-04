import requests
import re
from bs4 import BeautifulSoup

def find_login():
    s = requests.Session()
    h = {"User-Agent": "Mozilla/5.0"}
    
    r = s.get("https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd", headers=h)
    soup = BeautifulSoup(r.text, 'html.parser')
    
    scripts = [t.get('src') for t in soup.find_all('script') if t.get('src') and t.get('src').startswith('/')]
    
    r2 = s.get("https://data.krx.co.kr/contents/MDC/MAIN/main/MF_MDC_LOGIN.cmd", headers=h)
    print("MF_MDC_LOGIN length:", len(r2.text))
    
    content = ""
    for src in scripts:
        try:
            content += s.get("https://data.krx.co.kr" + src, headers=h).text + "\n"
        except:
            pass
            
    endpoints = set(re.findall(r'"(/comm/[^"]*?\.cmd)"', content))
    endpoints.update(re.findall(r'"(/contents/[^"]*?\.cmd)"', content))
    print("Relevant endpoints:", [e for e in endpoints if 'login' in e.lower() or 'mbr' in e.lower()])
    
    # also search in r2 (the login page) just in case
    login_scripts = [t.get('src') for t in BeautifulSoup(r2.text, 'html.parser').find_all('script') if t.get('src') and t.get('src').startswith('/')]
    for src in login_scripts:
        if src not in scripts:
            try:
                content += s.get("https://data.krx.co.kr" + src, headers=h).text + "\n"
            except: pass

    # find ajax
    chunks = re.finditer(r'\$\.ajax[\s\S]{1,500}\}', content)
    for m in chunks:
        ajax = m.group(0)
        if 'login' in ajax.lower() or 'mbrId' in ajax:
            print("Ajax:", ajax)

if __name__ == "__main__":
    find_login()
