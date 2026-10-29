"""Conservative, source-linked 2026 topic answers for Mali Mevzuat AI.
This is a limited verified topic guide, not an AI model or live legislative monitor.
"""
import re
from datetime import datetime, timezone

TOPICS = [
    {
        'keywords': ('binek', 'otomobil', 'araç gider', 'arac gider', 'taşıt gider', 'tasit gider'),
        'name': 'Binek otomobil giderleri',
        'year': 2026,
        'source': 'Gelir İdaresi Başkanlığı - Binek Otomobillerde Gider ve Amortismanların Vergi Matrahından İndirimi',
        'url': 'https://www.gib.gov.tr/vergi-konulari/2_isletme_ve_girisimci/18_binek_otomobillerde_gider_ve_amortismanlarin_vergi_matrahindan_indirimi/18',
        'answer': (
            '2026 yılı için, binek otomobillerin yakıt, bakım, sigorta ve benzeri genel giderlerinin '
            'en fazla %70’i vergi matrahından indirilebilir; kalan %30’u kanunen kabul edilmeyen giderdir. '
            'Binek otomobil kiralamalarında aylık KDV hariç kira gider sınırı 46.000 TL’dir. '
            'İlk iktisapta ÖTV ve KDV toplamının doğrudan gider yazılabilecek azami kısmı 1.200.000 TL’dir. '
            'Amortisman sınırları, vergilerin maliyete eklenip eklenmemesine göre değişir. '
            'Faaliyeti binek otomobil kiralama veya işletme olanların bu amaçla kullandıkları araçlar için istisnalar vardır. '
            'MTV, genel %70 kuralından farklı olarak ayrıca değerlendirilir. '
            'KDV indirimi, giderin niteliği ve KDV Kanunu hükümleri dikkate alınarak ayrıca incelenmelidir.'
        ),
        'example': (
            'Örnek: İşte kullanılan binek otomobil için KDV hariç 10.000 TL uygun nitelikte bakım gideri '
            'varsa, 7.000 TL vergi açısından indirilebilir gider, 3.000 TL KKEG olarak değerlendirilir. '
            'Faturadaki KDV’nin indirimi ayrıca kontrol edilir.'
        ),
    },
]

def topic_answer(question):
    q = re.sub(r'\s+', ' ', (question or '').lower()).strip()
    for topic in TOPICS:
        if any(word in q for word in topic['keywords']):
            return {
                'message': 'Konu rehberi eşleşmesi bulundu. Bu cevap canlı mevzuat taraması değildir.',
                'excerpts': [topic['answer'], topic['example']],
                'url': topic['url'],
                'source': topic['source'],
                'checked_at': datetime.now(timezone.utc).isoformat(),
                'topic': topic['name'],
                'year': topic['year'],
                'source_note': 'GİB 2026 konu rehberine dayalı sabit açıklama; güncelliği ayrıca doğrulayın.',
                'verified_live': False,
            }
    return None
