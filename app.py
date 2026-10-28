

from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

SOURCES = {
    "Vergi Mevzuatı": [
        ("Gelir İdaresi Başkanlığı", "https://www.gib.gov.tr"),
        ("Mevzuat Bilgi Sistemi", "https://www.mevzuat.gov.tr")
    ],
    "Türk Ticaret Kanunu": [
        ("Mevzuat Bilgi Sistemi", "https://www.mevzuat.gov.tr")
    ],
    "SPK Mevzuatı": [
        ("Sermaye Piyasası Kurulu", "https://spk.gov.tr")
    ],
    "Türkiye Muhasebe Standartları": [
        ("Kamu Gözetimi Kurumu", "https://www.kgk.gov.tr")
    ],
    "Mali Takvim": [
        ("GİB Vergi Takvimi", "https://www.gib.gov.tr"),
        ("SGK", "https://www.sgk.gov.tr")
    ]
}

HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mali Mevzuat AI</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#101827;color:#fff;
font-family:Arial,sans-serif}
header{padding:25px 18px;text-align:center;
background:#17243a}
h1{margin:0;font-size:28px}
header p{color:#b7c7dd}
main{max-width:750px;margin:auto;padding:18px}
section{background:#1d2b42;border-radius:14px;
padding:18px;margin-bottom:18px}
h2{font-size:19px;margin-top:0}
textarea{width:100%;height:115px;padding:13px;
background:#101827;color:white;
border:1px solid #60728c;border-radius:9px;
font-size:16px}
button{width:100%;background:#2984ed;color:white;
padding:14px;border:0;border-radius:9px;
font-size:16px;margin-top:12px}
select{width:100%;padding:12px;margin-bottom:12px;
background:#101827;color:white;
border:1px solid #60728c;border-radius:9px}
a{color:#80bdff;display:block;padding:9px 0}
#result{white-space:pre-wrap;line-height:1.6;
margin-top:15px}
small{color:#b7c7dd}
</style>
</head>
<body>
<header>
<h1>Mali Mevzuat AI</h1>
<p>Vergi • TTK • SPK • TMS</p>
</header>
<main>
<section>
<h2>Mevzuat Asistanı</h2>
<select id="category">
{% for name in sources %}
<option value="{{name}}">{{name}}</option>
{% endfor %}
</select>
<textarea id="question"
placeholder="Mevzuat sorunuzu buraya yazın..."></textarea>
<button onclick="ask()">Soruyu Gönder</button>
<div id="result" aria-live="polite"></div>
</section>
<section>
<h2>Resmî Mevzuat Kaynakları</h2>
{% for name, links in sources.items() %}
<h3>{{name}}</h3>
{% for label, url in links %}
<a href="{{url}}" target="_blank"
rel="noopener noreferrer">{{label}}</a>
{% endfor %}
{% endfor %}
</section>
<section>
<h2>Mali Takvim</h2>
<p>Vergi ve SGK takvimlerini yukarıdaki
resmî bağlantılardan kontrol edebilirsiniz.</p>
<small>Otomatik tarih güncellemesi henüz aktif değil.</small>
</section>
</main>
<script>
async function ask(){
const q=document.getElementById("question").value.trim();
const c=document.getElementById("category").value;
const out=document.getElementById("result");
if(!q){out.textContent="Lütfen sorunuzu yazın.";return;}
out.textContent="Kaynak bilgileri hazırlanıyor...";
try{
const response=await fetch("/api/ask",{
method:"POST",
headers:{"Content-Type":"application/json"},
body:JSON.stringify({question:q,category:c})
});
const data=await response.json();
out.textContent=data.answer || "Yanıt alınamadı.";
}catch(e){
out.textContent="Bağlantı hatası oluştu.";
}
}
</script>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML, sources=SOURCES)

@app.route("/api/ask", methods=["POST"])
def ask():
    data = request.get_json(silent=True) or {}
    question = str(data.get("question", "")).strip()
    category = str(data.get("category", "Vergi Mevzuatı"))

    if not question:
        return jsonify({"answer": "Lütfen soru yazın."}), 400

    if category not in SOURCES:
        return jsonify({"answer": "Geçersiz kategori."}), 400

    links = "\n".join(
        f"{name}: {url}" for name, url in SOURCES[category]
    )

    return jsonify({
        "answer": (
            "Sorunuz alındı:\n" + question +
            "\n\nBu sürüm henüz yapay zekâ yanıtı üretmiyor."
            "\n\nİlgili resmî kaynaklar:\n" + links +
            "\n\nMevzuatın güncel metnini kontrol edin."
        )
    })

if __name__ == "__main__":
    import os
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )

