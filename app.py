import os,re,logging
from datetime import datetime,timezone
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from flask import Flask,jsonify,request,render_template_string

app=Flask(__name__);app.json.ensure_ascii=False
VERSION='4.0'
BASE='https://gib.gov.tr/mevzuat/kanun/436'
SOURCES={'Vergi Mevzuatı':BASE,'Türk Ticaret Kanunu':'https://www.mevzuat.gov.tr','SPK Mevzuatı':'https://spk.gov.tr','Türkiye Muhasebe Standartları':'https://www.kgk.gov.tr'}
HTML='''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mali Mevzuat AI {{version}}</title><style>body{background:#101827;color:white;font-family:system-ui;margin:0;padding:20px}main{max-width:760px;margin:auto}section{background:#1e3049;padding:20px;border-radius:15px;margin:16px 0}select,textarea,button{width:100%;box-sizing:border-box;padding:13px;border-radius:9px;font-size:16px;margin:8px 0}select,textarea{background:#101827;color:white;border:1px solid #65758b}textarea{min-height:95px}button{background:#2784ea;color:white;border:0}button:disabled{opacity:.6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.5}a{color:#91caff}small{color:#c0cddd}</style></head><body><main><h1>Mali Mevzuat AI {{version}}</h1><small>Resmî kaynak bulunmadan kanun hükmü doğrulanmış sayılmaz.</small><section><h2>Mevzuat Asistanı</h2><select id="cat">{% for c in sources %}<option>{{c}}</option>{% endfor %}</select><textarea id="q" placeholder="Örn: KDV Kanunu 29/3 indirim süresi nedir?"></textarea><textarea id="manual" placeholder="İsteğe bağlı: Kaynak metnini elle yapıştır"></textarea><button id="go" onclick="ask()">Kaynağı Ara ve Yanıtla</button><pre id="answer"></pre><div id="link"></div><details><summary>Kaynak tanılama bilgileri</summary><pre id="diag"></pre></details></section><section><h2>Resmî kaynaklar</h2>{% for name,url in sources.items() %}<p><a href="{{url}}" target="_blank" rel="noopener">{{name}}</a></p>{% endfor %}</section></main><script>async function ask(){let b=document.getElementById('go'),a=document.getElementById('answer'),d=document.getElementById('diag'),l=document.getElementById('link');b.disabled=true;a.textContent='Resmî kaynak aranıyor...';d.textContent='';l.replaceChildren();try{let r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:document.getElementById('cat').value,question:document.getElementById('q').value,manual_text:document.getElementById('manual').value})});let j=await r.json();a.textContent=j.answer||'Yanıt yok';d.textContent=JSON.stringify(j.diagnostics||{},null,2);if(j.source_url){let x=document.createElement('a');x.href=j.source_url;x.textContent='Resmî kaynak bağlantısını aç';x.target='_blank';x.rel='noopener noreferrer';l.appendChild(x)}}catch(e){a.textContent='Bağlantı hatası: '+e.message}finally{b.disabled=false}}</script></body></html>'''
@app.get('/')
def home():return render_template_string(HTML,version=VERSION,sources=SOURCES)
@app.get('/health')
def health():return jsonify(status='ok',version=VERSION)

def requested_article(q):
 if not re.search(r'\b(?:kdv|3065)\b|katma\s+değer',q,re.I):return None
 m=re.search(r'(?<!\d)(?:madde\s*)?(\d{1,3})(?:\s*/\s*\d+)?\s*(?:\.?\s*(?:madde(?:si|sinin|ye|de)?|inci\s+madde))?',q,re.I)
 # Avoid mistaking 3065 for article number; prioritize explicit article syntax
 explicit=re.search(r'(?:madde\s*(\d{1,3})|(?<!\d)(\d{1,3})\s*/\s*\d+|(?<!\d)(\d{1,3})\s*(?:inci|ıncı|uncu|üncü)\s+madde)',q,re.I)
 if explicit:return int(next(v for v in explicit.groups() if v))
 return None

def fetch(url,diag):
 item={'url':url};diag['attempts'].append(item)
 try:
  r=requests.get(url,timeout=(5,18),headers={'User-Agent':'Mozilla/5.0','Accept':'text/html'},allow_redirects=True)
  item.update(status=r.status_code,bytes=len(r.content),final_url=r.url)
  r.raise_for_status()
  if len(r.content)>5_000_000:return None,None
  soup=BeautifulSoup(r.content,'html.parser')
  for el in soup(['script','style','nav','footer','header']):el.decompose()
  return soup,re.sub(r'\s+',' ',soup.get_text(' ',strip=True))
 except requests.RequestException as ex:item['error']=type(ex).__name__;return None,None

def extract(text,num):
 if not text:return None
 # Use the last substantial article occurrence, not an index or historical note.
 pat=re.compile(r'(?<!\w)Madde\s*'+str(num)+r'\b\s*[-–—.:)]?',re.I)
 hits=list(pat.finditer(text))
 for m in hits:
  nxt=re.search(r'(?<!\w)Madde\s*'+str(num+1)+r'\b',text[m.end():],re.I)
  section=text[m.start():m.end()+(nxt.start() if nxt else min(9000,len(text)-m.end()))]
  if 100<len(section)<30000:return section
 return None

def find_article_link(soup,num):
 if not soup:return None
 for a in soup.select('a[href]'):
  href=a.get('href','');label=a.get_text(' ',strip=True)
  if '/madde/' in href and re.search(r'\b(?:madde\s*)?'+str(num)+r'\b',label,re.I):return urljoin(BASE,href)
 return None

def verify_article(text,num):
 if not text:return False
 # Article detail page must identify the article and statute, not just mention it.
 return bool(re.search(r'\bMadde\s*'+str(num)+r'\b',text,re.I) and ('KATMA DEĞER VERGİSİ' in text.upper() or len(text)>250))

def ai_answer(q,text,source_kind):
 key=os.getenv('GEMINI_API_KEY','').strip()
 if not key:return None,'GEMINI_API_KEY Render ortam değişkeni tanımlı değil.'
 model=os.getenv('GEMINI_MODEL','gemini-2.5-flash').strip()
 if not re.fullmatch(r'[\w.-]+',model):return None,'Geçersiz GEMINI_MODEL.'
 prompt=('Türkçe mali mevzuat asistanısın. Yalnızca verilen kaynak metnine dayan. Kaynak metninde olmayan hükmü uydurma. '
         'Kaynak türünü belirt. Kullanıcının yapıştırdığı metni resmî doğrulanmış diye sunma. '
         'Önce net yanıt, sonra dayanak ve varsa sınırlamaları yaz. Kaynak bir kanun maddesiyse dipnotlarda geçen eski metinleri yürürlükteki metinle karıştırma.\n'
         f'KAYNAK TÜRÜ: {source_kind}\nMETİN:\n{text[:18000]}\nSORU: {q}')
 try:
  r=requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',headers={'x-goog-api-key':key},json={'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'temperature':0.1}},timeout=(8,45))
  if not r.ok:return None,f'Gemini API HTTP {r.status_code}. Model veya API anahtarını kontrol edin.'
  result=r.json();out='\n'.join(p.get('text','') for c in result.get('candidates',[]) for p in c.get('content',{}).get('parts',[]) if p.get('text'))
  return out or None,None
 except requests.RequestException:return None,'Gemini bağlantı hatası.'

@app.post('/api/ask')
def ask():
 data=request.get_json(silent=True) or {};q=str(data.get('question','')).strip();cat=data.get('category','Vergi Mevzuatı');manual=str(data.get('manual_text','')).strip()
 if not q or len(q)>4000 or len(manual)>25000 or cat not in SOURCES:return jsonify(answer='Geçersiz giriş.'),400
 diag={'version':VERSION,'attempts':[],'checked_at_utc':datetime.now(timezone.utc).isoformat()}
 num=requested_article(q) if cat=='Vergi Mevzuatı' else None
 text=None;url=None;kind='none';verified=False
 if manual:text=manual;kind='user_supplied';diag['result']='user_supplied_unverified'
 elif num:
  soup,body=fetch(BASE,diag)
  if soup:
   link=find_article_link(soup,num)
   if link:
    _,detail=fetch(link,diag)
    if verify_article(detail,num):
     text=detail;url=link;kind='official_article_page';verified=True
   if not text:
    section=extract(body,num)
    if section and len(section)>150:
     text=section;url=BASE;kind='official_law_page_excerpt';verified=True
  diag['result']='official_text_found' if text else 'not_found'
 if not text:
  return jsonify(answer='İlgili resmî kanun maddesi otomatik doğrulanamadı. Doğrulanmamış hüküm üretilmedi. KDV dışındaki mevzuat için şimdilik resmî metni elle ekleyebilirsiniz.',source_url=BASE if num else None,verified_source=False,diagnostics=diag)
 answer,error=ai_answer(q,text,kind)
 if error:
  # Allow a usable, explicitly identified official excerpt even when Gemini is unavailable.
  if verified:return jsonify(answer='Resmî kaynak bulundu ancak yapay zekâ yanıtı alınamadı: '+error+'\n\nKaynak metni (ilk 4.000 karakter):\n'+text[:4000],source_url=url,verified_source=True,source_type=kind,diagnostics=diag)
  return jsonify(answer=error,diagnostics=diag),503
 return jsonify(answer=answer+'\n\nKaynak türü: '+kind+'\nNot: Sayfa erişimi doğrulandı; mevzuatın son değişiklik ve yürürlük durumu ayrıca teyit edilmelidir.',source_url=url,verified_source=verified,source_type=kind,diagnostics=diag)

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
