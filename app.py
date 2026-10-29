import os
import re
import json
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)
app.json.ensure_ascii = False
VERSION = '3.6'
KDV_OFFICIAL = 'https://gib.gov.tr/mevzuat/kanun/436'
SOURCES = {
    'Vergi Mevzuatı': [('GİB - KDV Kanunu', KDV_OFFICIAL), ('Mevzuat Bilgi Sistemi', 'https://www.mevzuat.gov.tr')],
    'Türk Ticaret Kanunu': [('Mevzuat Bilgi Sistemi', 'https://www.mevzuat.gov.tr')],
    'SPK Mevzuatı': [('Sermaye Piyasası Kurulu', 'https://spk.gov.tr')],
    'Türkiye Muhasebe Standartları': [('Kamu Gözetimi Kurumu', 'https://www.kgk.gov.tr')],
}
HTML = '''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mali Mevzuat AI {{version}}</title><style>body{font-family:system-ui;background:#101827;color:#f7f9ff;margin:0;padding:20px}main{max-width:750px;margin:auto}section{background:#1e3049;padding:22px;border-radius:18px;margin:18px 0}h1{font-size:29px}select,textarea,button{box-sizing:border-box;width:100%;padding:14px;border-radius:10px;font-size:16px;margin:9px 0}select,textarea{background:#101827;color:white;border:1px solid #62758e}textarea{min-height:125px}button{background:#2784ea;color:white;border:0;cursor:pointer}button:disabled{opacity:.6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.55}a{color:#8ec7ff}small{color:#bdc9d8}details{margin:18px 0}#diagnostics{font-size:13px}</style></head><body><main><h1>Mali Mevzuat AI {{version}}</h1><small>Vergi · TTK · SPK · TMS | Kaynak kontrolü</small><section><h2>Mevzuat Asistanı</h2><select id="category">{% for category in sources %}<option>{{category}}</option>{% endfor %}</select><textarea id="question" placeholder="Örnek: 3065 sayılı KDV Kanunu 29/3 nedir?"></textarea><button id="send" onclick="ask()">Resmî Kaynakta Ara ve Yanıtla</button><pre id="answer" aria-live="polite"></pre><div id="links"></div><details><summary>Kaynak tanılama bilgileri</summary><pre id="diagnostics">Henüz sorgu yapılmadı.</pre></details><button onclick="navigator.clipboard.writeText(document.getElementById('answer').textContent)">Yanıtı Kopyala</button></section><section><h2>Resmî Kaynaklar</h2>{% for category,links in sources.items() %}<h3>{{category}}</h3>{% for name,url in links %}<p><a href="{{url}}" target="_blank" rel="noopener noreferrer">{{name}}</a></p>{% endfor %}{% endfor %}</section></main><script>async function ask(){const b=document.getElementById('send'),a=document.getElementById('answer'),l=document.getElementById('links');b.disabled=true;a.textContent='Resmî kaynak kontrol ediliyor...';l.replaceChildren();document.getElementById('diagnostics').textContent='Kontrol sürüyor...';try{const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:document.getElementById('category').value,question:document.getElementById('question').value})});const j=await r.json();a.textContent=j.answer||'Yanıt alınamadı.';document.getElementById('diagnostics').textContent=JSON.stringify(j.diagnostics||{status:j.status||'bilinmiyor'},null,2);if(j.source_url){const p=document.createElement('p'),link=document.createElement('a');link.href=j.source_url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Kontrol edilen kaynak: '+j.source_url;p.appendChild(link);l.appendChild(p)}}catch(e){a.textContent='Bağlantı hatası. Tekrar deneyin.'}finally{b.disabled=false}}</script></body></html>'''

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
    match = re.search(r'\b(?:kdv|3065)\b[^\n]{0,70}?\b(29|30)(?:\s*/\s*\d+)?\b', q)
    return int(match.group(1)) if match else None


def clean_text(value):
    return re.sub(r'\s+', ' ', value).strip()


def extract_article(text, number):
    text = clean_text(text)
    starts = list(re.finditer(r'(?<!\w)madde\s*' + str(number) + r'\s*[-–—.:)]?', text, re.I))
    for start in starts:
        after = text[start.end():]
        next_heading = re.search(r'(?<!\w)madde\s*' + str(number + 1) + r'\s*[-–—.:)]?', after, re.I)
        if not next_heading:
            continue
        candidate = text[start.start():start.end() + next_heading.start()]
        if not 350 <= len(candidate) <= 30000:
            continue
        norm = candidate.casefold()
        if number == 29 and not ('indir' in norm and ('takvim' in norm or 'fatura' in norm)):
            continue
        if number == 30 and not ('indirileme' in norm or 'indirilemez' in norm):
            continue
        return candidate
    return None


def source_diagnostics(url, response):
    soup = BeautifulSoup(response.content, 'html.parser')
    visible_soup = BeautifulSoup(response.content, 'html.parser')
    for tag in visible_soup(['script', 'style', 'nav', 'header', 'footer']):
        tag.decompose()
    visible = visible_soup.get_text(' ', strip=True)
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    scripts = soup.find_all('script')
    # Only report paths from the trusted official domain; no scripts are executed.
    linked = []
    for tag in soup.find_all(['a', 'iframe', 'embed', 'object']):
        raw = tag.get('href') or tag.get('src') or tag.get('data')
        if not raw:
            continue
        resolved = urljoin(response.url, raw)
        if urlparse(resolved).hostname and (urlparse(resolved).hostname == 'gib.gov.tr' or urlparse(resolved).hostname.endswith('.gib.gov.tr')):
            if any(x in resolved.casefold() for x in ('pdf', 'kanun', 'madde', 'mevzuat')):
                linked.append(resolved[:240])
    embedded_text = ' '.join(s.get_text(' ', strip=True) for s in scripts if not s.get('src'))
    entry = {
        'source': url, 'final_url': response.url[:240], 'status': response.status_code,
        'raw_bytes': len(response.content), 'content_type': response.headers.get('Content-Type', '')[:100],
        'title': title[:120], 'visible_characters': len(visible),
        'script_tags': len(scripts), 'embedded_script_characters': len(embedded_text),
        'article_heading_in_raw_html': bool(re.search(r'(?i)madde\s*29\b|madde\s*30\b', response.text)),
        'official_link_candidates': list(dict.fromkeys(linked))[:12],
        'result': 'article_not_found',
    }
    return entry, visible, embedded_text


def official_article(number):
    urls = [f'https://{host}/mevzuat/kanun/436' for host in ('gib.gov.tr', 'antalya.gib.gov.tr', 'karabuk.gib.gov.tr', 'bilecik.gib.gov.tr')]
    if number == 30:
        urls.insert(0, 'https://gib.gov.tr/mevzuat/kanun/436/madde/7903')
    diagnostic = {'article': number, 'result': 'not_found', 'attempts': []}
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36', 'Accept': 'text/html,application/xhtml+xml', 'Accept-Language': 'tr-TR,tr;q=0.9'})
    for url in urls:
        try:
            response = session.get(url, timeout=(5, 10), allow_redirects=True)
            if len(response.content) > 6_000_000:
                diagnostic['attempts'].append({'source': url, 'status': response.status_code, 'raw_bytes': len(response.content), 'result': 'too_large'})
                continue
            entry, visible, embedded = source_diagnostics(url, response)
            diagnostic['attempts'].append(entry)
            response.raise_for_status()
            # Embedded scripts may hold text as escaped JSON; inspect but never execute.
            candidates = [('visible_html', visible)]
            if embedded:
                candidates.append(('embedded_script', embedded))
                try:
                    candidates.append(('unescaped_script', json.loads('"' + embedded.replace('"', '\\"') + '"')))
                except (ValueError, TypeError):
                    pass
            for source_kind, text in candidates:
                found = extract_article(text, number)
                if found and number == 29 and not re.search(r'(?<!\d)3\s*[.\-)]\s*.{0,450}?(?:takvim|indir)', found, re.I | re.S):
                    entry['result'] = 'article_29_paragraph_3_missing'
                    continue
                if found:
                    entry['result'] = 'verified_article_found_in_' + source_kind
                    diagnostic['result'] = 'verified_article_found'
                    return found, response.url, diagnostic
            entry['result'] = 'article_not_found'
        except requests.RequestException as exc:
            if not diagnostic['attempts'] or diagnostic['attempts'][-1].get('source') != url:
                diagnostic['attempts'].append({'source': url, 'result': 'request_error_' + type(exc).__name__})
            else:
                diagnostic['attempts'][-1]['result'] = 'request_error_' + type(exc).__name__
    return None, KDV_OFFICIAL, diagnostic


@app.post('/api/ask')
def ask():
    data = request.get_json(silent=True) or {}
    question = str(data.get('question', '')).strip()
    category = str(data.get('category', 'Vergi Mevzuatı'))
    if not question or len(question) > 4000 or category not in SOURCES:
        return jsonify(answer='Geçerli bir kategori seçip 1–4000 karakterlik soru yazın.'), 400
    article = requested_article(question) if category == 'Vergi Mevzuatı' else None
    source_text, source_url, diagnostics = official_article(article) if article else (None, None, {'result': 'article_not_supported'})
    app.logger.info('GIB source diagnostics: %s', diagnostics)
    if article and not source_text:
        return jsonify(answer='RESMÎ METİN DOĞRULANAMADI\n\nGİB yanıtları incelendi ancak ilgili kanun maddesi güvenilir biçimde çıkarılamadı. Tanılama bölümünde ham yanıt boyutu, sayfa başlığı ve bağlantı bilgilerini kontrol edin.', source_url=source_url, verified_source=False, status='unverified', diagnostics=diagnostics)
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        return jsonify(answer='GEMINI_API_KEY tanımlanmamış.'), 503
    model = os.environ.get('GEMINI_MODEL', 'gemini-3.1-flash-lite').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', model):
        return jsonify(answer='Geçersiz model ayarı.'), 500
    grounding = (f'GİB sitesinden bu istek sırasında alınan metin (yürürlük/güncellik ayrıca doğrulanmadı):\n{source_text}\nKaynak: {source_url}\nYalnızca bu metinle desteklenen hükümleri doğrulanmış olarak açıkla.' if source_text else 'Canlı resmî madde metni doğrulanmadı. Güncel oran, tarih ve madde içeriği hakkında doğrulama iddiasında bulunma; genel bilgi vereceksen açıkça doğrulanmamış olduğunu belirt.')
    prompt = f'Sen Türkiye mali mevzuat asistanısın. Kategori: {category}. Türkçe ve ihtiyatlı yanıt ver. Doğrulanmamış hükümleri uydurma.\n{grounding}\nKULLANICI SORUSU:\n{question}'
    try:
        response = requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent', headers={'x-goog-api-key': key, 'Content-Type': 'application/json'}, json={'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': {'temperature': 0.1}}, timeout=(8, 45))
        if not response.ok:
            try:
                message = response.json().get('error', {}).get('message', 'Bilinmeyen API hatası')
            except (ValueError, AttributeError):
                message = 'API hata yanıtı okunamadı.'
            return jsonify(answer='Gemini API hatası: ' + str(message)[:300]), 502
        payload = response.json()
        answer = '\n'.join(p.get('text', '') for c in payload.get('candidates', []) for p in c.get('content', {}).get('parts', []) if p.get('text'))
        suffix = ('\n\nKaynak kontrolü: GİB kaynağından madde metni çıkarıldı; yürürlükteki son sürüm olduğu ayrıca doğrulanmadı.' if source_text else '\n\nKaynak kontrolü: Bu yanıt için canlı madde metni doğrulanmadı.')
        return jsonify(answer=(answer or 'Model yanıt üretemedi.') + suffix, source_url=source_url, verified_source=bool(source_text), status='source_fetched' if source_text else 'unverified', diagnostics=diagnostics)
    except requests.RequestException:
        app.logger.exception('Gemini bağlantı hatası')
        return jsonify(answer='Yapay zekâ bağlantısı zaman aşımına uğradı veya kurulamadı.'), 504

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
