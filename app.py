import os,re
from datetime import datetime,timezone
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup
from flask import Flask,jsonify,request,render_template_string

app=Flask(__name__);app.json.ensure_ascii=False
VERSION='4.2'
BASE='https://gib.gov.tr/mevzuat/kanun/436'
SOURCES={'Vergi Mevzuatı':BASE,'Türk Ticaret Kanunu':'https://www.mevzuat.gov.tr','SPK Mevzuatı':'https://spk.gov.tr','Türkiye Muhasebe Standartları':'https://www.kgk.gov.tr'}
HTML='''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mali Mevzuat AI {{version}}</title><style>body{background:#101827;color:#fff;font-family:system-ui;margin:0;padding:20px}main{max-width:760px;margin:auto}section{background:#1e3049;padding:20px;border-radius:15px;margin:16px 0}select,textarea,button{width:100%;box-sizing:border-box;padding:13px;border-radius:9px;font-size:16px;margin:8px 0}select,textarea{background:#101827;color:#fff;border:1px solid #65758b}textarea{min-height:95px}button{background:#2784ea;color:#fff;border:0}button:disabled{opacity:.6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.5}a{color:#91caff}small{color:#c0cddd}</style></head><body><main><h1>Mali Mevzuat AI {{version}}</h1><small>Resmî kaynak okunur; güncellik ve yürürlük ayrıca değerlendirilmelidir.</small><section><h2>Mevzuat Asistanı</h2><select id="cat">{% for c in sources %}<option>{{c}}</option>{% endfor %}</select><textarea id="q" placeholder="3065 sayılı KDV Kanunu 29/3 maddesine göre indirim süresi nedir?"></textarea><textarea id="manual" placeholder="İsteğe bağlı: Kaynak metnini elle yapıştır"></textarea><button id="go" onclick="ask()">Kaynağı Ara ve Yanıtla</button><pre id="answer"></pre><div id="link"></div><details><summary>Kaynak tanılama bilgileri</summary><pre id="diag"></pre></details></section><section><h2>Resmî kaynaklar</h2>{% for name,url in sources.items() %}<p><a href="{{url}}" target="_blank" rel="noopener noreferrer">{{name}}</a></p>{% endfor %}</section></main><script>async function ask(){let b=document.getElementById('go'),a=document.getElementById('answer'),d=document.getElementById('diag'),l=document.getElementById('link');b.disabled=true;a.textContent='Resmî kaynak aranıyor...';d.textContent='';l.replaceChildren();try{let r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:document.getElementById('cat').value,question:document.getElementById('q').value,manual_text:document.getElementById('manual').value})});let j=await r.json();a.textContent=j.answer||'Yanıt yok';d.textContent=JSON.stringify(j.diagnostics||{},null,2);if(j.source_url){let x=document.createElement('a');x.href=j.source_url;x.textContent='Kaynak bağlantısını aç';x.target='_blank';x.rel='noopener noreferrer';l.appendChild(x)}}catch(e){a.textContent='Bağlantı hatası: '+e.message}finally{b.disabled=false}}</script></body></html>'''

@app.get('/')
def home():return render_template_string(HTML,version=VERSION,sources=SOURCES)
@app.get('/health')
def health():return jsonify(status='ok',version=VERSION)

def article_number(q):
 if not re.search(r'\b(?:kdv|3065)\b|katma\s+değer',q,re.I):return None
 for pattern in [r'\bmadde\s*(\d{1,3})\b',r'(?<!\d)(\d{1,3})\s*/\s*\d+',r'(?<!\d)(\d{1,3})\s*\.\s*madde',r'(?<!\d)(\d{1,3})\s*(?:inci|ıncı|uncu|üncü)\s+madde']:
  m=re.search(pattern,q,re.I)
  if m:return int(m.group(1))
 return None

def fetch(url,diag):
 item={'url':url};diag['attempts'].append(item)
 try:
  r=requests.get(url,timeout=(6,22),headers={'User-Agent':'Mozilla/5.0 (compatible; MaliMevzuatAI/4.2)','Accept':'text/html,application/xhtml+xml'},allow_redirects=True)
  item.update(status=r.status_code,bytes=len(r.content),final_url=r.url,content_type=r.headers.get('Content-Type',''))
  r.raise_for_status()
  if len(r.content)>7_000_000:item['error']='too_large';return None,None
  if urlparse(r.url).hostname not in ('gib.gov.tr','www.gib.gov.tr'):item['error']='unexpected_host';return None,None
  soup=BeautifulSoup(r.content,'html.parser')
  for el in soup(['script','style','nav','footer','header']):el.decompose()
  text=re.sub(r'\s+',' ',soup.get_text(' ',strip=True))
  item['visible_characters']=len(text)
  item['has_article_29_heading']=bool(re.search(r'\bMadde\s+29\s+Vergi\s+İndirimi\b',text,re.I))
  return soup,text
 except requests.RequestException as e:item['error']=type(e).__name__;return None,None

def extract(text,num):
 if not text:return None
 # Require the target heading and stop at the next ordinary article heading.
 start_pat=re.compile(r'\bMadde\s+'+str(num)+r'\s+(?!\d)([A-ZÇĞİÖŞÜa-zçğıöşü])',re.I)
 end_pat=re.compile(r'\bMadde\s+'+str(num+1)+r'\s+(?!\d)[A-ZÇĞİÖŞÜa-zçğıöşü]',re.I)
 for m in start_pat.finditer(text):
  tail=text[m.start():];n=end_pat.search(tail)
  if not n:continue
  section=tail[:n.start()].strip()
  if 180<=len(section)<=35000 and not section.lower().startswith('geçici madde'):
   return section
 return None

def detail_links(soup,num):
 if not soup:return []
 links=[]
 for a in soup.select('a[href]'):
  href=a.get('href','');label=re.sub(r'\s+',' ',a.get_text(' ',strip=True))
  if '/madde/' not in href:continue
  if re.search(r'\b(?:Madde\s*)?'+str(num)+r'\b',label,re.I) and not re.search(r'\bGeçici\b',label,re.I):
   url=urljoin(BASE,href)
   if urlparse(url).hostname in ('gib.gov.tr','www.gib.gov.tr') and url not in links:links.append(url)
 return links[:8]

def verify_detail(text,num):
 return bool(text and re.search(r'\bMadde\s+'+str(num)+r'\s+[A-Za-zÇĞİÖŞÜçğıöşü]',text,re.I) and re.search(r'Kanun\s+Numarası\s+3065\b',text,re.I) and re.search(r'KATMA\s+DEĞER\s+VERGİSİ',text,re.I))

def ai_answer(q,source,kind):
 key=os.getenv('GEMINI_API_KEY','').strip()
 if not key:return None,'GEMINI_API_KEY tanımlı değil.'
 model=os.getenv('GEMINI_MODEL','gemini-2.5-flash').strip()
 if not re.fullmatch(r'[A-Za-z0-9_.-]+',model):return None,'Geçersiz model adı.'
 prompt=('Türkçe mali mevzuat asistanısın. Yalnızca sağlanan metinden yanıtla. Madde ile dipnotlardaki eski hükümleri karıştırma. '
 'Kanunun güncelliğinin ve yürürlük durumunun ayrıca teyit edilmesi gerektiğini belirt. Kaynakta cevap yoksa açıkça söyle. '
 f'KAYNAK TÜRÜ: {kind}\nMETİN:\n{source[:20000]}\nSORU: {q}')
 try:
  r=requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',headers={'x-goog-api-key':key},json={'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'temperature':0.1}},timeout=(8,55))
  if not r.ok:return None,f'Gemini HTTP {r.status_code}'
  j=r.json();answer='\n'.join(p.get('text','') for c in j.get('candidates',[]) for p in c.get('content',{}).get('parts',[]) if p.get('text'))
  return answer or None,None
 except requests.RequestException as e:return None,type(e).__name__

@app.post('/api/ask')
def ask():
 data=request.get_json(silent=True)
 if not isinstance(data,dict):return jsonify(answer='Geçersiz JSON.'),400
 q=data.get('question','');manual=data.get('manual_text','');cat=data.get('category','Vergi Mevzuatı')
 if not isinstance(q,str) or not isinstance(manual,str) or cat not in SOURCES or not q.strip() or len(q)>4000 or len(manual)>25000:return jsonify(answer='Geçersiz giriş.'),400
 diag={'version':VERSION,'checked_at_utc':datetime.now(timezone.utc).isoformat(),'attempts':[]}
 num=article_number(q) if cat=='Vergi Mevzuatı' else None
 text=None;url=None;kind='none';verified=False
 if manual.strip():text=manual.strip();kind='user_supplied_unverified';diag['result']='manual'
 elif num:
  soup,body=fetch(BASE,diag)
  if soup:
   links=detail_links(soup,num);diag['candidate_detail_links']=links
   for link in links:
    _,detail=fetch(link,diag)
    if verify_detail(detail,num):
     text=detail;url=link;kind='official_detail';verified=True;break
   if not text:
    section=extract(body,num)
    if section:
     text=section;url=BASE;kind='official_law_excerpt';verified=True
   diag['base_visible_characters']=len(body or '')
  diag['result']='official_text_found' if text else 'not_found'
 if not text:return jsonify(answer='Resmî madde metni bu sunucu üzerinden çıkarılamadı. Tanılama bilgilerini inceleyin. Doğrulanmamış kanun hükmü üretilmedi.',source_url=BASE if num else None,verified_source=False,diagnostics=diag)
 answer,error=ai_answer(q,text,kind)
 if error:
  if verified:return jsonify(answer='Resmî kaynak metni bulundu, fakat Gemini yanıt veremedi ('+error+').\n\nKaynak metni:\n'+text[:6000],source_url=url,verified_source=verified,source_type=kind,diagnostics=diag)
  return jsonify(answer='Kaynak kullanıcı tarafından sağlandı ve doğrulanmadı. Gemini hatası: '+error,diagnostics=diag),503
 return jsonify(answer=(answer or 'Yanıt üretilemedi.')+'\n\nKaynak türü: '+kind+'\nNot: Kaynağın erişilebilirliği kontrol edildi; güncel yürürlük durumu ayrıca teyit edilmelidir.',source_url=url,verified_source=verified,source_type=kind,diagnostics=diag)

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
