import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
SOURCES = {
    'Vergi Mevzuatı': [('Gelir İdaresi Başkanlığı', 'https://gib.gov.tr/mevzuat'), ('Mevzuat Bilgi Sistemi', 'https://www.mevzuat.gov.tr')],
    'Türk Ticaret Kanunu': [('Mevzuat Bilgi Sistemi', 'https://www.mevzuat.gov.tr')],
    'SPK Mevzuatı': [('Sermaye Piyasası Kurulu', 'https://spk.gov.tr')],
    'Türkiye Muhasebe Standartları': [('Kamu Gözetimi Kurumu', 'https://www.kgk.gov.tr')],
}
KDV_OFFICIAL = 'https://gib.gov.tr/mevzuat/kanun/436'
HTML = '''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mali Mevzuat AI 3.2</title><style>body{font-family:system-ui;background:#101827;color:#f7f9ff;margin:0;padding:20px}main{max-width:750px;margin:auto}section{background:#1e3049;padding:22px;border-radius:18px;margin:18px 0}h1{font-size:29px}select,textarea,button{box-sizing:border-box;width:100%;padding:14px;border-radius:10px;font-size:16px;margin:9px 0}select,textarea{background:#101827;color:white;border:1px solid #62758e}textarea{min-height:125px}button{background:#2784ea;color:white;border:0;cursor:pointer}button:disabled{opacity:.6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.55}a{color:#8ec7ff}small{color:#bdc9d8}.muted{color:#bdc9d8}</style></head><body><main><h1>Mali Mevzuat AI 3.2</h1><small>Vergi · TTK · SPK · TMS | Kaynak doğrulama</small><section><h2>Mevzuat Asistanı</h2><select id="category">{% for category in sources %}<option>{{category}}</option>{% endfor %}</select><textarea id="question" placeholder="Örnek: 3065 sayılı KDV Kanunu 29. madde nedir?"></textarea><button id="send" onclick="ask()">Resmî Kaynakta Ara ve Yanıtla</button><pre id="answer" aria-live="polite"></pre><div id="links"></div><button onclick="navigator.clipboard.writeText(document.getElementById('answer').textContent)">Yanıtı Kopyala</button></section><section><h2>Resmî Kaynaklar</h2>{% for category,links in sources.items() %}<h3>{{category}}</h3>{% for name,url in links %}<p><a href="{{url}}" target="_blank" rel="noopener noreferrer">{{name}}</a></p>{% endfor %}{% endfor %}</section></main><script>async function ask(){const b=document.getElementById('send'),a=document.getElementById('answer'),l=document.getElementById('links');b.disabled=true;a.textContent='Resmî kaynak kontrol ediliyor...';l.replaceChildren();try{const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:document.getElementById('category').value,question:document.getElementById('question').value})});const j=await r.json();a.textContent=j.answer||'Yanıt alınamadı.';if(j.source_url){const p=document.createElement('p'),link=document.createElement('a');link.href=j.source_url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='İncelenen resmî kaynak: '+j.source_url;p.appendChild(link);l.appendChild(p)}}catch(e){a.textContent='Bağlantı hatası. Tekrar deneyin.'}finally{b.disabled=false}}</script></body></html>'''

@app.get('/')
def home():
    return render_template_string(HTML, sources=SOURCES)


def find_kdv_article(question):
    """Only a narrow, known official GIB law URL is supported. Never claim wider coverage."""
    q = question.lower()
    if not ('3065' in q or 'kdv' in q or 'katma değer' in q):
        return None
    match = re.search(r'(?:madde\s*|\b)(29|30)(?:\s*\.?\s*madde|\s*\.?\b)', q)
    if not match:
        return None
    return int(match.group(1))


def fetch_official_article(article):
    try:
        r = requests.get(KDV_OFFICIAL, timeout=(5, 12), headers={'User-Agent': 'MaliMevzuatAI/3.2 (public-law-research)'})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        for node in soup(['script', 'style', 'nav', 'footer', 'header']):
            node.decompose()
        content = soup.get_text(' ', strip=True)
        content = re.sub(r'\s+', ' ', content)
        # Only accept article text when the heading AND a substantial article body are present.
        pattern = rf'\bMadde\s+{article}\s+(?:Vergi\s+[İIıi]ndirimi|[İIıi]ndirilemeyecek\s+Katma\s+Değer\s+Vergisi)\b'
        start = re.search(pattern, content, re.IGNORECASE)
        if not start:
            return None
        following = content[start.start():]
        end = re.search(rf'\bMadde\s+{article + 1}\b', following[start.end()-start.start():], re.IGNORECASE)
        offset = start.end() - start.start()
        extracted = following[:offset + end.start()] if end else following[:12000]
        if len(extracted) < 300:
            return None
        # Fail closed: do not treat navigation/summary text as a verified provision.
        if article == 29 and not re.search(r'takvim\s+yılını\s+takip\s+eden\s+takvim\s+yılı', extracted, re.IGNORECASE):
            return None
        if article == 30 and 'indirilemez' not in extracted.lower():
            return None
        return extracted[:14000]
    except requests.RequestException:
        app.logger.exception('GIB source fetch failed')
        return None

@app.post('/api/ask')
def ask():
    data = request.get_json(silent=True) or {}
    question = str(data.get('question', '')).strip()
    category = str(data.get('category', 'Vergi Mevzuatı'))
    if not question or len(question) > 4000 or category not in SOURCES:
        return jsonify(answer='Geçerli bir kategori seçip 1–4000 karakterlik soru yazın.'), 400
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        return jsonify(answer='GEMINI_API_KEY tanımlanmamış.'), 503
    model = os.environ.get('GEMINI_MODEL', 'gemini-3.1-flash-lite').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', model):
        return jsonify(answer='Geçersiz model ayarı.'), 500

    article = find_kdv_article(question) if category == 'Vergi Mevzuatı' else None
    official_text = fetch_official_article(article) if article else None
    # Strict source policy: for article-specific questions, never ask the model
    # to reconstruct a legal provision when the official text is missing.
    if article and not official_text:
        return jsonify(
            answer=('RESMÎ METİN DOĞRULANAMADI\n\n'
                    'GİB sayfasından ilgili kanun maddesinin metni güvenilir biçimde alınamadı. '
                    'Bu nedenle kanun maddesinin içeriği hakkında yapay zekâ yanıtı üretilmedi. '
                    'Lütfen aşağıdaki resmî bağlantıdan maddeyi kontrol edin.'),
            source_url=KDV_OFFICIAL,
            verified_source=False,
            status='unverified'
        )
    if official_text:
        grounding = ('Aşağıdaki metin GİB sayfasından bu istek sırasında çekilmiştir. '
                     'Yalnızca bu metnin desteklediği hükümleri aktar; erişim, tek başına güncellik garantisi değildir. '
                     'Başka maddelere veya değişikliklere ilişkin kesin güncellik iddiasında bulunma.\n'
                     f'RESMÎ KAYNAK: {KDV_OFFICIAL}\nMADDE METNİ:\n{official_text}')
    else:
        grounding = ('İstenen kanun maddesinin tam metni canlı resmî kaynaktan doğrulanamadı. '
                     'Doğrulanmış kanun metni varmış gibi davranma; gerekirse genel bilgi ver, '
                     'ancak bu bilgileri açıkça doğrulanmamış olarak etiketle. '
                     'Madde numarası, tarih veya oran uydurma.')
    prompt = (f'Sen Türkiye mali mevzuat asistanısın. Kategori: {category}. '
              'Türkçe, açık ve ihtiyatlı cevap ver. Kanun hükümlerini uydurma. '
              f'{grounding}\nKULLANICI SORUSU:\n{question}')
    try:
        r = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
            json={'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': {'temperature': 0.1}},
            timeout=(8, 45))
        if not r.ok:
            try:
                message = r.json().get('error', {}).get('message', 'Bilinmeyen API hatası')
            except (ValueError, AttributeError):
                message = 'API hata yanıtı okunamadı.'
            app.logger.warning('Gemini HTTP %s: %s', r.status_code, str(message)[:500])
            return jsonify(answer='Gemini API hatası: ' + str(message)[:300]), 502
        payload = r.json()
        answer = '\n'.join(p.get('text', '') for c in payload.get('candidates', []) for p in c.get('content', {}).get('parts', []) if p.get('text'))
        suffix = ('\n\nKaynak kontrolü: GİB sayfasında ilgili madde başlığı ve metni bulundu. '
                  'Bu kontrol, metnin yürürlükteki son sürüm olduğunu tek başına kanıtlamaz.' if official_text else
                  '\n\nKaynak kontrolü: İlgili madde tam metni bu oturumda resmî kaynaktan doğrulanamadı.')
        return jsonify(answer=(answer or 'Model yanıt üretemedi.') + suffix,
                       source_url=KDV_OFFICIAL if article else None,
                       verified_source=bool(official_text), status='source_fetched' if official_text else 'unverified')
    except requests.RequestException:
        app.logger.exception('Gemini connection failed')
        return jsonify(answer='Yapay zekâ bağlantısı zaman aşımına uğradı veya kurulamadı.'), 504

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
