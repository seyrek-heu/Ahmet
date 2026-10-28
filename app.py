
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>Mali Mevzuat AI</title>
    </head>
    <body style="background:#101827;
                 color:white;
                 font-family:Arial;
                 text-align:center;
                 padding:40px;">
        <h1>Mali Mevzuat AI</h1>
        <h2>Uygulama Başarıyla Çalışıyor</h2>
        <p>Vergi, TTK, SPK ve TMS</p>
        <p>İlk kurulum sürümü</p>
    </body>
    </html>
    """

if __name__ == "__main__":
    app.run()

