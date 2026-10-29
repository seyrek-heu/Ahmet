import io
import os
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string, request
from pypdf import PdfReader

app = Flask(__name__)
app.json.ensure_ascii = False

VERSION = '3.3'
KDV_OFFICIAL = 'https://gib.gov.tr/mevzuat/kanun/436'
SOURCES = {
    'Vergi Mevzuatı': [('GİB - KDV Kanunu', KDV_OFFICIAL), ('Mevzuat Bilgi Sistemi', 'https://www.mevzuat.gov.tr')],
    'Türk Ticaret Kanunu': [('Mevzuat Bilgi Sistemi', 'https://www.mevzuat.gov.tr')],
    'SPK Mevzuatı': [('Sermaye Piyasası Kurulu', 'https://spk.gov.tr')],
    'Türkiye Muhasebe Standartları': [('Kamu Gözetimi Kurumu', 'https://www.kgk.gov.tr')],
}
HTML = '''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mali Mevzuat AI {{version}}</title><style>body{font-family:system-ui;background:#101827;color:#f7f9ff;margin:0;padding:20px}main{max-width:750px;margin:auto}section{background:#1e3049;padding:22px;border-radius:18px;margin:18px 0}h1{font-size:29px}select,textarea,button{box-sizing:border-box;width:100%;padding:14px;border-radius:10px;font-size:16px;margin:9px 0}select,textarea{background:#101827;color:white;border:1px solid #62758e}textarea{min-height:125px}button{background:#2784ea;color:white;border:0;cursor:pointer}button:disabled{opacity:.6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.55}a{color:#8ec7ff}small{color:#bdc9d8}</style></head><body><main><h1>Mali Mevzuat AI {{version}}</h1><small>Vergi · TTK · SPK · TMS | Kaynak kontrolü</small><section><h2>Mevzuat Asistanı</h2><select id="category">{% for category in sources %}<option>{{category}}</option>{% endfor %}</select><textarea id="question" placeholder="Örnek: 3065 sayılı KDV Kanunu 29/3 nedir?"></textarea><button id="send" onclick="ask()">Resmî Kaynakta Ara ve Yanıtla</button><pre id="answer" aria-live="polite"></pre><div id="links"></div><button onclick="navigator.clipboard.writeText(document.getElementById('answer').textContent)">Yanıtı Kopyala</button></section><section><h2>Resmî Kaynaklar</h2>{% for category,links in sources.items() %}<h3>{{category}}</h3>{% for name,url in links %}<p><a href="{{url}}" target="_blank" rel="noopener noreferrer">{{name}}</a></p>{% endfor %}{% endfor %}</section></main><script>async function ask(){const b=document.getElementById('send'),a=document.getElementById('answer'),l=document.getElementById('links');b.disabled=true;a.textContent='Resmî kaynak kontrol ediliyor...';l.replaceChildren();try{const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:document.getElementById('category').value,question:document.getElementById('question').value})});const j=await r.json();a.textContent=j.answer||'Yanıt alınamadı.';if(j.source_url){const p=document.createElement('p'),link=document.createElement('a');link.href=j.source_url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Kontrol edilen kaynak: '+j.source_url;p.appendChild(link);l.appendChild(p)}}catch(e){a.textContent='Bağlantı hatası. Tekrar deneyin.'}finally{b.disabled=false}}</script></body></html>'''

@app.get('/')
def home():
    return render_template_string(HTML, sources=SOURCES, version=VERSION)

@app.get('/health')
def health():
    return jsonify(status='ok', version=VERSION)


def requested_article(question):
    q = question.casefold()
    if not any(x in q for x in ('3065', 'kdv', 'katma değer')):
        return None
    match = re.search(r'\b(?:madde\s*|m\.?\s*)(29|30)\b|\b(29|30)\s*(?:/\s*\d+)?\s*\.?\s*madde\b|\b3065\s*(?:sayılı)?\s*(?:kanun(?:un)?\s*)?(29|30)\b', q)
    if match:
        return int(next(x for x in match.groups() if x))
    # E.g. 'KDV 29/3' or 'KDV 29'
    match = re.search(r'\b(?:kdv|3065)\b[^\n]{0,70}?\b(29|30)(?:\s*/\s*\d+)?\b', q)
    return int(match.group(1)) if match else None


def clean_text(value):
    return re.sub(r'\s+', ' ', value).strip()


def extract_article(text, number):
    text = clean_text(text)
    # Some PDF files render headings as 'MADDE 29 –', others as 'Madde 29 -'.
    starts = list(re.finditer(r'(?<!\w)madde\s*' + str(number) + r'\s*[-–—.:)]?', text, re.I))
    for start in starts:
        after = text[start.end():]
        next_heading = re.search(r'(?<!\w)madde\s*' + str(number + 1) + r'\s*[-–—.:)]?', after, re.I)
        if not next_heading:
            continue  # Do not include an unbounded fragment of an unrelated page.
        candidate = text[start.start():start.end() + next_heading.start()]
        if len(candidate) < 350 or len(candidate) > 30000:
            continue
        # Article-specific signals help exclude TOC and navigation hits.
        normalized = candidate.casefold()
        if number == 29 and not ('indir' in normalized and ('takvim' in normalized or 'fatura' in normalized)):
            continue
        if number == 30 and not ('indirileme' in normalized or 'indirilemez' in normalized):
            continue
        return candidate
    return None


def official_article(number):
    """Fetch bounded HTML/PDF from GIB only; failure is NOT proof of no law."""
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; MaliMevzuatAI/3.3)'})
    try:
        r = session.get(KDV_OFFICIAL, timeout=(5, 12))
        r.raise_for_status()
        if len(r.content) > 4_000_000:
            return None, KDV_OFFICIAL
        soup = BeautifulSoup(r.content, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
            tag.decompose()
        found = extract_article(soup.get_text(' ', strip=True), number)
        if found:
            return found, r.url
        # Some GIB law pages expose the actual text in a linked PDF.
        candidates = []
        for tag in soup.select('a[href], iframe[src], embed[src]'):
            href = tag.get('href') or tag.get('src') or ''
            link = urljoin(r.url, href)
            parsed = urlparse(link)
            if parsed.scheme != 'https' or parsed.hostname not in ('gib.gov.tr', 'www.gib.gov.tr'):
                continue
            if '.pdf' in parsed.path.lower() and link not in candidates:
                candidates.append(link)
        for url in candidates[:3]:
            try:
                pdf = session.get(url, timeout=(5, 15))
                pdf.raise_for_status()
                if not pdf.content.startswith(b'%PDF') or len(pdf.content) > 8_000_000:
                    continue
                reader = PdfReader(io.BytesIO(pdf.content), strict=False)
                if len(reader.pages) > 350:
                    continue
                parts = []
                for page in reader.pages:
                    parts.append(page.extract_text() or '')
                found = extract_article(' '.join(parts), number)
                if found:
                    return found, url
            except (requests.RequestException, ValueError, Exception) as exc:
                app.logger.info('PDF okunamadı: %s', type(exc).__name__)
        return None, r.url
    except requests.RequestException as exc:
        app.logger.warning('GIB erişimi başarısız: %s', type(exc).__name__)
        return None, KDV_OFFICIAL


@app.post('/api/ask')
def ask():
    data = request.get_json(silent=True) or {}
    question = str(data.get('question', '')).strip()
    category = str(data.get('category', 'Vergi Mevzuatı'))
    if not question or len(question) > 4000 or category not in SOURCES:
        return jsonify(answer='Geçerli bir kategori seçip 1–4000 karakterlik soru yazın.'), 400
    article = requested_article(question) if category == 'Vergi Mevzuatı' else None
    source_text, source_url = official_article(article) if article else (None, None)
    if article and not source_text:
        return jsonify(answer='RESMÎ METİN DOĞRULANAMADI\n\nGİB sayfası veya bağlı PDF içinden ilgili kanun maddesinin tam metni güvenilir biçimde çıkarılamadı. Bu nedenle madde hakkında tahmini cevap verilmedi. Kaynağı bağlantıdan manuel kontrol edin.', source_url=source_url, verified_source=False, status='unverified')
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        return jsonify(answer='GEMINI_API_KEY tanımlanmamış.'), 503
    model = os.environ.get('GEMINI_MODEL', 'gemini-3.1-flash-lite').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', model):
        return jsonify(answer='Geçersiz model ayarı.'), 500
    grounding = (f'GİB sitesinden bu istek sırasında alınan metin (yürürlük/güncellik ayrıca doğrulanmadı):\n{source_text}\nKaynak: {source_url}\nYalnızca bu metinle desteklenen hükümleri doğrulanmış olarak açıkla.' if source_text else 'Canlı resmî madde metni doğrulanmadı. Güncel oran, tarih ve madde içeriği hakkında doğrulama iddiasında bulunma; genel bilgi vereceksen açıkça doğrulanmamış olduğunu belirt.')
    prompt = f'Sen Türkiye mali mevzuat asistanısın. Kategori: {category}. Türkçe ve ihtiyatlı yanıt ver. Doğrulanmamış hükümleri uydurma.\n{grounding}\nKULLANICI SORUSU:\n{question}'
    try:
        r = requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent', headers={'x-goog-api-key': key, 'Content-Type': 'application/json'}, json={'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': {'temperature': 0.1}}, timeout=(8, 45))
        if not r.ok:
            try:
                message = r.json().get('error', {}).get('message', 'Bilinmeyen API hatası')
            except (ValueError, AttributeError):
                message = 'API hata yanıtı okunamadı.'
            app.logger.warning('Gemini HTTP %s: %s', r.status_code, str(message)[:500])
            return jsonify(answer='Gemini API hatası: ' + str(message)[:300]), 502
        payload = r.json()
        answer = '\n'.join(p.get('text', '') for c in payload.get('candidates', []) for p in c.get('content', {}).get('parts', []) if p.get('text'))
        suffix = ('\n\nKaynak kontrolü: GİB kaynağından madde metni çıkarıldı; yürürlükteki son sürüm olduğu ayrıca doğrulanmadı.' if source_text else '\n\nKaynak kontrolü: Bu yanıt için canlı madde metni doğrulanmadı.')
        return jsonify(answer=(answer or 'Model yanıt üretemedi.') + suffix, source_url=source_url, verified_source=bool(source_text), status='source_fetched' if source_text else 'unverified')
    except requests.RequestException:
        app.logger.exception('Gemini bağlantı hatası')
        return jsonify(answer='Yapay zekâ bağlantısı zaman aşımına uğradı veya kurulamadı.'), 504

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
