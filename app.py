import os, asyncio, logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.client.default import DefaultBotProperties
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn, httpx

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = os.environ.get("WEBAPP_URL", "http://localhost:8000")

CODES = {
"P0300": ("إشعال متعدد الأعطال (Misfire)", ["بواجات","كويلات","حاقن","باكر سينس","خلط وقود"],
 ["فحص البواجات وتغييرها بنفس الترتيب","فحص الكويلات بالتبديل","فحص الحاقن"],
 "لا تتجاهله — ضعف الإشعال يحرق المحول الكتاليتي."),
"P0301": ("إشعال متعدد — الأسطوانة 1", ["شمعة","كويل","حاقن","ضغط منخفض"],
 ["فحص البواجات","فحص كويل الأسطوانة 1","فحص الحاقن 1"],"غيّر البواجات الثماني كلها."),
"P0152": ("جهد حساس الأكسجين Bank 2 Sensor 1 عالي", ["تسريب عادم","حساس قديم","خلط وقود"],
 ["فحص تسريب العادم أولاً","قراءة نسبة الوقود","فحص السلك"],"ابدأ بتسريب العادم — أرخص سبب."),
"P0125": ("حساس حرارة المبرد (Closed Loop)", ["ثرموستات","مستوى المبرد","حساس ECT"],
 ["قراءة حرارة المبرد","فحص الثرموستات","فحص المستوى"],"لا تفتح غطاء البراد وهي ساخنة."),
"P0118": ("جهد حساس المبرد خارج المدى", ["حساس ECT","توصيلات","PCM"],
 ["فحص مقاومة الحساس","فحص السلك من PCM"],"ECT السليم ~85kΩ عند 20°م."),
"P0740": ("انزلاق محول العزم", ["زيت MERCON V","فلتر","سولENOID","محول تالف"],
 ["فحص مستوى ونوع الزيت","تغيير الفلتر","فحص سولENOID"],"اهتزاز 50-70 كم/س = محول تالف غالباً."
          "P0741": ("أداء محول العزم غير صحيح", ["سولENOID","أسلاك","PCM"],
 ["فحص سولENOID بالأوم","فحص التوصيلات"],"لا تتركها — بتوقف السيارة."),
"P2107": ("وحدة التحكم بالثrottle — عطل معالج TAC", ["بطارية","أرضيات","أسلاك TAC","حساس TPS"],
 ["فحص أرضيات PCM","فحص البطاريات","فحص أسلاك TAC"],"أكثر الكودات تتكرر بسبب الأرضيات."),
"P0607": ("أداء معالج PCM — خطأ داخلي", ["أرضيات ضعيفة","BCM","تمويل","برمجة ناقصة"],
 ["فحص الأرضيات والتمويل","فحص BCM"],"لا تغيّر PCM قبل فحص الأرضيات."),
"P2196": ("حساس O2 Bank 1 إشارة ثابتة غنية", ["تسريب وقود","حاقن","حساس","خلط هواء"],
 ["فحص تسريب الحقن","فحص MAP","فحص حساس O2"],"تسريب الحقن بعد التنقيط = حساس يتلف."),
"B1342": ("حساس حرارة الهواء ACT", ["حساس","توصيلات","PCM"],
 ["فحص مقاومة الحساس","فحص السلك"],"خطأ بارد/ساخن مع undiagnosed."),
"C0300": ("نظام ABS — عطل وحدة التحكم", ["مستشعرات عجلات","وحدة ABS","بطارية","أسلاك"],
 ["قراءة أكواد ABS","فحص أسلاك المستشعرات","فحص البطارية"],"بطارية ضعيفة = أكواد ABS."),
"C0135": ("مستشعر سرعة العجلة الأمامية الأيمن", ["حساس","أسلاك","كونيكتور","حلقة الترس"],
 ["فحص المقاومة","فحص الأسلاك","فحص حلقة الترس"],"غبار الماغنِت يعطي كود زائف."),
"U0100": ("فقدان الاتصال بوحدة PCM/ACM", ["شبكة CAN","BCM","أرضيات","فيوزات"],
 ["فحص شبكة CAN","فحص الفيوزات","فحص الأرضيات"],"افحص CAN بالجهاز أول خطوة."),
"P1000": ("قراءة الكود غير مكتملة", ["بروتوكول خاطئ","فيوز","بطارية","سوكت"],
 ["اختيار بروتوكول J1850","فحص الفيوزات","فحص الباتيري"],"باور سبلتير يعطي P1000."),
}

def find(code):
    d = CODES.get(code)
    if not d:
        return None
    ar, causes, steps, tip = d
    return (f"🔧 <b>{code} — {ar}</b>\n\n"
            f"<b>الأسباب الشائعة:</b>\n" + "\n".join("• "+c for c in causes) +
            f"\n\n<b>خطوات التشخيص:</b>\n" + "\n".join(f"{i+1}) {s}" for i,s in enumerate(steps)) +
            f"\n\n💡 <b>نصيحة:</b> {tip}")

async def ai_explain(code):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    sys_p = ("أنت خبير فورد بانثر. اشرح بالعربي المختصر أي كود OBD-II: المعنى، الأسباب، "
             "أرقام قطع فورد، التشخيص، نصيحة.")
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model":"gpt-4o-mini","temperature":0.2,
                      "messages":[{"role":"system","content":sys_p},
                                  {"role":"user","content":f"الكود: {code}"}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except Exception:
        return None
      ```python
`HTML ``=`` ``"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>فاحص أكواد فورد بانثر</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>body{margin:0;background:#0f1216;color:#e8edf3;font-family:system-ui,Tahoma;padding:14px}
h1{font-size:18px}input,button{width:100%;padding:13px;border-radius:12px;font-size:16px;margin-bottom:9px}
input{background:#12161c;color:#e8edf3;border:1px solid #2a323d;text-align:center;letter-spacing:2px;font-weight:700}
button{background:#3b82f6;color:#fff;border:0;font-weight:700}
.q{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.q button{width:auto;padding:8px 11px;font-size:13px;background:#222a34;letter-spacing:1px}
#o{background:#181d24;border:1px solid #232b35;border-radius:14px;padding:14px;white-space:pre-wrap;line-height:1.85;display:none}
.t{display:inline-block;background:#12304d;color:#7dd3fc;border-radius:20px;padding:2px 10px;font-size:12px;margin-bottom:8px}
</style></head><body><h1>فاحص أكواد فورد بانثر</h1>
<input id="c" placeholder="P0300"><button onclick="go()">اشرح الكود</button>
<div class="q"><button onclick="q('P0300')">P0300</button><button onclick="q('P0152')">P0152</button><button onclick="q('P0740')">P0740</button><button onclick="q('P2107')">P2107</button><button onclick="q('C0135')">C0135</button><button onclick="q('U0100')">U0100</button></div>
<div id="o"></div><script>
var o=document.getElementById('o');
function q(c){document.getElementById('c').value=c;go();}
async function go(){var c=document.getElementById('c').value.trim().toUpperCase();
if(!/^[PBUC][0-9]{4}$/.test(c)){o.style.display='block';o.innerHTML='اكتب كود صحيح مثل P0300';return;}
o.style.display='block';o.innerHTML='جاري الشرح...';
try{var r=await fetch('/api/explain',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:c})});
var j=await r.json();var s=j.source==='local'?'قاعدة الأكواد':(j.source==='ai'?'ذكاء صناعي':'غير متوفر');
o.innerHTML='<span class="t">'+s+' - '+j.code+'</span>'+j.text;}catch(e){o.innerHTML='تعذّر الاتصال، حاول مرة ثانية.';}}
</script></body></html>"""``

bot ``=`` Bot``(``token``=``TOKEN``,`` default``=``DefaultBotProperties``(``parse_mode``=``"HTML"``))``
dp ``=`` Dispatcher``()``
app ``=`` FastAPI``()``

@app``.``get``(``"/"``,`` response_class``=``HTMLResponse``)``
``async`` ``def`` root``():``
    ``return`` HTML

@app``.``post``(``"/api/explain"``)``
``async`` ``def`` api``(``payload``:`` ``dict``):``
    code ``=`` ``str``(``payload``.``get``(``"code"``,``""``)).``strip``().``upper``()``
    local ``=`` find``(``code``)``
    ``if`` local``:``
        ``return`` ``{``"code"``:``code``,``"source"``:``"local"``,``"text"``:``local``}``
    ai ``=`` ``await`` ai_explain``(``code``)``
    ``if`` ai``:``
        ``return`` ``{``"code"``:``code``,``"source"``:``"ai"``,``"text"``:``ai``}``
    ``return`` ``{``"code"``:``code``,``"source"``:``"none"``,``"text"``:``f"ما لقيت ``{``code``}`` في القاعدة."``}``

@dp``.``message``(``CommandStart``())``
``async`` ``def`` start``(``m``:`` types``.``Message``):``
    kb ``=`` InlineKeyboardMarkup``(``inline_keyboard``=``[[``InlineKeyboardButton``(``
        text``=``"فاحص الأكواد"``,`` web_app``=``WebAppInfo``(``url``=``f"``{``WEBAPP_URL``}``/"``))]])``
    ``await`` m``.``answer``(``"أهلاً بيك\nاضغط الزر تحت وابحث عن كودك، أو أرسل الكود هنا مباشرة."``,``
                   reply_markup``=``kb``)``

@dp``.``message``(``F``.``text``.``regexp``(``r"\b[PBUC][0-9]{4}\b"``))``
``async`` ``def`` code_msg``(``m``:`` types``.``Message``):``
    code ``=`` m``.``text``.``strip``().``split``()[``0``].``upper``()``
    txt ``=`` find``(``code``)`` ``or`` ``await`` ai_explain``(``code``)`` ``or`` ``f"ما لقيت ``{``code``}`` في القاعدة."``
    ``await`` m``.``answer``(``txt``)``

``if`` __name__ ``==`` ``"__main__"``:``
    ``async`` ``def`` main``():``
        cfg ``=`` uvicorn``.``Config``(``app``,`` host``=``"0.0.0.0"``,`` port``=``int``(``os``.``environ``.``get``(``"PORT"``,`` ``8000``)),`` log_level``=``"info"``)``
        ``await`` asyncio``.``gather``(``dp``.``start_polling``(``bot``),`` uvicorn``.``Server``(``cfg``).``serve``())``
    asyncio``.``run``(``main``())`
```
