import os,re,io
from datetime import datetime,timezone
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from flask import Flask,jsonify,request,render_template_string

app=Flask(__name__)
VERSION='4.2.1'
SOURCES={'Vergi Mevzuatı (GİB)':'https://gib.gov.tr/mevzuat/kanun/436','Türk Ticaret Kanunu':'https://www.mevzuat.gov.tr','SPK Mevzuatı':'https://spk.gov.tr','Türkiye Muhasebe Standartları':'https://www.kgk.gov.tr'}
HTML='''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mali Mevzuat AI 4.2.1</title><style>body{font-family:system-ui;background:#101827;color:#edf3ff;margin:0;padding:18px}main{max-width:800px;margin:auto}.panel{background:#20344e;padding:20px;border-radius:20px;margin:16px 0}select,textarea,button{font:inherit;box-sizing:border-box;width:100%;padding:13px;border-radius:10px;margin:10px 0}select,textarea{background:#101827;color:white;border:1px solid #64748b}button{background:#2788ec;border:0;color:white;font-weight:700}a{color:#9fd2ff}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit}details{margin-top:14px}.muted{color:#b7c7dc}</style></head><body><main><h1>Mali Mevzuat AI <small>4.2.1</small></h1><p class="muted">Resmî kaynak tarama ve tanılama</p><section class="panel"><label>Kaynak</label><select id="source">{% for name in sources %}<option>{{name}}</option>{% endfor %}</select><label>Soru veya aranacak ifade</label><textarea id="q" rows="4" placeholder="3065 sayılı KDV Kanunu'nun 29/3. maddesine göre KDV indirim süresi nedir?"></textarea><button id="go">Kaynağı Ara ve Yanıtla</button><p id="status" role="status"></p><div id="results"></div><details><summary>Kaynak tanılama bilgileri</summary><pre id="debug"></pre></details></section><section class="panel"><h2>Resmî kaynaklar</h2>{% for name,url in sources.items() %}<p><a href="{{url}}" target="_blank" rel="noopener noreferrer">{{name}}</a></p>{% endfor %}</section></main><script>document.getElementById('go').onclick=async()=>{const s=document.getElementById('status'),out=document.getElementById('results'),dbg=document.getElementById('debug');s.textContent='Kaynak taranıyor...';out.replaceChildren();dbg.textContent='';try{const p=new URLSearchParams({source:document.getElementById('source').value,q:document.getElementById('q').value});const r=await fetch('/api/search?'+p);const d=await r.json();s.textContent=d.message||'İşlem tamamlandı';const a=document.createElement('a');a.href=d.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='Resmî kaynak bağlantısını aç';out.append(a);for(const excerpt of d.excerpts||[]){const p=document.createElement('pre');p.textContent=excerpt;out.append(p)}dbg.textContent=JSON.stringify({checked_at:d.checked_at,http_status:d.http_status,content_type:d.content_type,content_length:d.content_length,final_url:d.final_url,detail:d.detail,detected_article:d.detected_article},null,2)}catch(e){s.textContent='İstek başarısız';dbg.textContent=String(e)}};</script></body></html>'''

def fetch_source(url):
    response=requests.get(url,timeout=(6,18),headers={'User-Agent':'Mozilla/5.0 (compatible; MaliMevzuatAI/4.2.1)','Accept':'text/html,application/pdf;q=0.9,*/*;q=0.5'},allow_redirects=True)
    response.raise_for_status()
    p=urlparse(response.url)
    allowed={urlparse(u).hostname for u in SOURCES.values()}
    if p.scheme!='https' or not any(p.hostname==h or p.hostname.endswith('.'+h) for h in allowed):raise ValueError('Beklenmeyen yönlendirme adresi')
    if len(response.content)>8_000_000:raise ValueError('Kaynak boyutu sınırı aşıldı')
    content_type=response.headers.get('Content-Type','').lower()
    if 'pdf' in content_type or response.content.startswith(b'%PDF'):
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(response.content))
        content='\n'.join(page.extract_text() or '' for page in reader.pages[:100])
    elif 'html' in content_type or response.text.lstrip().lower().startswith(('<!doctype','<html')):
        soup=BeautifulSoup(response.content,'html.parser')
        for tag in soup(['script','style','nav','footer','header']):tag.decompose()
        content=' '.join(soup.stripped_strings)
    else:raise ValueError('Desteklenmeyen içerik türü: '+content_type)
    return content,response.status_code,content_type,response.url

def extract_article(q):
    m=re.search(r'(?:madde(?:si|sine|sinin|de)?\s*|\b)(\d{1,3})\s*/\s*(\d{1,2})',q,re.I)
    return {'article':m.group(1),'paragraph':m.group(2)} if m else None

@app.get('/')
def index():return render_template_string(HTML,sources=SOURCES)
@app.get('/health')
def health():return jsonify(status='ok',version=VERSION)
@app.get('/api/search')
def search():
    name=request.args.get('source','Vergi Mevzuatı (GİB)');q=request.args.get('q','').strip()[:400]
    if name not in SOURCES:return jsonify(error='Geçersiz kaynak'),400
    url=SOURCES[name];checked=datetime.now(timezone.utc).isoformat();article=extract_article(q)
    result=dict(version=VERSION,source=name,url=url,checked_at=checked,detected_article=article,excerpts=[])
    try:
        content,status,ctype,final=fetch_source(url)
        result.update(http_status=status,content_type=ctype,content_length=len(content),final_url=final)
        if len(content)<250:raise ValueError('Kaynak metni çok kısa; sayfa dinamik olabilir')
        # Exact phrase matches only; never fabricate a legal provision.
        terms=[q] if q else []
        if article:terms.extend([f"MADDE {article['article']}",f"Madde {article['article']}"])
        if not terms:result['excerpts']=[content[:1500]]
        else:
            for term in terms:
                for match in list(re.finditer(re.escape(term),content,re.I))[:5]:
                    excerpt=content[max(0,match.start()-160):match.end()+650]
                    if excerpt not in result['excerpts']:result['excerpts'].append(excerpt)
                if result['excerpts']:break
        result['message']=(f"{len(result['excerpts'])} metin eşleşmesi bulundu. Resmî kaynak üzerinden doğrulayın." if result['excerpts'] else 'İlgili madde doğrulanamadı. Resmî kaynaktan kontrol edin.')
    except (requests.RequestException,ValueError,Exception) as exc:
        result.update(message='Resmî metin otomatik okunamadı; doğrulanmamış hüküm üretilmedi.',detail=f'{type(exc).__name__}: {exc}')
    return jsonify(result)

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
