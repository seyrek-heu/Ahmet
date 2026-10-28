import os
import requests
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
SOURCES = {
    'Vergi Mevzuatı': [('Gelir İdaresi Başkanlığı', 'https://www.gib.gov.tr'), ('Mevzuat Bilgi Sistemi', 'https://www.mevzuat.gov.tr')],
    'Türk Ticaret Kanunu': [('Mevzuat Bilgi Sistemi', 'https://www.mevzuat.gov.tr')],
    'SPK Mevzuatı': [('Sermaye Piyasası Kurulu', 'https://spk.gov.tr')],
    'Türkiye Muhasebe Standartları': [('Kamu Gözetimi Kurumu', 'https://www.kgk.gov.tr')],
}
HTML = '''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mali Mevzuat AI</title><style>body{font-family:system-ui;background:#101827;color:#f7f9ff;margin:0;padding:24px}main{max-width:680px;margin:auto}section{background:#1e3049;padding:24px;border-radius:18px;margin:20px 0}h1{font-size:30px}select,textarea,button{box-sizing:border-box;width:100%;padding:15px;border-radius:10px;font-size:17px;margin:10px 0}select,textarea{background:#101827;color:white;border:1px solid #62758e}textarea{min-height:130px}button{background:#2784ea;color:white;border:0;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.55}a{color:#8ec7ff}small{color:#bdc9d8}</style></head><body><main><h1>Mali Mevzuat AI</h1><small>Vergi · TTK · SPK · TMS</small><section><h2>Mevzuat Asistanı</h2><select id="category">{% for category in sources %}<option>{{category}}</option>{% endfor %}</select><textarea id="question" placeholder="Mevzuat sorunuzu yazın"></textarea><button id="send" onclick="ask()">Soruyu Gönder</button><pre id="answer" aria-live="polite"></pre></section><section><h2>Resmî Kaynaklar</h2>{% for category,links in sources.items() %}<h3>{{category}}</h3>{% for name,url in links %}<p><a href="{{url}}" target="_blank" rel="noopener noreferrer">{{name}}</a></p>{% endfor %}{% endfor %}</section></main><script>async function ask(){const b=document.getElementById('send'),a=document.getElementById('answer');b.disabled=true;a.textContent='Yanıt hazırlanıyor...';try{const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:document.getElementById('category').value,question:document.getElementById('question').value})});const j=await r.json();a.textContent=j.answer||'Yanıt alınamadı.'}catch(e){a.textContent='Bağlantı hatası. Tekrar deneyin.'}finally{b.disabled=false}}</script></body></html>'''

@app.get('/')
def home():
    return render_template_string(HTML, sources=SOURCES)

@app.post('/api/ask')
def ask():
    data = request.get_json(silent=True) or {}
    question = str(data.get('question', '')).strip()
    category = str(data.get('category', 'Vergi Mevzuatı'))
    if not question:
        return jsonify(answer='Lütfen sorunuzu yazın.'), 400
    if len(question) > 4000 or category not in SOURCES:
        return jsonify(answer='Geçersiz kategori veya çok uzun soru.'), 400
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        return jsonify(answer='Gemini API anahtarı Render ortam değişkenlerinde tanımlanmamış.'), 503
    model = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')
    prompt = (f'Sen Türkiye mali mevzuat asistanısın. Konu: {category}. '
              'Türkçe, dikkatli ve açık yanıt ver. Kanun maddelerini veya güncel oranları uydurma. '
              'Canlı mevzuat erişimin olmadığını ve güncelliğin doğrulanması gerektiğini gerektiğinde belirt. '
              'Kaynak bağlantılarını yalnızca doğruluğundan eminsen ver. Sorunun içeriği:\n' + question)
    try:
        response = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
            json={'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': {'temperature': 0.2}},
            timeout=45)
        if not response.ok:
            try:
                error = response.json().get('error', {})
                error_message = error.get('message', 'Bilinmeyen API hatası')
            except (ValueError, AttributeError):
                error_message = 'Google API hata yanıtı okunamadı.'
            app.logger.warning('Gemini API HTTP %s: %s', response.status_code, error_message[:1000])
            return jsonify(answer='Gemini API hatası: ' + error_message[:500]), 502
        payload = response.json()
        answer = '\n'.join(p.get('text', '') for c in payload.get('candidates', []) for p in c.get('content', {}).get('parts', []) if p.get('text'))
        return jsonify(answer=(answer or 'Model yanıt üretemedi.') + '\n\nNot: Güncel mevzuatı resmî kaynaklardan teyit edin.')
    except requests.RequestException:
        app.logger.exception('Gemini bağlantı hatası')
        return jsonify(answer='Yapay zekâ bağlantısı zaman aşımına uğradı veya bağlantı kurulamadı. Tekrar deneyin.'), 504

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
