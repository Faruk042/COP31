import os
import re
import time
import uuid
import threading
import requests
from urllib.parse import urljoin
from datetime import datetime
from bs4 import BeautifulSoup
import streamlit as st
import ollama
import chromadb
import fitz  # PyMuPDF
import docx
from duckduckgo_search import DDGS
from google import genai
from google.genai import types

import folium
from streamlit_folium import st_folium

import ssl
import urllib3

try:
    ssl._create_default_https_context = ssl._create_unverified_context
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except AttributeError:
    pass

# =====================================================================
# SAYFA VE TEMA YAPILANDIRMASI
# =====================================================================
st.set_page_config(page_title="COP31 Sağlık ve İklim Merkezi", page_icon="🌍", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .stApp { background-color: #0b192c; color: #f8f9fa; }
    .stChatInput { border-color: #00A86B !important; }
    .uyari-kutusu { background-color: #850000; padding: 15px; border-radius: 10px; color: white; font-weight: bold; border-left: 5px solid #ff0000; }
    .basari-kutusu { background-color: #004d40; padding: 10px; border-radius: 8px; color: #e0f2f1; }
    </style>
""", unsafe_allow_html=True)

# =====================================================================
# OTURUM (SESSION) VE ARKA PLAN İZLEYİCİ DEĞİŞKENLERİ
# =====================================================================
if "mesajlar" not in st.session_state:
    st.session_state.mesajlar = [{"role": "system",
                                  "content": "[SİSTEM]: Altar Climate Core Çevrimiçi. Bölgesel hava kalitesi, sağlık verileri veya erken uyarı analizleri için komut bekliyorum."}]
if "islenen_linkler" not in st.session_state:
    st.session_state.islenen_linkler = set()
if "scraper_aktif" not in st.session_state:
    st.session_state.scraper_aktif = False
if "harita_riskleri" not in st.session_state:
    st.session_state.harita_riskleri = [
        {"lat": 37.87, "lon": 32.48, "tooltip": "Gözlem Noktası: Konya (Aktif Veri Bekleniyor)"}]


# =====================================================================
# VERİTABANI VE HAFIZA YÖNETİMİ
# =====================================================================
@st.cache_resource
def get_chroma_client():
    db_path = os.path.join(os.getcwd(), "chroma_memory")
    if not os.path.exists(db_path):
        os.makedirs(db_path)
    client = chromadb.PersistentClient(path=db_path)
    return client.get_or_create_collection(name="cop31_semantic_memory")


collection = get_chroma_client()


def belgeyi_hafizaya_al(icerik, kaynak_adi):
    if not icerik.strip(): return False
    chunk_size = 1500
    chunks = [icerik[i:i + chunk_size] for i in range(0, len(icerik), chunk_size)]
    for i, chunk in enumerate(chunks):
        mesaj_id = str(uuid.uuid4())
        metin = f"KAYNAK: {kaynak_adi}\nBÖLÜM: {i + 1}/{len(chunks)}\nİÇERİK:\n{chunk}"
        collection.add(
            documents=[metin],
            metadatas=[{"source": kaynak_adi, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}],
            ids=[mesaj_id]
        )
    return True


def hafizada_ara(sorgu, n_results=3):
    try:
        results = collection.query(query_texts=[sorgu], n_results=n_results)
        if results['documents'] and results['documents'][0]:
            return "\n\n".join(results['documents'][0])
        return ""
    except:
        return ""


# =====================================================================
# ARAÇLAR (TOOL CALLING FONKSİYONLARI)
# =====================================================================
def web_search(query: str) -> str:
    try:
        sonuclar = list(DDGS().text(query, max_results=3))
        if not sonuclar: return "Sonuç bulunamadı."
        return "\n".join([f"- {s.get('title')}: {s.get('body')}" for s in sonuclar])
    except Exception as e:
        return f"Arama hatası: {e}"


def fetch_climate_health_api(query: str) -> str:
    try:
        sonuclar = list(DDGS().text(f"climate change health epidemic {query}", max_results=3))
        if not sonuclar: return "Açık veri bulunamadı."
        return "\n".join([f"🌍 {s.get('title')}: {s.get('body')}" for s in sonuclar])
    except Exception as e:
        return f"Veri çekim hatası: {e}"


def get_air_quality(city: str) -> str:
    try:
        res = requests.get(f"https://wttr.in/{city}?format=j1", timeout=5)
        if res.status_code == 200:
            data = res.json()['current_condition'][0]
            return f"[CANLI VERİ - {city}]: Sıcaklık: {data['temp_C']}°C, Durum: {data['weatherDesc'][0]['value']}, Nem: %{data['humidity']}"
        return f"Sensörlere ulaşılamadı."
    except:
        return "Sensör bağlantı hatası."


def read_webpage(url: str) -> str:
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        for script in soup(["script", "style"]): script.extract()
        return soup.get_text(separator='\n', strip=True)[:4000]
    except Exception as e:
        return f"Sayfa okunamadı: {e}"


# =====================================================================
# SONSUZ DÖNGÜ: ARKA PLAN VERİ İZLEYİCİ (SCRAPER THREAD)
# =====================================================================
def arkaplan_izleyici_dongusu(hedef_url):
    headers = {'User-Agent': 'COP31-AI-Agent'}
    while st.session_state.scraper_aktif:
        try:
            res = requests.get(hedef_url, headers=headers, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.content, 'html.parser')
                for a_tag in soup.find_all('a', href=True):
                    link = a_tag['href']
                    if link.endswith(('.csv', '.json', '.txt')):
                        tam_link = urljoin(hedef_url, link)
                        dosya_adi = os.path.basename(tam_link)

                        if tam_link not in st.session_state.islenen_linkler:
                            st.session_state.islenen_linkler.add(tam_link)

                            veri_res = requests.get(tam_link, timeout=15)
                            icerik = veri_res.text
                            belgeyi_hafizaya_al(icerik, dosya_adi)

                            uyari_metni = f"🚨 [OTOMATİK İZLEME]: İzlenen portala yeni bir veri eklendi ({dosya_adi}). Veri RAG hafızasına alındı. Etki analizi için sistemi tetikleyebilirsiniz."
                            st.session_state.mesajlar.append({"role": "system", "content": uyari_metni})
        except Exception:
            pass

        time.sleep(20)


# =====================================================================
# SOL MENÜ KONTROL PANELİ
# =====================================================================
with st.sidebar:
    st.title("⚙️ COP31 Sistem Kontrolü")

    motor_secimi = st.selectbox("Yapay Zeka Motoru", ["Yerel (Ollama)", "Bulut (Gemini API)"])
    if motor_secimi == "Yerel (Ollama)":
        try:
            modeller = [m['model'] for m in ollama.Client(host='http://localhost:11434').list().get('models', [])]
        except:
            modeller = ["Bağlantı Hatası"]
        model_secimi = st.selectbox("Aktif Model", modeller)
    else:
        model_secimi = st.selectbox("API Modeli", ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash-exp"])
        api_key = st.text_input("Gemini API Key", type="password")

    st.divider()

    st.markdown("### 📡 Canlı Epidemiyoloji İzleyici")
    hedef_portal = st.text_input("Hedef Veri URL'si", value="https://who.int/data/")

    if st.toggle("Sürekli İzlemeyi Başlat (Sonsuz Döngü)", value=st.session_state.scraper_aktif):
        if not st.session_state.scraper_aktif:
            st.session_state.scraper_aktif = True
            threading.Thread(target=arkaplan_izleyici_dongusu, args=(hedef_portal,), daemon=True).start()
            st.toast("Arka plan veri izleyicisi başlatıldı!", icon="📡")
    else:
        st.session_state.scraper_aktif = False

    st.divider()
    yuklenen_dosya = st.file_uploader("📄 Manuel Rapor Yükle (PDF/TXT/DOCX)", type=["pdf", "txt", "docx"])
    if yuklenen_dosya:
        if st.button("Hafızaya Al"):
            icerik = ""
            if yuklenen_dosya.name.endswith(".txt"):
                icerik = yuklenen_dosya.getvalue().decode("utf-8")
            elif yuklenen_dosya.name.endswith(".pdf"):
                doc = fitz.open(stream=yuklenen_dosya.getvalue(), filetype="pdf")
                for page in doc: icerik += page.get_text() + "\n"
            elif yuklenen_dosya.name.endswith(".docx"):
                doc = docx.Document(yuklenen_dosya)
                for para in doc.paragraphs: icerik += para.text + "\n"

            belgeyi_hafizaya_al(icerik, yuklenen_dosya.name)
            st.success(f"{yuklenen_dosya.name} başarıyla işlendi.")

# =====================================================================
# ANA EKRAN GÖSTERGELERİ VE HARİTA
# =====================================================================
st.title("🌍 COP31 Erken Uyarı ve İklim Merkezi")
col1, col2, col3 = st.columns(3)
col1.metric(label="🌡️ Küresel Ortalama Sapma", value="+1.2 °C", delta="Kritik Seviye", delta_color="inverse")
col2.metric(label="💨 Güncel AQI (Hava Kalite İndeksi)", value="142", delta="- Yüksek Risk", delta_color="inverse")
col3.metric(label="🦠 Arka Plan İzleyici", value="Aktif" if st.session_state.scraper_aktif else "Kapalı",
            delta="Sonsuz Döngü", delta_color="normal")

st.divider()

# Dinamik Harita Alanı (OpenStreetMap kullanılarak API sorunu çözüldü)
st.markdown("### 🗺️ Dinamik Risk ve Salgın Haritası")
m = folium.Map(location=[39.0, 35.0], zoom_start=4, tiles="OpenStreetMap")

for risk in st.session_state.harita_riskleri:
    folium.CircleMarker(
        location=[risk["lat"], risk["lon"]],
        radius=12,
        color="red",
        fill=True,
        fill_color="red",
        tooltip=risk["tooltip"]
    ).add_to(m)

st_folium(m, width=1200, height=350, returned_objects=[])

st.divider()

# =====================================================================
# SOHBET VE OTONOM AJAN MANTIĞI (TOOL CALLING)
# =====================================================================
for msj in st.session_state.mesajlar:
    role = "assistant" if msj["role"] in ["system", "assistant"] else "user"
    with st.chat_message(role):
        if "🚨" in msj["content"]:
            st.markdown(f'<div class="uyari-kutusu">{msj["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(msj["content"])

if prompt := st.chat_input("İklim ve sağlık analizi için veri girin..."):
    st.session_state.mesajlar.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        cevap_alani = st.empty()

        istem = (
            "Sen COP31 Dinamik ve Dayanıklı Sağlık Sistemleri projesi Baş Analistisin. "
            "Arama İçin: SEARCH:::kelime | Sağlık Verisi İçin: HEALTH_SEARCH:::kelime | Hava Kalitesi İçin: AQI_SCAN:::Şehir | Hafıza İçin: MEMORY_SEARCH:::kelime | Sayfa Okuma İçin: READ:::url\n"
            "Haritaya Risk İşaretlemek İçin: MAP_ALERT:::Enlem,Boylam,Açıklama (Örn: MAP_ALERT:::37.87,32.48,Konya Yüksek Sıcaklık Riski)\n\n"
        )

        gonderilecek_mesajlar = [{"role": "system", "content": istem}] + [{"role": m["role"], "content": m["content"]}
                                                                          for m in st.session_state.mesajlar[-6:]]

        # Ajan Döngüsü (Otonom Karar Verme)
        adim = 0
        while adim < 5:
            adim += 1
            tam_cevap = ""

            try:
                if motor_secimi == "Yerel (Ollama)":
                    akim = ollama.chat(model=model_secimi, messages=gonderilecek_mesajlar, stream=True,
                                       options={"temperature": 0.3})
                    for parca in akim:
                        tam_cevap += parca['message'].get('content', '')
                        if not any(x in tam_cevap for x in
                                   ["SEARCH:::", "HEALTH_SEARCH:::", "AQI_SCAN:::", "MEMORY_SEARCH:::", "READ:::",
                                    "MAP_ALERT:::"]):
                            cevap_alani.markdown(tam_cevap + "▌")
                else:
                    client = genai.Client(api_key=api_key)
                    baglam_metni = "\n".join([f"{m['role']}: {m['content']}" for m in gonderilecek_mesajlar])
                    res = client.models.generate_content(model=model_secimi, contents=[baglam_metni])
                    tam_cevap = res.text
            except Exception as e:
                tam_cevap = f"Motor Hatası: {e}"
                cevap_alani.markdown(tam_cevap)
                break

            # ARAÇ KONTROLLERİ (REGEX)
            match_search = re.search(r'SEARCH:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
            match_health = re.search(r'HEALTH_SEARCH:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
            match_aqi = re.search(r'AQI_SCAN:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
            match_memory = re.search(r'MEMORY_SEARCH:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
            match_read = re.search(r'READ:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
            match_map = re.search(r'MAP_ALERT:::(.*?),(.*?),(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)

            if match_map:
                try:
                    lat, lon, desc = float(match_map.group(1).strip()), float(
                        match_map.group(2).strip()), match_map.group(3).strip()
                    st.session_state.harita_riskleri.append({"lat": lat, "lon": lon, "tooltip": desc})
                    gonderilecek_mesajlar.append({"role": "assistant", "content": tam_cevap})
                    gonderilecek_mesajlar.append(
                        {"role": "user", "content": "[SİSTEM]: Haritaya risk noktası başarıyla eklendi."})
                    continue
                except:
                    pass

            if any([match_search, match_health, match_aqi, match_memory, match_read]):
                gonderilecek_mesajlar.append({"role": "assistant", "content": tam_cevap})
                cevap_alani.markdown("⚙️ *Sistem araçları kullanılıyor, veri toplanıyor...*")

                if match_search:
                    sonuc = web_search(match_search.group(1).strip())
                    gonderilecek_mesajlar.append({"role": "user", "content": f"[ARAMA SONUCU]:\n{sonuc}"})
                elif match_health:
                    sonuc = fetch_climate_health_api(match_health.group(1).strip())
                    gonderilecek_mesajlar.append({"role": "user", "content": f"[SAĞLIK VERİSİ]:\n{sonuc}"})
                elif match_aqi:
                    sonuc = get_air_quality(match_aqi.group(1).strip())
                    gonderilecek_mesajlar.append({"role": "user", "content": sonuc})
                elif match_memory:
                    sonuc = hafizada_ara(match_memory.group(1).strip())
                    gonderilecek_mesajlar.append({"role": "user", "content": f"[HAFIZA VERİSİ]:\n{sonuc}"})
                elif match_read:
                    sonuc = read_webpage(match_read.group(1).strip())
                    gonderilecek_mesajlar.append({"role": "user", "content": f"[SAYFA İÇERİĞİ]:\n{sonuc}"})
                continue
            else:
                cevap_alani.markdown(tam_cevap)
                break

        st.session_state.mesajlar.append({"role": "assistant", "content": tam_cevap})
        st.rerun()