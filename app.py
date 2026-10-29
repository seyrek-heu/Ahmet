import os, re, logging
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, render_template_string

app=Flask(__name__)
app.json.ensure_ascii=False
VERSION='3.8'
LAW='https://gib.gov.tr/mevzuat/kanun/436'
GUIDANCE='https://cdn.gib.gov.tr/api/gibportal-file/file/getFileResources?objectKey=arsiv%2Ffileadmin%2Fuser_upload%2FTebligler%2FKDV%2Fkdv_genteb.htm'
SOURCES={'Vergi Mevzuatı':[('GİB KDV Kanunu',LAW),('GİB KDV Genel Uygulama Tebliği',GUIDANCE)],'Türk Ticaret Kanunu':[('Mevzuat Bilgi Sistemi','https://www.mevzuat.gov.tr')],'SPK Mevzuatı':[('SPK','https://spk.gov.tr')],'Türkiye Muhasebe Standartları':[('KGK','https://www.kgk.gov.tr')]}
HTML='''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mali Mevzuat AI {{version}}</title><style>body{font-family:system-ui;background:#101827;color:#fff;padding:20px;margin:0}main{max-width:750px;margin:auto}section{background:#1e3049;padding:20px;border-radius:16px;margin:16px 0}select,textarea,button{box-sizing:border-box;width:100%;padding:13px;border-radius:9px;font-size:16px;margin:9px 0}select,textarea{background:#101827;color:#fff;border:1px solid #62758e}textarea{min-height:110px}button{background:#2784ea;color:white;border:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.5}a{color:#8ec7ff}small{color:#bbc9db}</style></head><body><main><h1>Mali Mevzuat AI {{version}}</h1><small>Vergi · TTK · SPK · TMS | Kaynak türü açıkça belirtilir</small><section><h2>Mevzuat Asistanı</h2><select id="cat">{% for cat in sources %}<option>{{cat}}</option>{% endfor %}</select><textarea id="q" placeholder="Örnek: KDV Kanunu 29/3 indirim süresi nedir?"></textarea><textarea id="manual" placeholder="İsteğe bağlı: Resmî metni elle yapıştır"></textarea><button id="go" onclick="ask()">Kaynağı Ara ve Yanıtla</button><pre id="answer"></pre><div id="link"></div><details><summary>Kaynak tanılama bilgileri</summary><pre id="diag"></pre></details></section><section><h2>Resmî kaynaklar</h2>{% for category, links in sources.items() %}<h3>{{category}}</h3>{% for name,url in links %}<p><a href="{{url}}" target="_blank" rel="noopener noreferrer">{{name}}</a></p>{% endfor %}{% endfor %}</section></main><script>async function ask(){let b=document.getElementById('go'),a=document.getElementById('answer'),d=document.getElementById('diag'),l=document.getElementById('link');b.disabled=true;a.textContent='Resmî kaynaklar inceleniyor...';d.textContent='';l.replaceChildren();try{let r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:document.getElementById('cat').value,question:document.getElementById('q').value,manual_text:document.getElementById('manual').value})});let j=await r.json();a.textContent=j.answer||'Yanıt yok';d.textContent=JSON.stringify(j.diagnostics||{},null,2);if(j.source_url){let x=document.createElement('a');x.href=j.source_url;x.target='_blank';x.rel='noopener noreferrer';x.textContent='Kaynak bağlantısını aç';l.appendChild(x)}}catch(e){a.textContent='Bağlantı hatası: '+e.message}finally{b.disabled=false}}</script></body></html>'''

@app.get('/')
def home():return render_template_string(HTML,sources=SOURCES,version=VERSION)
@app.get('/health')
def health():return jsonify(status='ok',version=VERSION)

def article_number(q):
 if not any(t in q.casefold() for t in ('kdv','3065','katma değer')):return None
 m=re.search(r'(?<!\d)(29|30)(?:\s*/\s*\d+)?(?!\d)',q)
 return int(m.group(1)) if m else None

def get_page(url,diag):
 e={'url':url};diag['attempts'].append(e)
 try:
  r=requests.get(url,timeout=(5,17),headers={'User-Agent':'Mozilla/5.0 (compatible; MaliMevzuatAI/3.8)','Accept':'text/html,application/xhtml+xml'},allow_redirects=True)
  e.update(status=r.status_code,raw_bytes=len(r.content),content_type=r.headers.get('content-type',''),final_url=r.url)
  r.raise_for_status()
  if len(r.content)>7_000_000: e['result']='too_large';return None
  soup=BeautifulSoup(r.content,'html.parser')
  for tag in soup(['script','style','nav','header','footer']):tag.decompose()
  text=re.sub(r'\s+',' ',soup.get_text(' ',strip=True))
  e['visible_characters']=len(text)
  return text
 except requests.RequestException as ex:e['result']=type(ex).__name__;return None

def extract_law(text,num):
 if not text:return None
 # Exclude temporary/transitional articles and table-of-contents hits.
 pat=re.compile(r'(?<!\w)(?:Madde)\s*'+str(num)+r'\s*[-–—.:)]?',re.I)
 for m in pat.finditer(text):
  tail=text[m.end():]
  n=re.search(r'(?<!\w)Madde\s*'+str(num+1)+r'\s*[-–—.:)]?',tail,re.I)
  if not n:continue
  result=text[m.start():m.end()+n.start()]
  if len(result)<350 or len(result)>30000:continue
  if num==29 and not ('takvim yılını takip eden' in result.casefold() and 'indir' in result.casefold()):continue
  if num==30 and 'indirilemez' not in result.casefold():continue
  return result
 return None

def guidance_extract(text,question):
 if not text:return None
 # The official guidance is not the law. Only return a short, explicitly identified passage.
 terms=('takvim yılını takip eden','takvim yılı aşılmamak','indirim hakkının kullanılması')
 matches=[]
 low=text.casefold()
 for term in terms:
  pos=low.find(term)
  if pos>=0:matches.append(pos)
 if not matches:return None
 p=min(matches)
 return text[max(0,p-850):min(len(text),p+1100)]

@app.post('/api/ask')
def ask():
 data=request.get_json(silent=True) or {}
 q=str(data.get('question','')).strip();cat=str(data.get('category','Vergi Mevzuatı'))
 manual=str(data.get('manual_text','')).strip()
 if not q or len(q)>4000 or cat not in SOURCES or len(manual)>25000:return jsonify(answer='Geçerli soru ve kategori girin (metin en fazla 25.000 karakter).'),400
 diag={'version':VERSION,'attempts':[]};num=article_number(q) if cat=='Vergi Mevzuatı' else None
 text=None;source=None;kind='none'
 if manual:
  text=manual;kind='user_supplied';diag['result']='user_supplied_unverified'
 elif num:
  law=get_page(LAW,diag)
  text=extract_law(law,num)
  if text:source=LAW;kind='official_law_html';diag['result']='official_law_text_extracted'
  else:
   guide=get_page(GUIDANCE,diag)
   if num==29:
    text=guidance_extract(guide,q)
    if text:source=GUIDANCE;kind='official_guidance_not_law';diag['result']='official_guidance_excerpt'
 if num and not text:
  diag['result']='not_found'
  return jsonify(answer='RESMÎ METİN DOĞRULANAMADI\n\nGİB kanun sayfasından madde metni çıkarılamadı; alternatif GİB tebliğinde de soruya uygun açıklama bulunamadı. Tahmini kanun hükmü üretilmedi.',source_url=LAW,verified_source=False,source_type='none',diagnostics=diag)
 key=os.environ.get('GEMINI_API_KEY','').strip();model=os.environ.get('GEMINI_MODEL','gemini-3.1-flash-lite').strip()
 if not key:return jsonify(answer='GEMINI_API_KEY tanımlanmamış.',diagnostics=diag),503
 if not re.fullmatch(r'[A-Za-z0-9_.-]+',model):return jsonify(answer='Geçersiz model ayarı.',diagnostics=diag),500
 labels={'official_law_html':'GİB kanun sayfasından çıkarılan madde metni; güncelliği ayrıca teyit edilmedi.','official_guidance_not_law':'GİB KDV Genel Uygulama Tebliği açıklaması. BU METİN KANUNUN BİREBİR METNİ DEĞİLDİR.','user_supplied':'Kullanıcının yapıştırdığı metin. Resmî kaynaktan doğrulanmadı.','none':'Canlı resmî metin elde edilmedi.'}
 prompt=f'Sen Türkiye mali mevzuat asistanısın. Türkçe kısa ve doğru cevap ver. Kaynak türü: {labels[kind]} Kanun hükmü ile tebliğ açıklamasını karıştırma. Kaynak kanun değilse madde metninin doğrulandığını söyleme. Metinde bulunmayan tarih, fıkra ve hüküm uydurma.\nKAYNAK METİN:\n{(text or "Yok")[:15000]}\nSORU: {q}'
 try:
  r=requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',headers={'x-goog-api-key':key,'Content-Type':'application/json'},json={'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'temperature':0.1}},timeout=(8,50))
  if not r.ok:return jsonify(answer='Gemini API hatası (HTTP '+str(r.status_code)+').',diagnostics=diag),502
  payload=r.json();answer='\n'.join(p.get('text','') for c in payload.get('candidates',[]) for p in c.get('content',{}).get('parts',[]) if p.get('text'))
  return jsonify(answer=(answer or 'Yanıt alınamadı.')+'\n\nKaynak kontrolü: '+labels[kind],source_url=source,source_type=kind,verified_source=(kind=='official_law_html'),diagnostics=diag)
 except requests.RequestException:return jsonify(answer='Gemini bağlantısı zaman aşımına uğradı.',diagnostics=diag),504

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT','10000')))
