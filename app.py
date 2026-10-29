import os,re,io
from datetime import datetime,timezone
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from flask import Flask,jsonify,request,render_template_string

app=Flask(__name__)
VERSION='4.5.0'
SOURCES={'Vergi Mevzuatı (GİB)':'https://gib.gov.tr/mevzuat/kanun/436','Türk Ticaret Kanunu':'https://www.mevzuat.gov.tr','SPK Mevzuatı':'https://spk.gov.tr','Türkiye Muhasebe Standartları':'https://www.kgk.gov.tr'}
HTML='''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mali Mevzuat AI 4.5.0</title><style>body{font-family:system-ui;background:#101827;color:#edf3ff;margin:0;padding:18px}main{max-width:800px;margin:auto}.panel{background:#20344e;padding:20px;border-radius:20px;margin:16px 0}select,textarea,button{font:inherit;box-sizing:border-box;width:100%;padding:13px;border-radius:10px;margin:10px 0}select,textarea{background:#101827;color:white;border:1px solid #64748b}button{background:#2788ec;border:0;color:white;font-weight:700}a{color:#9fd2ff}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit}details{margin-top:14px}.muted{color:#b7c7dc}</style></head><body><main><h1>Mali Mevzuat AI <small>4.4.0</small></h1><p class="muted">Resmî kaynak tarama ve tanılama</p><section class="panel"><label>Kaynak</label><select id="source">{% for name in sources %}<option>{{name}}</option>{% endfor %}</select><label>Soru veya aranacak ifade</label><textarea id="q" rows="4" placeholder="3065 sayılı KDV Kanunu'nun 29/3. maddesine göre KDV indirim süresi nedir?"></textarea><button id="go">Kaynağı Ara ve Yanıtla</button><p id="status" role="status"></p><div id="results"></div><details><summary>Kaynak tanılama bilgileri</summary><pre id="debug"></pre></details></section><section class="panel"><h2>Resmî kaynaklar</h2>{% for name,url in sources.items() %}<p><a href="{{url}}" target="_blank" rel="noopener noreferrer">{{name}}</a></p>{% endfor %}</section></main><script>document.getElementById('go').onclick=async()=>{const s=document.getElementById('status'),out=document.getElementById('results'),dbg=document.getElementById('debug');s.textContent='Kaynak taranıyor...';out.replaceChildren();dbg.textContent='';try{const p=new URLSearchParams({source:document.getElementById('source').value,q:document.getElementById('q').value});const r=await fetch('/api/search?'+p,{headers:{'Accept':'application/json'}});const raw=await r.text();let d;try{d=JSON.parse(raw)}catch(_){throw new Error('Sunucu JSON yerine HTML/metin döndürdü (HTTP '+r.status+'). Render Logs bölümünü kontrol edin.')}if(!r.ok)throw new Error(d.message||d.error||'HTTP '+r.status);s.textContent=d.message||'İşlem tamamlandı';const a=document.createElement('a');a.href=d.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='Resmî kaynak bağlantısını aç';out.append(a);for(const excerpt of d.excerpts||[]){const p=document.createElement('pre');p.textContent=excerpt;out.append(p)}dbg.textContent=JSON.stringify({checked_at:d.checked_at,http_status:d.http_status,content_type:d.content_type,content_length:d.content_length,final_url:d.final_url,detail:d.detail,detected_article:d.detected_article},null,2)}catch(e){s.textContent='İstek başarısız';dbg.textContent=String(e)}};</script></body></html>'''

def fetch_source(url):
    response=requests.get(url,timeout=(6,18),headers={'User-Agent':'Mozilla/5.0 (compatible; MaliMevzuatAI/4.5.0)','Accept':'text/html,application/pdf;q=0.9,*/*;q=0.5'},allow_redirects=True)
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

# Konu rehberi: sabit ve kaynak bağlantılı yönlendirmeler; canlı mevzuat taraması değildir.
# Parasal hadler yıl bazında değişebildiğinden otomatik doğrulanmadan rakam verilmez.
TOPIC_GUIDES = [
    {
        'terms': ('binek', 'otomobil', 'araç gider', 'arac gider', 'taşıt gider', 'tasit gider'),
        'title': 'Binek otomobil giderleri',
        'law': 'Gelir Vergisi Kanunu madde 40/1, 40/5 ve 40/7; KDV Kanunu madde 30/d; ilgili tebliğler',
        'explanation': 'İşletmeye ait binek otomobilin yakıt, bakım, sigorta ve benzeri genel giderlerinde, kapsam ve istisnalar saklı kalmak üzere, vergi matrahından indirim kısıtlaması uygulanır. Kira, ilk iktisap vergileri ve amortisman için ayrıca yıllık parasal sınırlar vardır. MTV ve KDV indirimi kendi mevzuatına göre değerlendirilir.',
        'example': 'Örnek (yalnızca genel gider): 10.000 TL KDV hariç uygun nitelikte bakım harcamasının %70’i 7.000 TL indirilebilir gider, %30’u 3.000 TL KKEG olarak izlenebilir. KDV tutarı ayrıca değerlendirilir.',
        'entry': 'Örnek hesap yaklaşımı: 770 Genel Yönetim Giderleri (indirilebilir kısım), 770 altında ayrı KKEG alt hesabı (indirilemeyen kısım), şartları varsa 191 İndirilecek KDV; karşılığında 320 Satıcılar veya 102 Bankalar. Kesin kayıt fatura ve işletmenin niteliğine bağlıdır.',
        'url': 'https://www.gib.gov.tr/vergi-konulari/2_isletme_ve_girisimci/18_binek_otomobillerde_gider_ve_amortismanlarin_vergi_matrahindan_indirimi/18',
    },
    {
        'terms': ('amortisman', 'itfa payı', 'itfa payi', 'sabit kıymet', 'sabit kiymet'),
        'title': 'Amortisman',
        'law': 'Vergi Usul Kanunu madde 313 ve devamı; ilgili amortisman listeleri',
        'explanation': 'Amortismana tabi iktisadi kıymetlerin maliyet bedelleri, ilgili mevzuatın öngördüğü süre ve oranlara göre giderleştirilir. Faydalı ömür ve oran, kıymetin niteliğine göre belirlenmelidir. Binek otomobillerde ayrıca gider kısıtlaması bulunabilir.',
        'example': 'Örnek: 100.000 TL maliyetli bir varlık için geçerli oran %20 ise, tam yıl normal amortisman örneği 20.000 TL’dir. Bu oran yalnızca örnektir; gerçek oran resmî listeden kontrol edilmelidir.',
        'entry': 'Örnek hesap yaklaşımı: ilgili gider hesabı (730/760/770) borç; 257 Birikmiş Amortismanlar alacak. Varlığın ilk kaydı, niteliğine göre 25x maddi duran varlık hesabında izlenir.',
        'url': 'https://www.gib.gov.tr/',
    },
    {
        'terms': ('kurumlar vergisi', 'kurum kazancı', 'kurum kazanci'),
        'title': 'Kurumlar vergisi',
        'law': '5520 sayılı Kurumlar Vergisi Kanunu; ilgili tebliğler',
        'explanation': 'Kurum kazancı, ticari bilanço kârından vergi mevzuatındaki ilave ve indirimler dikkate alınarak hesaplanır. Oranlar, istisnalar ve indirimler dönem ve mükellef türüne göre kontrol edilmelidir.',
        'example': 'Örnek: Ticari kâra KKEG eklenir, mevzuata uygun istisna ve indirimler düşülerek vergi matrahına ulaşılır. Burada güncel oran veya tutar otomatik doğrulanmamıştır.',
        'entry': 'Örnek hesap yaklaşımı: dönem vergi karşılığı için 691 Dönem Kârı Vergi ve Diğer Yasal Yükümlülük Karşılıkları / 370 Dönem Kârı Vergi ve Diğer Yasal Yükümlülük Karşılıkları; kesin kayıt hesaplamaya bağlıdır.',
        'url': 'https://www.gib.gov.tr/',
    },
    {
        'terms': ('gelir vergisi', 'stopaj', 'tevkifat', 'ücret vergisi', 'ucret vergisi'),
        'title': 'Gelir vergisi ve stopaj',
        'law': '193 sayılı Gelir Vergisi Kanunu; ilgili tebliğler',
        'explanation': 'Gelir vergisi ve stopaj yükümlülükleri, ödemenin türüne ve mükellefiyet durumuna göre değişir. Kesinti oranı, beyan süresi ve istisnalar işlem tarihinde resmî kaynaklardan kontrol edilmelidir.',
        'example': 'Örnek: Hizmet ödemelerinde önce ödemenin stopaja tabi olup olmadığı ve varsa doğru oranı belirlenir; oran burada varsayılmamıştır.',
        'entry': 'Örnek hesap yaklaşımı: ilgili gider hesabı borç; şartlarına göre 360 Ödenecek Vergi ve Fonlar ve 320 Satıcılar / 102 Bankalar alacak.',
        'url': 'https://www.gib.gov.tr/',
    },
    {
        'terms': ('kdv indir', 'indirilecek kdv', 'kdv hesap', 'katma değer vergisi', 'katma deger vergisi'),
        'title': 'KDV indirimi ve muhasebesi',
        'law': '3065 sayılı Katma Değer Vergisi Kanunu madde 29, 30 ve 34',
        'explanation': 'KDV indirimi için belgelendirme, kayıt dönemi, işlemin niteliği ve kanuni kısıtlamalar birlikte değerlendirilir. 29/3 kapsamındaki süre şartı ayrıca kontrol edilmelidir.',
        'example': 'Örnek: İndirimi mümkün 1.000 TL KDV içeren bir alış faturasında 191 İndirilecek KDV hesabı kullanılabilir; indirimi yasaklanan KDV için farklı işlem gerekir.',
        'entry': 'Örnek hesap yaklaşımı: ilgili gider/stok hesabı ve 191 İndirilecek KDV borç; 320 Satıcılar alacak. İşlemin niteliği kayıtları değiştirir.',
        'url': 'https://gib.gov.tr/mevzuat/kanun/436',
    },
]

def topic_answer(question):
    normalized = re.sub(r'\s+', ' ', (question or '').casefold()).strip()
    if not normalized:
        return None
    for guide in TOPIC_GUIDES:
        if any(term in normalized for term in guide['terms']):
            return {
                'message': 'Konu rehberi bulundu. Canlı mevzuat doğrulaması yapılmadı.',
                'source': 'Vergi Mevzuatı (GİB)',
                'url': guide['url'],
                'checked_at': datetime.now(timezone.utc).isoformat(),
                'topic': guide['title'],
                'verified_live': False,
                'excerpts': [
                    'MEVZUAT DAYANAĞI (yönlendirme): '+guide['law'],
                    'AÇIKLAMA (kanun metni değildir): '+guide['explanation'],
                    'ÖRNEK (temsili): '+guide['example'],
                    'MUHASEBE KAYDI (temsili): '+guide['entry'],
                    'UYARI: Bu rehber sabittir. Güncel oran, parasal had, yürürlük ve istisnaları resmî kaynaktan ayrıca doğrulayın.'
                ],
                'source_note': 'Sabit konu rehberi; canlı kaynak doğrulaması yapılmadı.'
            }
    return None

def extract_paragraph(section, paragraph):
    # PDF dipnotlarında aynı sayılar bulunabilir: sadece satır başındaki fıkra işaretini eşleştir.
    number = re.escape(str(int(paragraph)))
    match = re.search(r'(?m)^\s*'+number+r'\s*[.)]\s+(?=\S)', section)
    if not match:
        return None
    tail = section[match.end():]
    following = re.search(r'(?m)^\s*\d{1,2}\s*[.)]\s+(?=\S)', tail)
    finish = match.end()+following.start() if following else len(section)
    result = section[match.start():finish].strip()
    # Çok uzun dipnot/kesit durumunda tamamını kanun fıkrası gibi göstermeyelim.
    if len(result)>4500:
        return None
    return re.sub(r'\s+', ' ', result)

@app.get('/')
def index():return render_template_string(HTML,sources=SOURCES)
@app.get('/health')
def health():return jsonify(status='ok',version=VERSION)
@app.get('/api/search')
def search():
    name=request.args.get('source','Vergi Mevzuatı (GİB)');q=request.args.get('q','').strip()[:400]
    if name not in SOURCES:return jsonify(error='Geçersiz kaynak'),400
    url=SOURCES[name];checked=datetime.now(timezone.utc).isoformat();article=extract_article(q)
    if name == 'Vergi Mevzuatı (GİB)' and not article:
        topic = topic_answer(q)
        if topic:
            topic['version'] = VERSION
            topic['detected_article'] = None
            return jsonify(topic)
    result=dict(version=VERSION,source=name,url=url,checked_at=checked,detected_article=article,excerpts=[])
    try:
        # GİB can return a 24-character dynamic shell to server-side clients.
        # Use a separate official government-hosted PDF as fallback for KDV.
        fallback_used=False
        try:
            content,status,ctype,final=fetch_source(url)
            if len(content)<250:raise ValueError('GİB dinamik sayfa kısa içerik döndürdü')
        except (requests.RequestException,ValueError) as primary_error:
            if name!='Vergi Mevzuatı (GİB)' or not re.search(r'\b(?:3065|kdv|katma\s+değer)\b',q,re.I):raise
            fallback='https://www.yatirimadestek.gov.tr/pdf/assets/upload/dosyalar/3065-sayili-katma-deger-vergisi-kanunu.pdf'
            response=requests.get(fallback,timeout=(5,12),headers={'User-Agent':'Mozilla/5.0','Accept':'application/pdf'})
            response.raise_for_status()
            if not response.content.startswith(b'%PDF') or len(response.content)>12000000:raise ValueError('Resmî yedek PDF doğrulanamadı')
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(response.content))
            content='\n'.join(page.extract_text() or '' for page in reader.pages[:80])
            if len(content)<1000:raise ValueError('Resmî PDF metni çıkarılamadı')
            status=response.status_code;ctype='application/pdf';final=fallback;fallback_used=True
        result['url']=final
        result['fallback_used']=fallback_used
        result.update(http_status=status,content_type=ctype,content_length=len(content),final_url=final)
        if len(content)<250:raise ValueError('Kaynak metni çok kısa; sayfa dinamik olabilir')
        # Exact phrase matches only; never fabricate a legal provision.
        terms=[q] if q else []
        if article:
            n=article['article']
            # Extract bounded article section, not an unrelated occurrence in a footnote.
            pattern=rf'(?im)^\s*Madde\s+{re.escape(n)}\s*[–—-]'
            match=re.search(pattern,content)
            if match:
                next_match=re.search(r'(?im)^\s*(?:Madde\s+\d+\s*[–—-]|Geçici\s+Madde\s+\d+)',content[match.end():])
                end=match.end()+next_match.start() if next_match else min(len(content),match.start()+10000)
                section=content[match.start():end].strip()
                if len(section)>10000:section=section[:10000]+'…'
                result['excerpts']=[extract_paragraph(section,article['paragraph']) or section]
                result['message']='Resmî kaynaktan madde metni bulundu. Yürürlük ve değişiklikleri ayrıca doğrulayın.'
                result['source_note']='PDF yedek kaynağı kullanıldı' if fallback_used else 'GİB kaynağı kullanıldı'
                return jsonify(result)
        if article:terms.extend([f"MADDE {article['article']}",f"Madde {article['article']}"])
        if not terms:result['excerpts']=[content[:1500]]
        else:
            for term in terms:
                for match in list(re.finditer(re.escape(term),content,re.I))[:5]:
                    excerpt=content[max(0,match.start()-160):match.end()+650]
                    if excerpt not in result['excerpts']:result['excerpts'].append(excerpt)
                if result['excerpts']:break
        result['message']=(f"{len(result['excerpts'])} metin eşleşmesi bulundu. Resmî kaynak üzerinden doğrulayın." if result['excerpts'] else 'İlgili madde doğrulanamadı. Resmî kaynaktan kontrol edin.')
    except Exception as exc:
        app.logger.exception('Source retrieval failed')
        result.update(message='Resmî metin otomatik okunamadı; doğrulanmamış hüküm üretilmedi.',detail=f'{type(exc).__name__}: {exc}')
    return jsonify(result)

@app.errorhandler(404)
def not_found(exc):
    if request.path.startswith('/api/'):
        return jsonify(message='API adresi bulunamadı',version=VERSION),404
    return 'Sayfa bulunamadı',404

@app.errorhandler(405)
def method_not_allowed(exc):
    return jsonify(message='Bu API isteği desteklenmiyor',version=VERSION),405

@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    app.logger.exception('Unhandled application error')
    return jsonify(message='Sunucu işlemi tamamlayamadı. Render Logs bölümünü kontrol edin.',detail=type(exc).__name__,version=VERSION),500

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
