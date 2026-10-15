import os
import sys
import json
import threading
import multiprocessing
import importlib.util
import time
import requests
import urllib3
import uuid
import re
import socket
import zipfile
import io
import hashlib
import ast
import ssl
import ctypes
from datetime import datetime
import customtkinter as ctk
import tkinter as tk
import ollama
from tkinter import messagebox, filedialog
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from dotenv import load_dotenv

# =========================================================
# MODÜL 1: WEB & NASA SCRAPER KÖPRÜSÜ
# =========================================================
try:
    from nasa_scraper import NasaScraperWindow

    NASA_SCRAPER_AVAILABLE = True
except ImportError:
    NASA_SCRAPER_AVAILABLE = False


# =========================================================
# MODÜL 2: WORD PROGRAMI.PY (ALTAR BELGE) DIŞARIDAN IMPORT KÖPRÜSÜ
# =========================================================
def _word_editor_surecini_baslat(baslangic_metni: str = ""):
    """
    PyQt6 tabanlı 'Word Programı.py' dosyasını CustomTkinter ile çakışmaması için
    bağımsız bir süreçte (Process) import eder ve TAM EKRAN (Maximized) başlatır.
    """
    try:
        ana_dizin = os.path.dirname(os.path.abspath(__file__))
        olasi_isimler = ["Word Programı.py", "word_programi.py", "AltarEditorPro.py"]
        hedef_dosya = None

        for isim in olasi_isimler:
            tam_yol = os.path.join(ana_dizin, isim)
            if os.path.exists(tam_yol):
                hedef_dosya = tam_yol
                break

        if not hedef_dosya:
            return

        spec = importlib.util.spec_from_file_location("word_programi_modulu", hedef_dosya)
        word_modulu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(word_modulu)

        from PyQt6.QtWidgets import QApplication
        app = QApplication(sys.argv)
        pencere = word_modulu.AltarEditorPro()

        if baslangic_metni and baslangic_metni.strip():
            pencere.editor.setPlainText(baslangic_metni)
            pencere.not_defteri.setPlainText(
                f"Bu belge Altar sisteminden ({datetime.now().strftime('%d.%m.%Y %H:%M')}) aktarıldı."
            )

        # Her zaman tam ekran (Maximized) olarak aç
        pencere.showMaximized()
        sys.exit(app.exec())
    except Exception as e:
        print(f"[!] Altar Belge başlatma hatası: {e}")


# =========================================================
# KÜTÜPHANE VE DONANIM TELEMETRİ KONTROLLERİ
# =========================================================
try:
    from PIL import Image

    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False

try:
    import speech_recognition as sr

    STT_AVAILABLE = True
except ImportError:
    STT_AVAILABLE = False

try:
    import pymupdf as fitz

    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    import docx

    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi

    YOUTUBE_AVAILABLE = True
except ImportError:
    YOUTUBE_AVAILABLE = False

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# Salt-Okunur GPU Kullanım Okuyucu (Ek Kütüphane Gerektirmez, NVML DLL Okur)
class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class SafeGPUReader:
    def __init__(self):
        self.nvml_lib = None
        self.handle = ctypes.c_void_p()
        self.aktif = False
        self._baslat()

    def _baslat(self):
        olasi_dll_yollari = [
            "nvml.dll",
            r"C:\Windows\System32\nvml.dll",
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll"
        ]
        for yol in olasi_dll_yollari:
            try:
                lib = ctypes.WinDLL(yol)
                if lib.nvmlInit_v2() == 0:
                    if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self.handle)) == 0:
                        self.nvml_lib = lib
                        self.aktif = True
                        break
            except Exception:
                continue

    def gpu_yuzdesi_oku(self, ollama_client=None) -> int:
        if self.aktif and self.nvml_lib:
            try:
                util = _NvmlUtilization()
                if self.nvml_lib.nvmlDeviceGetUtilizationRates(self.handle, ctypes.byref(util)) == 0:
                    return int(util.gpu)
            except Exception:
                pass

        # Yedek: Ollama üzerinde aktif model varsa VRAM yük oranını döndür
        if ollama_client:
            try:
                ps_data = ollama_client.ps()
                models = ps_data.get("models", [])
                if models:
                    size = models[0].get("size", 1) or 1
                    vram = models[0].get("size_vram", 0) or 0
                    return min(100, int((vram / size) * 100))
            except Exception:
                pass
        return 0


# =========================================================

# Ağ filtreleri ve SSL sertifika hatalarını devre dışı bırakır
try:
    ssl._create_default_https_context = ssl._create_unverified_context
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except AttributeError:
    pass

# Vektörel Hafıza (Anlamsal Arama) için ChromaDB
try:
    import chromadb

    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

# API modelleri için gerekli Google GenAI kütüphaneleri
from google import genai
from google.genai import types

# Windows terminalinin özel karakterlerde çökmesini engeller
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

load_dotenv()
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

GEMİNİ_API_KEY = os.getenv("GEMINI_API_KEY", "")


# =========================================================
# GÜVENLİK KALKANI & STATİK DOĞRULAYICILAR (SALT-OKUNUR)
# =========================================================
def guvenlik_taramasi_yap(metin: str) -> str:
    tehlikeli_desenler = [
        r"rm\s+-rf\s+/", r"os\.system\(", r"subprocess\.Popen\(", r"subprocess\.call\(",
        r"nc\s+-e", r"bash\s+-i", r"mkfifo", r"eval\(", r"exec\(",
        r"__import__\('os'\)", r"pty\.spawn", r"base64\.b64decode\("
    ]

    bulunan_tehditler = []
    for desen in tehlikeli_desenler:
        if re.search(desen, metin, re.IGNORECASE):
            bulunan_tehditler.append(desen.replace('\\', '').replace('(', ''))

    if bulunan_tehditler:
        tehdit_listesi = ", ".join(bulunan_tehditler)
        return (f"\n\n[🚨 KRİTİK GÜVENLİK UYARISI 🚨]\n"
                f"Altar'ın ürettiği veya internetten çektiği bu kodda şüpheli/sisteme müdahale eden komutlar tespit edildi: [{tehdit_listesi}]\n"
                f"Lütfen bu kodu kendi işletim sisteminizde doğrudan ÇALIŞTIRMAYIN. İncelemek için Sanal Makine (VM) kullanın!\n")
    return ""


def ast_python_kontrolu(metin: str) -> str:
    """Üretilen Python kod bloklarını ÇALIŞTIRMADAN (statik olarak) SyntaxError açısından test eder."""
    kod_bloklari = re.findall(r'```python\s*(.*?)```', metin, re.DOTALL)
    hatalar = []
    for i, kod in enumerate(kod_bloklari, 1):
        try:
            ast.parse(kod)
        except SyntaxError as e:
            hatalar.append(f"  • Kod Bloğu #{i} içinde Sözdizimi Hatası (Satır {e.lineno}): {e.msg}")

    if hatalar:
        return "\n[🔍 STATİK PYTHON KOD DENETÇİSİ UYARISI]\n" + "\n".join(hatalar) + "\n"
    return ""


def gcode_safety_analyzer(metin: str) -> str:
    """Metin içindeki G-Code satırlarını bellekte tarayarak eksen sınırlarını (Min/Max X,Y,Z) ve çarpışma risklerini çıkarır."""
    x_vals, y_vals, z_vals, f_vals, s_vals = [], [], [], [], []
    uyarilar = []
    gcode_komut_sayisi = 0

    satirlar = metin.splitlines()
    for i, satir in enumerate(satirlar, 1):
        temiz = re.sub(r'\(.*?\)', '', satir).split(';')[0].upper().strip()
        if not temiz:
            continue

        if re.match(r'^(N\d+\s*)?[GM]\d+', temiz):
            gcode_komut_sayisi += 1
            for eksen, liste in [('X', x_vals), ('Y', y_vals), ('Z', z_vals), ('F', f_vals), ('S', s_vals)]:
                eslesme = re.search(rf'{eksen}([-+]?\d*\.?\d+)', temiz)
                if eslesme:
                    try:
                        liste.append(float(eslesme.group(1)))
                    except ValueError:
                        pass

            if ("G0 " in temiz or "G00" in temiz) and "Z-" in temiz:
                uyarilar.append(
                    f"Satır {i}: G00 (boşta hızlı ilerleme) ile Z- (parça içine) hareket tespit edildi! Çarpışma riski: '{temiz}'")

    if gcode_komut_sayisi < 3 or not (x_vals or y_vals or z_vals):
        return ""

    rapor = "\n[⚙️ CNC G-CODE TELEMETRİ VE SINIR RAPORU]\n"
    if x_vals:
        rapor += f"  • X Ekseni Sınırları: Min {min(x_vals)} mm | Max {max(x_vals)} mm\n"
    if y_vals:
        rapor += f"  • Y Ekseni Sınırları: Min {min(y_vals)} mm | Max {max(y_vals)} mm\n"
    if z_vals:
        rapor += f"  • Z Ekseni (Derinlik): Min {min(z_vals)} mm | Max {max(z_vals)} mm\n"
    if s_vals:
        rapor += f"  • Maksimum İş Mili Devri (S): {max(s_vals):.0f} RPM\n"
    if f_vals:
        rapor += f"  • Maksimum İlerleme (F): {max(f_vals):.1f} mm/dk\n"

    if uyarilar:
        rapor += "  ⚠️ KRİTİK TEZGAH UYARILARI:\n    - " + "\n    - ".join(uyarilar[:5]) + "\n"
    else:
        rapor += "  ✅ Hızlı dalış (G00 Z-) çakışması tespit edilmedi.\n"
    return rapor


# =========================================================
# İNTERNET VE SALT-OKUNUR ANALİZ ARAÇLARI
# =========================================================
def get_youtube_transcript(url: str) -> str:
    if not YOUTUBE_AVAILABLE:
        return "[!] 'youtube-transcript-api' kütüphanesi eksik. Terminalden yükleyin."
    try:
        video_id = ""
        if "v=" in url:
            video_id = url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            video_id = url.split("youtu.be/")[1].split("?")[0]
        else:
            return "[!] Geçerli bir YouTube URL'si bulunamadı."

        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript(['tr', 'en']).fetch()
        except Exception:
            transcript = transcript_list.find_generated_transcript(['tr', 'en']).fetch()

        metin = " ".join([t['text'] for t in transcript])
        return f"[YOUTUBE VİDEO DÖKÜMÜ]:\n{metin[:8000]}"
    except Exception as e:
        return f"[!] YouTube metni çekilemedi: {e}"


def safe_network_scan(target: str) -> str:
    target = target.replace("http://", "").replace("https://", "").replace("/", "").split(":")[0]
    sonuc = f"--- [{target}] İÇİN GÜVENLİ AĞ VE HEDEF ANALİZİ ---\n"
    try:
        ip = socket.gethostbyname(target)
        sonuc += f"Hedef IP Adresi: {ip}\n"
        try:
            ip_data = requests.get(f"https://ipapi.co/{ip}/json/", timeout=5).json()
            sonuc += f"Sunucu Konumu: {ip_data.get('city', 'Bilinmiyor')}, {ip_data.get('country_name', 'Bilinmiyor')}\n"
            sonuc += f"ISP/Sağlayıcı: {ip_data.get('org', 'Bilinmiyor')}\n"
        except Exception:
            pass

        acik_portlar = []
        for port in [21, 22, 80, 443, 3306, 8080]:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            if sock.connect_ex((ip, port)) == 0:
                acik_portlar.append(str(port))
            sock.close()

        if acik_portlar:
            sonuc += f"Tespit Edilen Açık Servis Portları: {', '.join(acik_portlar)}\n"
        else:
            sonuc += "Aktif/Açık standart servis portu bulunamadı (veya güvenlik duvarı arkasında).\n"

        return sonuc
    except Exception as e:
        return f"[!] Ağ analizi başarısız oldu: {e}"


def passive_ssl_header_audit(target: str) -> str:
    """Hedefe tek bir standart HTTPS isteği atarak SSL ömrünü ve güvenlik başlıklarını salt-okunur denetler."""
    domain = target.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0].strip()
    rapor = f"--- [{domain}] PASİF SSL VE GÜVENLİK BAŞLIĞI DENETİMİ ---\n"

    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                bitis_str = cert.get('notAfter', 'Bilinmiyor')
                issuer = dict(x[0] for x in cert.get('issuer', []))
                rapor += f"[+] SSL Sağlayıcı: {issuer.get('organizationName', 'Bilinmiyor')}\n"
                rapor += f"[+] Sertifika Bitiş Tarihi: {bitis_str}\n"
    except Exception as e:
        rapor += f"[-] SSL Sertifikası doğrulanamadı veya 443 portu kapalı: {e}\n"

    try:
        headers_req = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(f"https://{domain}", headers=headers_req, timeout=6, verify=False)
        headers = res.headers
        kritik_basliklar = [
            "Strict-Transport-Security",
            "Content-Security-Policy",
            "X-Frame-Options",
            "X-Content-Type-Options",
            "Referrer-Policy"
        ]
        eksikler = [h for h in kritik_basliklar if h not in headers]
        mevcutlar = [h for h in kritik_basliklar if h in headers]

        rapor += f"[+] Mevcut Korumalar: {', '.join(mevcutlar) if mevcutlar else 'Yok'}\n"
        rapor += f"[!] Eksik Güvenlik Başlıkları: {', '.join(eksikler) if eksikler else 'Tamamı Mevcut'}\n"
    except Exception as e:
        rapor += f"[-] HTTP başlıkları okunamadı: {e}\n"

    return rapor


def passive_subdomain_osint(domain: str) -> str:
    """Hedef sunucuya hiç dokunmadan, halka açık crt.sh SSL şeffaflık kayıtlarından alt alan adlarını bulur."""
    temiz_domain = domain.replace("http://", "").replace("https://", "").split("/")[0].strip()
    try:
        url = f"https://crt.sh/?q=%.{temiz_domain}&output=json"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            kayitlar = res.json()
            alt_alanlar = set()
            for k in kayitlar:
                isim = k.get("name_value", "")
                for satir in isim.splitlines():
                    if "*" not in satir:
                        alt_alanlar.add(satir.strip().lower())
            sirali = sorted(list(alt_alanlar))[:40]
            if sirali:
                return f"--- [{temiz_domain}] PASİF SERTİFİKA ŞEFFAFLIĞI (ALT ALAN ADI) KAYITLARI ---\n" + "\n".join(
                    [f"  • {s}" for s in sirali]
                )
            return f"[!] '{temiz_domain}' için halka açık alt alan adı kaydı bulunamadı."
        return f"[!] crt.sh servisi yanıt vermedi (Durum: {res.status_code})."
    except Exception as e:
        return f"[!] Pasif alt alan adı sorgusu başarısız: {e}"


def check_file_hash_and_reputation(filepath: str) -> str:
    """Dosyayı ÇALIŞTIRMADAN ve DEĞİŞTİRMEDEN ('rb' salt-okunur kipte) SHA-256 değerini hesaplar ve MalwareBazaar'da sorgular."""
    filepath = filepath.strip().strip('"').strip("'")
    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        return f"[!] Dosya bulunamadı: {filepath}"

    try:
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        digest = sha256_hash.hexdigest()
        boyut_kb = os.path.getsize(filepath) / 1024

        sonuc = "--- YEREL DOSYA BÜTÜNLÜK VE GÜVENLİK ANALİZİ (SALT-OKUNUR) ---\n"
        sonuc += f"Dosya: {os.path.basename(filepath)} ({boyut_kb:.1f} KB)\nSHA-256: {digest}\n"

        res = requests.post("https://mb-api.abuse.ch/api/v1/", data={"query": "get_info", "hash": digest}, timeout=6)
        if res.status_code == 200:
            data = res.json()
            if data.get("query_status") == "ok":
                bilgi = data["data"][0]
                sonuc += "[🚨 TEHLİKE TESPİT EDİLDİ] Bu dosya bilinen bir zararlı yazılımdır!\n"
                sonuc += f"İmza/Tür: {bilgi.get('signature', 'Bilinmiyor')} | Etiketler: {bilgi.get('tags', [])}\n"
            else:
                sonuc += "[+] MalwareBazaar veritabanında bu SHA-256 ile eşleşen bilinen bir zararlı kaydı bulunamadı.\n"
        return sonuc
    except Exception as e:
        return f"[!] Hash hesaplama hatası: {e}"


def get_cyber_rss() -> str:
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get("https://feeds.feedburner.com/TheHackersNews", headers=headers, timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        items = soup.find_all('item')[:5]
        out = "--- GÜNCEL SİBER GÜVENLİK HABERLERİ VE ZAAFİYETLER ---\n"
        for item in items:
            title = item.title.text if item.title else "Başlık Yok"
            desc = item.description.text if item.description else "Açıklama Yok"
            out += f"\n{title}\n  Özet: {desc[:250]}...\n"
        return out
    except Exception as e:
        return f"[!] RSS haber akışı okunamadı: {e}"


def fetch_cve_details(cve_id: str) -> str:
    cve_id = cve_id.strip().upper()
    if not cve_id.startswith("CVE-"):
        return "[!] Geçersiz format. Lütfen 'CVE-YYYY-NNNN' formatında girin."
    try:
        res = requests.get(f"https://cve.circl.lu/api/cve/{cve_id}", timeout=10)
        if res.status_code == 200 and res.json():
            data = res.json()
            ozet = data.get("summary", "Açıklama bulunamadı.")
            cvss = data.get("cvss", "Bilinmiyor")
            return f"[CVE DETAYLARI - {cve_id}]\nCVSS Skoru: {cvss}\nÖzet: {ozet}\nLütfen bu zafiyeti kapatacak güvenli kodu veya savunma mimarisini tasarla."
        else:
            ddgs = DDGS()
            sonuclar = list(ddgs.text(f"site:nvd.nist.gov {cve_id}", max_results=2))
            if sonuclar:
                return f"[NVD ARAMA SONUCU - {cve_id}]\n{sonuclar[0]['body']}\nLütfen bu bilgiye göre güvenli yama (patch) yöntemleri geliştir."
            return "[!] Bu zafiyet koduna dair detay bulunamadı."
    except Exception as e:
        return f"[!] CVE araması başarısız: {e}"


def test_rest_api(istek: str) -> str:
    try:
        parcalar = istek.strip().split(" ", 1)
        method = parcalar[0].upper()
        url = parcalar[1] if len(parcalar) > 1 else ""
        if method not in ["GET", "POST"] or not url.startswith("http"):
            return "[!] Geçersiz API isteği. Format: 'GET https://api.site.com' olmalı."

        headers = {'User-Agent': 'Altar-Security-Agent/1.0'}
        res = requests.request(method, url, headers=headers, timeout=10)
        kisaltilmis_yanit = res.text[:2000]
        return f"[API YANITI - {method} {url} Durum: {res.status_code}]\n{kisaltilmis_yanit}\n\nLütfen bu JSON/Metin yanıtını analiz ederek kodunu optimize et."
    except Exception as e:
        return f"[!] API İsteği başarısız oldu: {e}"


def clone_github_repo_to_memory(url: str, db_manager) -> str:
    try:
        parcalar = url.replace("https://github.com/", "").strip("/").split("/")
        if len(parcalar) < 2:
            return "[!] Geçersiz GitHub linki."

        owner, repo = parcalar[0], parcalar[1]
        api_url = f"https://api.github.com/repos/{owner}/{repo}/zipball/main"
        headers = {'User-Agent': 'Altar-Agent'}

        res = requests.get(api_url, headers=headers, timeout=15)
        if res.status_code != 200:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/zipball/master"
            res = requests.get(api_url, headers=headers, timeout=15)
            if res.status_code != 200:
                return f"[!] Repo indirilemedi (Durum: {res.status_code})."

        islenen_dosya = 0
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            izin_verilen_uzantilar = ['.py', '.c', '.cpp', '.h', '.js', '.html', '.java', '.md', '.txt', '.json',
                                      '.yml', '.yaml']
            for dosya_adi in z.namelist():
                if any(dosya_adi.endswith(ext) for ext in izin_verilen_uzantilar):
                    try:
                        icerik = z.read(dosya_adi).decode('utf-8')
                        if not icerik.strip():
                            continue

                        chunk_size = 2000
                        chunks = [icerik[i:i + chunk_size] for i in range(0, len(icerik), chunk_size)]
                        for i, chunk in enumerate(chunks):
                            veri = f"GITHUB REPO: {repo}\nDOSYA: {dosya_adi}\nBÖLÜM: {i + 1}\nKOD/METİN:\n{chunk}"
                            db_manager.mesaj_kaydet("document", veri)
                        islenen_dosya += 1
                    except Exception:
                        pass

        if islenen_dosya > 0:
            return f"[BAŞARILI] '{repo}' reposundaki {islenen_dosya} adet kaynak kod dosyası RAG (Vektörel) Hafızasına gömüldü. Bu projedeki fonksiyonlar ve mimari hakkında sorular sorabilirsiniz."
        else:
            return "[!] Repoda desteklenen ve okunabilir kod dosyası bulunamadı."
    except Exception as e:
        return f"[!] Repo hafızaya alınırken hata oluştu: {e}"


def osint_directory_scan(target: str) -> str:
    target = target.replace("http://", "").replace("https://", "").strip("/")
    base_url = f"http://{target}"
    paths = ["/robots.txt", "/.env", "/sitemap.xml", "/admin", "/login", "/wp-login.php"]
    out = f"--- [{target}] İÇİN PASİF OSINT VE DİZİN KEŞFİ ---\n"
    found_something = False
    headers = {'User-Agent': 'Mozilla/5.0'}

    for path in paths:
        try:
            res = requests.get(base_url + path, headers=headers, timeout=3, verify=False)
            if res.status_code == 200:
                out += f"[AÇIK/BULUNDU] {path} (Durum: 200 OK)\n"
                if "robots.txt" in path or "sitemap" in path:
                    out += f"  İçerik Özeti: {res.text[:200]}...\n"
                found_something = True
            elif res.status_code in [401, 403]:
                out += f"[KORUMALI] {path} (Durum: {res.status_code} Erişim Engellendi)\n"
                found_something = True
        except Exception:
            pass

    if not found_something:
        out += "Gizli veya standart dizin bulunamadı.\n"
    return out


def fetch_latest_docs(lib_name: str) -> str:
    try:
        ddgs = DDGS()
        query = f"{lib_name} documentation latest official"
        results = list(ddgs.text(query, max_results=2))
        if results:
            url = results[0].get('href')
            out = f"--- '{lib_name}' İÇİN GÜNCEL DOKÜMANTASYON ({url}) ---\n"
            icerik = read_webpage(url, max_chunk_size=4000)
            out += icerik
            return out
        return f"[!] '{lib_name}' için resmi dokümantasyon bulunamadı."
    except Exception as e:
        return f"[!] Dokümantasyon arama hatası: {e}"


def fetch_nasa_api(query: str) -> str:
    try:
        url = f"https://images-api.nasa.gov/search?q={query}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            items = data.get("collection", {}).get("items", [])[:4]
            if not items:
                return "[!] NASA API'de bu sorguyla ilgili güncel veri/araştırma bulunamadı."
            out = f"--- NASA API (AÇIK UZAY VERİLERİ) SONUÇLARI ('{query}') ---\n"
            for item in items:
                info = item.get("data", [{}])[0]
                title = info.get("title", "Başlık Yok")
                desc = info.get("description", "Açıklama Yok")[:600]
                out += f"🚀 {title}\n📝 Özet: {desc}...\n\n"
            return out
        return f"[!] NASA API bağlantı reddi. (Durum: {res.status_code})"
    except Exception as e:
        return f"[!] NASA API arama hatası: {e}"


# =========================================================
# ÇEVRİMİÇİ BULUT MOTORU (FNSIntelligence)
# =========================================================
class FNSIntelligence:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.internet_baglantisi_aktif = True
        self.hazir_mi = False
        self.sistem_hatasi = ""
        self.model_id = "Bekleniyor..."

        try:
            self.client = genai.Client(api_key=self.api_key)
            self.varsayilan_sistem_talimati = (
                "Sen Altar ekosisteminin üst düzey Çevrimiçi Zekasısın. Karşındaki kullanıcı Faruk Emir. "
                "Görevin, her türlü alanda (bilim, tıp, tarih, günlük veriler vb.) en doğru, net ve kapsamlı "
                "bilgiyi sunmaktır. Gereksiz askeri veya siber jargonlardan kaçın, sorulan konunun "
                "doğasına uygun, son derece zeki ve vizyoner bir uzman gibi davran."
            )
            self.hazir_mi = True
            print("[SİSTEM] Çevrimiçi AI Çekirdeği Başlatıldı. Dinamik Rol Alma Bekleniyor...")

        except Exception as e:
            self.hazir_mi = False
            self.sistem_hatasi = str(e)
            print(f"[!] KRİTİK HATA: AI Motoru başlatılamadı: {self.sistem_hatasi}")

    def siber_radar_modelleri_getir(self):
        dinamik_modeller = {}
        try:
            print("[SİSTEM] Radar aktif. Yetkili API modelleri taranıyor...")
            for model in self.client.models.list():
                actions = getattr(model, 'supported_actions', [])
                name = model.name

                if "generateContent" in actions and "gemini" in name.lower():
                    gecersiz_modeller = [
                        "tts", "image", "omni", "computer-use", "customtools", "transcribe",
                        "2.5-pro", "2.5-flash", "3.1-", "3.5-", "3.6-flash", "3.7-", "3.8-flash",
                        "3-flash-preview", "latest"
                    ]

                    if any(gecersiz in name.lower() for gecersiz in gecersiz_modeller):
                        continue

                    if "lite" in name.lower():
                        avantaj = "Hafif, çok hızlı ve düşük kaynak tüketimi."
                        renk = "#00FF00"
                    elif "pro" in name.lower():
                        avantaj = "Derin muhakeme, üst düzey siber analiz."
                        renk = "#FF00FF"
                    elif "flash" in name.lower():
                        avantaj = "Hız ve zeka dengesi. En verimli operasyon."
                        renk = "#00AAFF"
                    else:
                        avantaj = "Standart Model."
                        renk = "#FFFFFF"

                    dinamik_modeller[name] = {
                        "avantaj": avantaj,
                        "dezavantaj": "Kota sınırları Google tarafından belirlenir.",
                        "limit": "Hesap seviyesine göre dinamiktir.",
                        "renk": renk
                    }
            print(f"[SİSTEM] Radar tamamlandı. {len(dinamik_modeller)} adet aktif API modeli bulundu.")
            return dinamik_modeller
        except Exception as e:
            print(f"[!] Radar Hatası: {e}")
            return {}

    def model_degistir(self, yeni_model_id: str):
        self.model_id = yeni_model_id

    def baglanti_anahtari(self, durum: bool):
        self.internet_baglantisi_aktif = durum
        return f"[SİSTEM] Dış Ağ Tüneli: {'AKTİF' if durum else 'İZOLASYONDA'}"

    def soru_sor(self, kullanici_mesaji: str, not_icerigi: str = "", dinamik_kimlik: str = None,
                 resim_yolu: str = None) -> str:
        if not self.internet_baglantisi_aktif:
            return "[!] GÜVENLİK DUVARI: Sistem izole modda. Veri çıkışı engellendi."
        if not self.hazir_mi:
            return f"[!] SİSTEM HATASI: AI Motoru aktif değil. Hata: {self.sistem_hatasi}"

        try:
            prompt_icerigi = kullanici_mesaji
            if not_icerigi:
                prompt_icerigi = f"KASA VERİSİ (ANALİZ EDİLECEK):\n{not_icerigi}\n\nKOMUT: {kullanici_mesaji}"

            aktif_talimat = dinamik_kimlik if dinamik_kimlik else self.varsayilan_sistem_talimati

            gonderilecek_icerik = [prompt_icerigi]
            if resim_yolu and VISION_AVAILABLE:
                gonderilecek_icerik.append(Image.open(resim_yolu))

            response = self.client.models.generate_content(
                model=self.model_id,
                contents=gonderilecek_icerik,
                config=types.GenerateContentConfig(
                    system_instruction=aktif_talimat,
                    temperature=0.3,
                    tools=[{'google_search': {}}]
                )
            )
            return response.text if response.text else "[!] Sunucudan boş yanıt döndü."

        except Exception as e:
            hata_mesaji = str(e)
            if "429" in hata_mesaji or "RESOURCE_EXHAUSTED" in hata_mesaji:
                return "[!] KOTA DOLDU: Google API dakikalık/günlük limitine takıldınız."
            elif "404" in hata_mesaji or "NOT_FOUND" in hata_mesaji:
                return f"[!] KULLANIMDAN KALDIRILDI: Seçtiğiniz model ('{self.model_id}') kullanımdan kaldırıldı."
            return f"[!] BAĞLANTI HATASI: Siber tünelde kopukluk. Detay: {hata_mesaji}"


# =========================================================
# %100 VEKTÖREL (CHROMADB) VERİTABANI MOTORU
# =========================================================
class FNSDatabaseManager:
    def __init__(self):
        self.ana_klasor = os.path.dirname(os.path.abspath(__file__))
        self.data_klasoru = os.path.join(self.ana_klasor, "data")
        self._kasa_hazirla()

        self.vektor_aktif = False
        if CHROMA_AVAILABLE:
            try:
                self.chroma_client = chromadb.PersistentClient(path=os.path.join(self.data_klasoru, "chroma_memory"))
                self.collection = self.chroma_client.get_or_create_collection(name="altar_semantic_memory")
                self.vektor_aktif = True
                print("[SİSTEM] Vektörel Hafıza (ChromaDB) Başarıyla Yüklendi. Anlamsal Arama Aktif!")
            except Exception as e:
                print(f"[!] Vektör Veritabanı başlatılamadı: {e}")
        else:
            print("[!] SİSTEM HATASI: ChromaDB yüklü değil. Hafıza kapalı!")

    def _kasa_hazirla(self):
        if not os.path.exists(self.data_klasoru):
            os.makedirs(self.data_klasoru)

    def mesaj_kaydet(self, role: str, content: str):
        if self.vektor_aktif:
            try:
                mesaj_id = str(uuid.uuid4())
                tarih = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                has_code = bool(re.search(r'```.*?```', content, re.DOTALL))
                temiz_icerik = re.sub(r'<düşünce>.*?</düşünce>', '', content, flags=re.DOTALL).strip()
                if not temiz_icerik:
                    temiz_icerik = content

                self.collection.add(
                    documents=[temiz_icerik],
                    metadatas=[{"role": role, "timestamp": tarih, "has_code": has_code}],
                    ids=[mesaj_id]
                )
            except Exception as e:
                print(f"[!] Vektör kaydı başarısız: {e}")

    def otomatik_hafiza_tarama(self, kelime: str, distance_threshold: float = 1.3) -> str:
        if self.vektor_aktif:
            try:
                results = self.collection.query(
                    query_texts=[kelime],
                    n_results=2
                )

                if not results['documents'] or not results['documents'][0]:
                    return ""

                anilar = []
                distances = results.get('distances', [[10.0, 10.0]])[0]
                documents = results['documents'][0]
                metadatas = results['metadatas'][0]

                for i in range(len(documents)):
                    if distances[i] < distance_threshold:
                        rol = metadatas[i]['role']
                        anilar.append(f"[{rol.upper()}]: {documents[i]}")

                if anilar:
                    return "[OTOMATİK GEÇMİŞ HAFIZA HATIRLATMASI - BU BİLGİLERİ GİZLİCE BAĞLAM OLARAK KULLAN]:\n" + "\n\n".join(
                        anilar)
                return ""
            except Exception:
                return ""
        return ""

    def hafiza_ara(self, kelime: str, role_filter: str = None) -> str:
        if self.vektor_aktif:
            try:
                where_clause = {"role": role_filter} if role_filter else None
                results = self.collection.query(
                    query_texts=[kelime],
                    n_results=5,
                    where=where_clause
                )

                if not results['documents'] or not results['documents'][0]:
                    return "Bu konuyla veya anlamsal olarak benzer bir geçmiş kayıt bulunamadı."

                formatli_sonuc = "[VEKTÖREL (ANLAMSAL) ARAMA SONUÇLARI]:\n"
                for i, doc in enumerate(results['documents'][0]):
                    rol = results['metadatas'][0][i]['role']
                    tarih = results['metadatas'][0][i].get('timestamp', 'Bilinmeyen Tarih')
                    rol_tr = "Belge (RAG)" if rol == "document" else ("Kullanıcı" if rol == "user" else "Asistan (Sen)")
                    formatli_sonuc += f"[{tarih}] --- {rol_tr} ---\n{doc}\n\n"
                return formatli_sonuc

            except Exception as e:
                return f"Vektörel arama sırasında hata oluştu: {e}"
        return "[!] Vektörel hafıza aktif değil."


# =========================================================
# DOKÜMANTASYON HEDEF HARİTASI VE MÜHENDİSLİK PROFİLLERİ
# =========================================================
DOCS_MAP = {
    "NASA Yanma Analizi": "site:ntrs.nasa.gov OR site:nasa.gov",
    "Genel (Serbest Arama)": "",
    "GitHub (Açık Kaynak)": "site:github.com",
    "Python": "site:docs.python.org",
    "C": "site:en.cppreference.com/w/c",
    "C++": "site:en.cppreference.com/w/cpp",
    "C# (.NET)": "site:learn.microsoft.com/en-us/dotnet",
    "JavaScript (MDN)": "site:developer.mozilla.org",
    "Java": "site:docs.oracle.com",
    "Rust": "site:doc.rust-lang.org",
    "G-Code / CNC": "",
    "Ağ Analizi": ""
}


# =========================================================
# ARAÇLAR (TOOL CALLING) - İNTERNET ERİŞİMİ VE SCRAPING
# =========================================================
def web_search(query: str) -> str:
    try:
        ddgs = DDGS()
        arama_sonuclari = list(ddgs.text(query, max_results=8))

        if not arama_sonuclari:
            return "İnternette bu konuyla ilgili güncel bir sonuç bulunamadı."

        kapsamli_bilgi = f"Arama Sorgusu: '{query}'\n\n--- ÖZET SONUÇLAR ---\n"

        for sonuc in arama_sonuclari:
            kapsamli_bilgi += f"- {sonuc.get('title')}: {sonuc.get('body')}\n"

        kapsamli_bilgi += "\n--- DETAYLI KAYNAK OKUMALARI ---\n"

        for sonuc in arama_sonuclari[:4]:
            site_linki = sonuc.get('href')
            site_basligi = sonuc.get('title')

            try:
                sayfa_icerigi = read_webpage(site_linki)
                kisaltilmis_icerik = sayfa_icerigi[:3000]
                kapsamli_bilgi += f"[{site_basligi}] ({site_linki}) İÇERİĞİ:\n{kisaltilmis_icerik}...\n\n"
            except Exception:
                kapsamli_bilgi += f"[{site_basligi}] ({site_linki}): Sayfa içeriği okunamadı.\n\n"

        return kapsamli_bilgi

    except Exception as e:
        return f"Arama sırasında hata oluştu: {str(e)}"


def read_webpage(url: str, max_chunk_size: int = 7000) -> str:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    try:
        if "github.com" in url and "/blob/" not in url and "/tree/" not in url and url.count("/") >= 4:
            url_readme = url.rstrip('/') + "/blob/main/README.md"
            url = url_readme

        if "github.com" in url and "/blob/" in url:
            url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        if "raw.githubusercontent" in url or "text/plain" in response.headers.get('Content-Type', ''):
            text = response.text
        else:
            soup = BeautifulSoup(response.text, 'html.parser')

            ana_icerik = soup.find('article') or soup.find('main') or soup.find('div', class_='markdown-body')
            if ana_icerik:
                soup = ana_icerik

            for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
                script.extract()
            text = soup.get_text(separator='\n', strip=True)

        if len(text) > max_chunk_size:
            return text[
                   :max_chunk_size] + "\n\n[SİSTEM UYARISI: İçerik çok uzundu, sistemin kararlılığını korumak için metin otomatik kırpıldı.]"

        return text
    except Exception as e:
        if "main/README.md" in url:
            try:
                url_master = url.replace("main/README.md", "master/README.md")
                res = requests.get(url_master, headers=headers, timeout=5)
                if res.status_code == 200:
                    return res.text[:max_chunk_size]
            except Exception:
                pass
        return f"Sayfa okunamadı: {str(e)}"


class AltarMainUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        # Pencere başlığı sağa/ortaya kaydırılmış şekilde 'Altar' olarak ayarlandı
        self.title(" " * 85 + "Altar")
        self.geometry("1250x780")
        self.after(0, lambda: self.state('zoomed'))

        self.ekli_resim_yolu = None
        self.nasa_sim_aktif = False
        self.son_kazinan_paket = None
        self.gpu_reader = SafeGPUReader()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---------------- OLLAMA YEREL ÇEKİRDEK BAĞLANTISI VE MODEL TESPİTİ ----------------
        self.yuklu_modeller = []
        try:
            self.client = ollama.Client(host='http://localhost:11434')
            modeller_ham = self.client.list().get('models', [])
            self.yuklu_modeller = [m['model'] for m in modeller_ham]

            if not self.yuklu_modeller:
                self.yuklu_modeller = ["Yüklü Model Bulunamadı"]
        except Exception:
            messagebox.showerror("Kritik Hata",
                                 "Ollama servisine bağlanılamadı! Lütfen Ollama'nın çalıştığından emin olun.")
            sys.exit(1)

        # ---------------- GOOGLE GENAI BULUT ÇEKİRDEK BAĞLANTISI (API) ----------------
        self.api_key = GEMİNİ_API_KEY

        if self.api_key and self.api_key.strip():
            self.api_engine = FNSIntelligence(api_key=self.api_key)
            if self.api_engine.hazir_mi:
                dinamik_api_modelleri = self.api_engine.siber_radar_modelleri_getir()
                self.api_modeller = list(dinamik_api_modelleri.keys()) if dinamik_api_modelleri else [
                    "API Model Bulunamadı"]
            else:
                self.api_modeller = ["Bağlantı Hatası"]
        else:
            self.api_engine = None
            self.api_modeller = ["API Anahtarı Bulunamadı (.env'yi kontrol et)"]

        self.db_manager = FNSDatabaseManager()
        self.gecmis = []

        master_prompt = (
            "Sen Altar sisteminin yetenekli, zeki ve özgür yapay zeka asistanı ve Kıdemli Yazılım Mühendisisin.\n\n"
            "=== KARAR VERME VE DÜŞÜNME SÜRECİ (Chain of Thought) ===\n"
            "Kullanıcıya nihai cevabı vermeden önce, planını ve çözüm adımlarını SADECE <düşünce> ve </düşünce> etiketleri arasına yaz. "
            "Nihai cevabını, kodlarını ve açıklamalarını ise bu etiketlerin DIŞINA, doğrudan kullanıcıya yönelik olarak yaz.\n\n"
            "=== KOD ÜRETİM VE KALİTE SINIRLARI (COGNITIVE LIMITS) ===\n"
            "Senin en yüksek kaliteli ve tutarlı kod üretme kapasiten tek seferde ortalama 100-200 satır aralığındadır. 250 satırı aşan monolitik bloklarda mantık hataları yapabilirsin. Bu riski önlemek için:\n"
            "1. Uzunluğu değil, DAİMA KALİTEYİ hedefle. Kodu en optimize ve temiz haliyle tasarla.\n"
            "2. Tüm dosyayı baştan yazdırmaya çalışma! Sadece değiştirdiğin sınıfı/fonksiyonu, kendi içinde eksiksiz ve çalışır durumda sun.\n\n"
            "=== GÜVENLİK VE ARAŞTIRMA PROTOKOLÜ ===\n"
            "1. Zararlı Yazılım (Malware) Filtresi: İnternetten veya GitHub'dan bulduğun kodları kullanıcıya sunmadan önce kontrol et. Sisteme zarar verecek tersine kabuk (reverse shell) veya silme komutları (rm -rf) varsa kullanıcıyı uyar ve güvenli savunma yöntemleri geliştir.\n"
            "2. Hedefli Sistem Taraması: Kullanıcının talebi üzerine zafiyet tespit edersen bunu yama (patch) üretmek için kullan.\n\n"
            "=== ÇALIŞMA MODLARI ===\n"
            "Kullanıcının talebine göre aşağıdaki modlardan birini seçerek hareket et:\n\n"
            "DURUM A - HATA DÜZELTME (BUG FIX): Hatayı bul, açıkla. Sadece hatalı kısmı değiştir. İskeleti koru.\n"
            "DURUM B - GELİŞTİRME VE İYİLEŞTİRME (FEATURE/REFACTOR): Kodu daha profesyonel, şık ve performanslı hale getirmek için özgürce tasarla.\n"
            "DURUM C - SOHBET, BİLGİ VE ANALİZ (Q&A): Eğer kullanıcı kod yazmanı açıkça istemiyorsa (sadece soru soruyor, mantığını anlamak istiyor veya araştırma yapıyorsa) ZORLA KOD YAZMA! Konuşma dilinde, açıklayıcı, net ve konuya odaklı bir metin/yanıt sun.\n\n"
            "HER DURUM İÇİN ORTAK KURALLAR:\n"
            "- Tembellik Yasaktır Ancak Odaklı Ol: '// buralar aynı kalacak' gibi işe yaramaz yer tutucular kullanma.\n"
            "- Uydurma Yasaktır: Hayali kütüphaneler icat etme."
        )

        self.model_kimlikleri = {
            "dolphin3:8b": master_prompt,
            "dolphin-llama3:8b": master_prompt,
            "dolphin-llama3:70b": master_prompt,
            "varsayilan": master_prompt
        }

        # =========================================================
        # ANA PENCERE TASARIMI
        # =========================================================
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=0, rowspan=2, sticky="nsew")

        # --- ÜST MENÜ BAR ---
        self.top_panel = ctk.CTkFrame(self.main_frame, height=55, corner_radius=0)
        self.top_panel.pack(side="top", fill="x", padx=10, pady=(8, 0))

        ctk.CTkLabel(self.top_panel, text="Yerel Model:", font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left", padx=(12, 4)
        )
        varsayilan_model = "fns-deepseek-uncensored:latest" if "fns-deepseek-uncensored:latest" in self.yuklu_modeller else \
            self.yuklu_modeller[0]
        self.active_model_var = ctk.StringVar(value=varsayilan_model)
        self.model_selector = ctk.CTkOptionMenu(
            self.top_panel,
            variable=self.active_model_var,
            values=self.yuklu_modeller,
            width=165
        )
        self.model_selector.pack(side="left", padx=4, pady=10)

        ctk.CTkLabel(self.top_panel, text="Hedef Dil/Profil:", font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left", padx=(10, 4)
        )
        self.active_lang_var = ctk.StringVar(value="NASA Yanma Analizi")
        self.lang_selector = ctk.CTkOptionMenu(
            self.top_panel,
            variable=self.active_lang_var,
            values=list(DOCS_MAP.keys()),
            width=165,
            fg_color="#4B0082"
        )
        self.lang_selector.pack(side="left", padx=4, pady=10)

        ctk.CTkLabel(self.top_panel, text="Motor:", font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left", padx=(10, 4)
        )
        self.motor_var = ctk.StringVar(value="Yerel (Ollama)")
        self.motor_selector = ctk.CTkOptionMenu(
            self.top_panel,
            variable=self.motor_var,
            values=["Yerel (Ollama)", "Bulut (API)"],
            width=125,
            fg_color="#b85c00",
            button_color="#8f4700",
            button_hover_color="#6e3700"
        )
        self.motor_selector.pack(side="left", padx=4, pady=10)

        ctk.CTkLabel(self.top_panel, text="API Modeli:", font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left", padx=(10, 4)
        )
        varsayilan_api = self.api_modeller[0] if self.api_modeller else "Bulunamadı"
        self.active_api_model_var = ctk.StringVar(value=varsayilan_api)
        self.api_model_selector = ctk.CTkOptionMenu(
            self.top_panel,
            variable=self.active_api_model_var,
            values=self.api_modeller,
            width=175,
            fg_color="#8b0000",
            button_color="#5c0000",
            button_hover_color="#3d0000"
        )
        self.api_model_selector.pack(side="left", padx=4, pady=10)

        # Sağ Üst: Gelişmiş CPU, GPU ve RAM Telemetri Göstergesi
        self.lbl_telemetri = ctk.CTkLabel(
            self.top_panel,
            text="CPU: %0 | GPU: %0 | RAM: %0 (0.0/0.0 GB)",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#00FF88"
        )
        self.lbl_telemetri.pack(side="right", padx=15)
        self.telemetri_guncelle()

        # --- ORTA EKRAN: SEKMELİ YAPI (SOHBET + KAZINAN VERİ + G-CODE 2D SİMÜLATÖR) ---
        self.tabview = ctk.CTkTabview(self.main_frame, corner_radius=8)
        self.tabview.pack(side="top", fill="both", expand=True, padx=10, pady=(4, 10))

        self.tab_sohbet = self.tabview.add("💬 Sohbet")
        self.tab_analiz = self.tabview.add("📊 Kazınan Veri & Analiz Merkezi")
        self.tab_gcode = self.tabview.add("📐 CNC G-Code 2D Simülatör")

        # 1. Sekme: Sohbet Ekranı ve Kapsamlı Sistem Rehberi
        self.chat_display = ctk.CTkTextbox(self.tab_sohbet, font=ctk.CTkFont(family="Consolas", size=14),
                                           wrap="word", fg_color="#1a1a1a")
        self.chat_display.pack(fill="both", expand=True)

        karsilama_rehberi = (
            "========================================================================================\n"
            "                   🚀 ALTAR YAPAY ZEKA VE MÜHENDİSLİK SİSTEMİNE HOŞ GELDİNİZ\n"
            "========================================================================================\n"
            "Merhaba! Altar; yerel (Ollama) ve bulut (Google Gemini API) yapay zeka modellerini, sınırsız\n"
            "vektörel hafızayı (ChromaDB RAG), pasif siber güvenlik araçlarını, web veri kazıma köprüsünü\n"
            "ve CNC G-Code simülasyonunu tek çatı altında birleştiren hibrit bir çalışma istasyonudur.\n\n"
            "🔹 1. MOTOR VE UZMANLIK PROFİLİ SEÇİMİ (ÜST MENÜ)\n"
            "   • Adım 1: 'Motor' menüsünden çevrimdışı çalışmak için 'Yerel (Ollama)', çevrimiçi Google\n"
            "     desteği için 'Bulut (API)' seçeneğini belirleyin.\n"
            "   • Adım 2: Kullanmak istediğiniz yerel modeli veya API modelini ilgili listeden seçin.\n"
            "   • Adım 3: 'Hedef Dil/Profil' menüsünden çalışacağınız alanı (NASA Yanma Analizi, G-Code / CNC,\n"
            "     Ağ Analizi, GitHub, Python, C++ vb.) seçin; yapay zeka kimliğini bu alana göre ayarlar.\n"
            "   • Sağ üst köşeden anlık CPU, GPU ve RAM (GB/%) kullanımınızı canlı takip edebilirsiniz.\n\n"
            "🔹 2. SOL ALT ARAÇLAR VE ÇOKLU ORTAM KULLANIMI\n"
            "   • 💾 Raporu Kaydet : Mevcut sohbet ve analiz geçmişinizi hiçbir dosyanın üzerine yazmadan\n"
            "                        güvenli (.md veya .txt) rapor olarak bilgisayarınıza kaydeder.\n"
            "   • 📝 Altar Belge   : Gelişmiş kelime işlemciyi tam ekran açar. İsterseniz o anki sohbet\n"
            "                        raporunuzu otomatik olarak belgenin içine aktararak düzenleyebilirsiniz.\n"
            "   • 📎 Resim         : Bilgisayarınızdan bir görsel (.png, .jpg) seçip sorunuzu yazarak\n"
            "                        yapay zekaya görsel analiz yaptırabilirsiniz.\n"
            "   • 🎤 Ses           : Mikrofonunuzu kullanarak konuşmanızı doğrudan metin kutusuna yazdırır.\n"
            "   • 📄 Belge         : .altar, .pdf, .docx, .txt, .json ve .md belgelerinizi okuyup parçalara\n"
            "                        ayırarak Vektörel Hafıza'ya (ChromaDB) gömer; belge hakkında her şeyi sorabilirsiniz.\n"
            "   • 🌐 Web           : Yörünge & Web Veri Kazıma Merkezini açar. Herhangi bir web sitesini\n"
            "                        5 kategoride (Başlıklar, Tablolar, Belgeler, Paragraflar, Linkler) kazıyabilir,\n"
            "                        SSD'ye (JSON/MD) kaydedebilir veya canlı veri takibi başlatabilirsiniz.\n\n"
            "🔹 3. ÖZEL ÇALIŞMA SEKMELERİ (ÜST SEKME ÇUBUĞU)\n"
            "   • 💬 Sohbet                        : Ana yapay zeka iletişim, kodlama ve analiz ekranıdır.\n"
            "   • 📊 Kazınan Veri & Analiz Merkezi : '🌐 Web' modülünden gönderilen veya SSD arşivinden yüklenen\n"
            "                                        kategorize web verilerini filtreleyip tek tıkla AI'ya analiz ettirir.\n"
            "   • 📐 CNC G-Code 2D Simülatör       : G-Code komutlarınızı tezgaha bağlamadan önce X-Y ekseninde\n"
            "                                        2 boyutlu olarak çizer (Kırmızı Kesikli: G00, Yeşil: G01/G02/G03).\n\n"
            "🔹 4. SOHBET İNTERNET, OSINT VE GÜVENLİK ARAÇLARI (OTONOM YETENEKLER)\n"
            "   Sohbet ekranından yapay zekaya doğal dille talimat vererek şu işlemleri yaptırabilirsiniz:\n"
            "   • İnternet & Doküman : Güncel web araması, web sayfası okuma, resmi kütüphane dokümanı çekme,\n"
            "                          NASA açık veri araması ve YouTube videolarının metin dökümünü çıkarma.\n"
            "   • GitHub RAG Klonlama: Bir GitHub repo linki vererek tüm kaynak kodlarını hafızaya alıp analiz ettirme.\n"
            "   • Pasif Siber Analiz : Hedef IP/Domain port ve konum kontrolü, pasif SSL ve HTTP güvenlik başlığı\n"
            "                          denetimi, sertifika şeffaflığı ile alt alan adı (subdomain) keşfi, pasif dizin\n"
            "                          kontrolü, CVE zafiyet sorgusu, güncel siber haberler (RSS) ve yerel dosyaları\n"
            "                          çalıştırmadan SHA-256 / MalwareBazaar üzerinden virüs kontrolü.\n\n"
            "🛡️ Otomatik Güvenlik Kalkanı: Üretilen her yanıt; zararlı komut tarayıcısı, Python AST sözdizimi\n"
            "denetçisi ve CNC G-Code çarpışma (G00 Z-) analizörü tarafından otomatik olarak salt-okunur denetlenir.\n"
            "========================================================================================\n"
            "👉 Başlamak için aşağıdaki metin kutusuna sorunuzu veya talimatınızı yazıp 'Enter' tuşuna basın!\n\n"
        )
        self.chat_display.insert("end", karsilama_rehberi)

        self.chat_display.tag_config("code_style", foreground="#E6DB74")
        self.chat_display.tag_config("thought_style", foreground="#8A8A8A")
        self.chat_display.tag_config("telemetry_style", foreground="#00CED1")
        self.chat_display.tag_config("warning_style", foreground="#FF3333")
        self.chat_display._textbox.tag_configure("warning_style", font=("Consolas", 14, "bold"))
        self.chat_display.configure(state="disabled")

        # 2. Sekme: Kazınan Veri & Kategorizasyon Analiz Merkezi
        self._analiz_sekmesini_hazirla()

        # 3. Sekme: CNC G-Code 2D Görsel Takım Yolu Simülatörü (Salt-Okunur / Bellek İçi)
        self._gcode_simulator_sekmesini_hazirla()

        # --- GİRDİ ALANI VE SOL ALT BUTONLAR ---
        self.bottom_panel = ctk.CTkFrame(self.main_frame, corner_radius=0, fg_color="transparent")
        self.bottom_panel.pack(side="bottom", fill="x", padx=10, pady=(0, 10))

        self.lbl_ek_bilgi = ctk.CTkLabel(self.bottom_panel, text="", text_color="#00AAFF")
        self.lbl_ek_bilgi.pack(side="top", anchor="w", padx=10)

        self.action_frame = ctk.CTkFrame(self.bottom_panel, fg_color="transparent")
        self.action_frame.pack(side="left", padx=(0, 10))

        # Sol Alt Buton Grubu (Raporu Kaydet + Altar Belge + Resim + Ses + Belge + Web)
        self.btn_export = ctk.CTkButton(self.action_frame, text="💾 Raporu Kaydet", width=115, height=22,
                                        command=self.sohbeti_disa_aktar,
                                        fg_color="#1f538d", hover_color="#14375e")
        self.btn_export.pack(side="top", pady=1)

        self.btn_word_pro = ctk.CTkButton(self.action_frame, text="📝 Altar Belge", width=115, height=22,
                                          command=self.word_programini_ac,
                                          fg_color="#008080", hover_color="#005959")
        self.btn_word_pro.pack(side="top", pady=1)

        self.btn_resim = ctk.CTkButton(self.action_frame, text="📎 Resim", width=115, height=22,
                                       command=self.resim_ekle,
                                       fg_color="#4B0082", hover_color="#2b004d")
        self.btn_resim.pack(side="top", pady=1)

        self.btn_ses = ctk.CTkButton(self.action_frame, text="🎤 Ses", width=115, height=22,
                                     command=self.sesli_yazdir,
                                     fg_color="#006400", hover_color="#004d00")
        self.btn_ses.pack(side="top", pady=1)

        self.btn_belge = ctk.CTkButton(self.action_frame, text="📄 Belge", width=115, height=22,
                                       command=self.belge_ekle,
                                       fg_color="#8B4500", hover_color="#5c2e00")
        self.btn_belge.pack(side="top", pady=1)

        self.btn_nasa_sim = ctk.CTkButton(self.action_frame, text="🌐 Web", width=115, height=22,
                                          command=self.toggle_nasa_sim,
                                          fg_color="#FF4500", hover_color="#8B0000")
        self.btn_nasa_sim.pack(side="top", pady=1)

        self.user_input = ctk.CTkTextbox(self.bottom_panel, font=ctk.CTkFont(size=14), height=145, border_width=2,
                                         border_color="#3a3a3a")
        self.user_input.pack(side="left", fill="both", expand=True, padx=(0, 10))

        def on_enter_pressed(event):
            if event.state & 0x0001:
                return
            else:
                self.send_command()
                return "break"

        self.user_input.bind("<Return>", on_enter_pressed)

        self.btn_send = ctk.CTkButton(self.bottom_panel, text="İlet", width=100, height=145, command=self.send_command)
        self.btn_send.pack(side="right")

    # =====================================================================
    # 2. SEKME: KAZINAN VERİ & ANALİZ MERKEZİ ARAYÜZÜ
    # =====================================================================
    def _analiz_sekmesini_hazirla(self):
        ust_bar = ctk.CTkFrame(self.tab_analiz, fg_color="transparent")
        ust_bar.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(
            ust_bar, text="📂 Kategori Filtresi:", font=ctk.CTkFont(weight="bold")
        ).pack(side="left", padx=5)

        self.kategori_filtre_var = ctk.StringVar(value="Tüm Kategoriler")
        self.kategori_menu = ctk.CTkOptionMenu(
            ust_bar,
            variable=self.kategori_filtre_var,
            values=[
                "Tüm Kategoriler",
                "1. Başlık Hiyerarşisi",
                "2. Veri Tabloları",
                "3. İndirilebilir Belgeler & Veri Setleri",
                "4. Önemli Paragraflar & Makaleler",
                "5. Sayfa Bağlantıları"
            ],
            width=260,
            command=self.kategori_gorunumu_guncelle
        )
        self.kategori_menu.pack(side="left", padx=8)

        ctk.CTkButton(
            ust_bar, text="📂 SSD Arşivinden JSON Yükle", width=190,
            fg_color="#4B0082", command=self.ssd_arsivinden_json_yukle
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            ust_bar, text="🧠 Seçili Kategoriyi AI İle Analiz Et", width=220,
            fg_color="#008080", command=self.secili_kategoriyi_ai_ile_analiz_et
        ).pack(side="right", padx=5)

        self.analiz_textbox = ctk.CTkTextbox(
            self.tab_analiz, font=ctk.CTkFont(family="Consolas", size=13),
            wrap="word", fg_color="#121824", text_color="#00FFCC"
        )
        self.analiz_textbox.pack(fill="both", expand=True, padx=10, pady=5)
        self.analiz_textbox.insert(
            "end",
            "📊 [KAZINAN VERİ & ANALİZ MERKEZİ]\n"
            "Sol alttaki 'Web' butonuna tıklayarak herhangi bir web sitesini kategorize edip buraya gönderebilir "
            "veya SSD'deki 'scraped_archive' klasöründen daha önce kazıdığınız JSON dosyalarını yükleyebilirsiniz.\n"
        )
        self.analiz_textbox.configure(state="disabled")

    def analiz_sekmesine_veri_ekle(self, veri_paketi: dict, tam_metin: str):
        self.son_kazinan_paket = veri_paketi
        self.tabview.set("📊 Kazınan Veri & Analiz Merkezi")
        self.kategori_filtre_var.set("Tüm Kategoriler")
        self.analiz_textbox.configure(state="normal")
        self.analiz_textbox.delete("1.0", "end")
        self.analiz_textbox.insert("end", tam_metin)
        self.analiz_textbox.configure(state="disabled")

    def kategori_gorunumu_guncelle(self, secim: str):
        if not self.son_kazinan_paket:
            return
        kat = self.son_kazinan_paket.get("kategoriler", {})
        baslik = f"📌 KAYNAK: {self.son_kazinan_paket.get('kaynak_url')} ({self.son_kazinan_paket.get('kazima_tarihi')})\n\n"

        if secim == "1. Başlık Hiyerarşisi":
            icerik = "\n".join(kat.get("baslik_hiyerarsisi", [])) or "Bu kategoride veri yok."
        elif secim == "2. Veri Tabloları":
            icerik = "\n\n".join(kat.get("veri_tablolari", [])) or "Bu kategoride tablo bulunamadı."
        elif secim == "3. İndirilebilir Belgeler & Veri Setleri":
            icerik = "\n".join(kat.get("indirilebilir_veri_ve_belgeler", [])) or "İndirilebilir belge bulunamadı."
        elif secim == "4. Önemli Paragraflar & Makaleler":
            icerik = "\n\n".join([f"• {p}" for p in kat.get("onemli_paragraflar", [])]) or "Paragraf bulunamadı."
        elif secim == "5. Sayfa Bağlantıları":
            icerik = "\n".join(kat.get("sayfa_baglantilari", [])) or "Bağlantı bulunamadı."
        else:
            icerik = json.dumps(self.son_kazinan_paket, ensure_ascii=False, indent=2)

        self.analiz_textbox.configure(state="normal")
        self.analiz_textbox.delete("1.0", "end")
        self.analiz_textbox.insert("end", baslik + icerik)
        self.analiz_textbox.configure(state="disabled")

    def ssd_arsivinden_json_yukle(self):
        arsiv_yolu = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraped_archive")
        if not os.path.exists(arsiv_yolu):
            os.makedirs(arsiv_yolu)
        dosya = filedialog.askopenfilename(
            initialdir=arsiv_yolu,
            title="Kategorize JSON Verisi Seç",
            filetypes=[("JSON Veri Dosyası", "*.json"), ("Tüm Dosyalar", "*.*")]
        )
        if dosya:
            try:
                with open(dosya, "r", encoding="utf-8") as f:
                    paket = json.load(f)
                self.son_kazinan_paket = paket
                self.kategori_gorunumu_guncelle("Tüm Kategoriler")
            except Exception as e:
                messagebox.showerror("Hata", f"JSON dosyası okunamadı: {e}")

    def secili_kategoriyi_ai_ile_analiz_et(self):
        icerik = self.analiz_textbox.get("1.0", "end").strip()
        if not icerik or not self.son_kazinan_paket:
            messagebox.showwarning("Uyarı", "Analiz edilecek kazınmış veri bulunamadı.")
            return

        self.tabview.set("💬 Sohbet")
        komut = (
            f"Aşağıda web kazıyıcı tarafından kategorize edilmiş veriler yer almaktadır. "
            f"Lütfen bu verileri detaylıca incele, önemli bulguları, sayısal değerleri ve kritik noktaları raporla:\n\n{icerik[:6000]}"
        )
        self.log_to_chat("Sen (Analiz Merkezi)", "Seçili kategorize web verisini analiz et.", final=True)

        aktif_motor = self.motor_var.get()
        secilen_dil = self.active_lang_var.get()
        if aktif_motor == "Yerel (Ollama)":
            threading.Thread(
                target=self.model_ile_konus,
                args=(self.active_model_var.get(), secilen_dil, komut, None),
                daemon=True
            ).start()
        else:
            threading.Thread(
                target=self.api_ile_konus,
                args=(self.active_api_model_var.get(), secilen_dil, komut, None),
                daemon=True
            ).start()

    # =====================================================================
    # 3. SEKME: CNC G-CODE 2D TAKIM YOLU SİMÜLATÖRÜ (%100 BELLEK İÇİ)
    # =====================================================================
    def _gcode_simulator_sekmesini_hazirla(self):
        cerceve = ctk.CTkFrame(self.tab_gcode, fg_color="transparent")
        cerceve.pack(fill="both", expand=True, padx=5, pady=5)

        sol_panel = ctk.CTkFrame(cerceve, width=360)
        sol_panel.pack(side="left", fill="y", padx=(0, 8))

        ctk.CTkLabel(
            sol_panel, text="⚙️ G-Code Girişi (X-Y Simülasyonu)", font=ctk.CTkFont(weight="bold")
        ).pack(pady=(8, 4), padx=10, anchor="w")

        self.gcode_editor = ctk.CTkTextbox(
            sol_panel, width=340, font=ctk.CTkFont(family="Consolas", size=13), fg_color="#121212"
        )
        self.gcode_editor.pack(fill="both", expand=True, padx=8, pady=4)
        ornek_gcode = (
            "G21 G90 G17\n"
            "G00 X0 Y0 Z5\n"
            "G01 Z-1 F200\n"
            "G01 X60 Y0 F500\n"
            "G01 X60 Y40\n"
            "G01 X0 Y40\n"
            "G01 X0 Y0\n"
            "G00 Z10\n"
            "G00 X15 Y10\n"
            "G01 Z-1\n"
            "G01 X45 Y10\n"
            "G01 X30 Y30\n"
            "G01 X15 Y10\n"
            "G00 Z15\n"
            "M30"
        )
        self.gcode_editor.insert("1.0", ornek_gcode)

        btn_ciz = ctk.CTkButton(
            sol_panel, text="▶️ Takım Yolunu 2D Çiz & Denetle",
            fg_color="#00A86B", hover_color="#007F50", command=self.gcode_takim_yolunu_ciz
        )
        btn_ciz.pack(fill="x", padx=8, pady=6)

        sag_panel = ctk.CTkFrame(cerceve, fg_color="#0d1117")
        sag_panel.pack(side="right", fill="both", expand=True)

        self.lbl_gcode_bilgi = ctk.CTkLabel(
            sag_panel,
            text="🟥 Kesikli Kırmızı: G00 (Boşta Hızlı Hareket)  |  🟩 Yeşil: G01/G02/G03 (Talaşlı Kesim)",
            font=ctk.CTkFont(family="Consolas", size=12), text_color="#00FFCC"
        )
        self.lbl_gcode_bilgi.pack(side="top", pady=4)

        self.gcode_canvas = tk.Canvas(sag_panel, bg="#090d16", highlightthickness=1, highlightbackground="#30363d")
        self.gcode_canvas.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def gcode_takim_yolunu_ciz(self):
        metin = self.gcode_editor.get("1.0", "end")
        self.gcode_canvas.delete("all")

        w = max(self.gcode_canvas.winfo_width(), 500)
        h = max(self.gcode_canvas.winfo_height(), 400)

        cur_x, cur_y, cur_z = 0.0, 0.0, 5.0
        cur_mod = "G00"
        segmentler = []
        xs, ys = [0.0], [0.0]

        for satir in metin.splitlines():
            temiz = re.sub(r'\(.*?\)', '', satir).split(';')[0].upper().strip()
            if not temiz:
                continue
            if re.search(r'\bG0*0\b', temiz):
                cur_mod = "G00"
            elif re.search(r'\bG0*[123]\b', temiz):
                cur_mod = "G01"

            mx = re.search(r'X([-+]?\d*\.?\d+)', temiz)
            my = re.search(r'Y([-+]?\d*\.?\d+)', temiz)
            mz = re.search(r'Z([-+]?\d*\.?\d+)', temiz)

            nx = float(mx.group(1)) if mx else cur_x
            ny = float(my.group(1)) if my else cur_y
            nz = float(mz.group(1)) if mz else cur_z

            if (nx != cur_x) or (ny != cur_y):
                segmentler.append((cur_x, cur_y, nx, ny, cur_mod))
                xs.append(nx)
                ys.append(ny)

            cur_x, cur_y, cur_z = nx, ny, nz

        if not segmentler:
            return

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)

        kenar_boslugu = 50
        olcek = min((w - 2 * kenar_boslugu) / span_x, (h - 2 * kenar_boslugu) / span_y)

        def ekran_koordinati(x_val, y_val):
            sx = kenar_boslugu + (x_val - min_x) * olcek
            sy = h - (kenar_boslugu + (y_val - min_y) * olcek)
            return sx, sy

        # Sıfır noktası (Orijin)
        ox, oy = ekran_koordinati(0, 0)
        self.gcode_canvas.create_oval(ox - 4, oy - 4, ox + 4, oy + 4, fill="#FFFF00", outline="#FFFF00")
        self.gcode_canvas.create_text(ox + 28, oy - 10, text="(X0, Y0)", fill="#FFFF00", font=("Consolas", 9))

        for x1, y1, x2, y2, mod in segmentler:
            sx1, sy1 = ekran_koordinati(x1, y1)
            sx2, sy2 = ekran_koordinati(x2, y2)
            if mod == "G00":
                self.gcode_canvas.create_line(sx1, sy1, sx2, sy2, fill="#FF4444", width=1.5, dash=(4, 4))
            else:
                self.gcode_canvas.create_line(sx1, sy1, sx2, sy2, fill="#00FF88", width=2.5)

    # =====================================================================
    # ALTAR BELGE (WORD PROGRAMI.PY) BAŞLATICI
    # =====================================================================
    def word_programini_ac(self):
        ana_dizin = os.path.dirname(os.path.abspath(__file__))
        olasi_isimler = ["Word Programı.py", "word_programi.py", "AltarEditorPro.py"]
        bulunan = any(os.path.exists(os.path.join(ana_dizin, isim)) for isim in olasi_isimler)

        if not bulunan:
            messagebox.showerror(
                "Eksik Modül",
                "'Word Programı.py' dosyası aynı klasörde bulunamadı!\nLütfen dosyanın ana kodla aynı dizinde olduğundan emin olun."
            )
            return

        mevcut_sohbet = self.chat_display.get("1.0", "end").strip()
        secim = messagebox.askyesnocancel(
            "Altar Belge",
            "Altar Belge başlatılıyor.\n\n"
            "• EVET: Mevcut Altar sohbet/analiz raporunu belge içine aktararak tam ekran aç.\n"
            "• HAYIR: Boş yeni bir belge olarak tam ekran aç."
        )
        if secim is None:
            return

        aktarilacak_metin = mevcut_sohbet if secim else ""
        p = multiprocessing.Process(target=_word_editor_surecini_baslat, args=(aktarilacak_metin,), daemon=True)
        p.start()

    # =====================================================================
    # CANLI DONANIM TELEMETRİSİ (CPU + GPU + RAM GB/%) VE RAPOR KAYDETME
    # =====================================================================
    def telemetri_guncelle(self):
        try:
            cpu = psutil.cpu_percent(interval=None) if PSUTIL_AVAILABLE else 0.0
            if PSUTIL_AVAILABLE:
                mem = psutil.virtual_memory()
                ram_yuzde = mem.percent
                ram_kullanilan_gb = mem.used / (1024 ** 3)
                ram_toplam_gb = mem.total / (1024 ** 3)
            else:
                ram_yuzde, ram_kullanilan_gb, ram_toplam_gb = 0.0, 0.0, 0.0

            gpu = self.gpu_reader.gpu_yuzdesi_oku(ollama_client=getattr(self, "client", None))

            renk = "#FF4444" if (ram_yuzde > 85 or cpu > 90) else "#00FF88"
            telemetri_metni = (
                f"CPU: %{cpu:.0f} | GPU: %{gpu:.0f} | "
                f"RAM: %{ram_yuzde:.0f} ({ram_kullanilan_gb:.1f}/{ram_toplam_gb:.1f} GB)"
            )
            self.lbl_telemetri.configure(text=telemetri_metni, text_color=renk)
        except Exception:
            pass
        self.after(2500, self.telemetri_guncelle)

    def sohbeti_disa_aktar(self):
        icerik = self.chat_display.get("1.0", "end").strip()
        if not icerik:
            messagebox.showinfo("Bilgi", "Kaydedilecek sohbet içeriği bulunamadı.")
            return

        varsayilan_ad = f"Altar_Rapor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        dosya_yolu = filedialog.asksaveasfilename(
            defaultextension=".md",
            initialfile=varsayilan_ad,
            filetypes=[("Markdown Raporu", "*.md"), ("Metin Dosyası", "*.txt")]
        )
        if dosya_yolu:
            if os.path.exists(dosya_yolu):
                messagebox.showwarning(
                    "Güvenlik Koruması",
                    "Seçtiğiniz isimde bir dosya zaten mevcut! Hiçbir dosyanın içeriğinin değişmemesi için üzerine yazma işlemi engellendi. Lütfen yeni bir dosya adı girin."
                )
                return
            try:
                with open(dosya_yolu, "x", encoding="utf-8") as f:
                    f.write("# ALTAR - ANALİZ RAPORU\n")
                    f.write(
                        f"**Tarih:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | **Profil:** {self.active_lang_var.get()}\n\n---\n\n")
                    f.write(icerik)
                messagebox.showinfo("Başarılı", f"Rapor yeni dosya olarak güvenle kaydedildi:\n{dosya_yolu}")
            except Exception as e:
                messagebox.showerror("Kayıt Hatası", f"Dosya oluşturulurken hata meydana geldi: {e}")

    # =====================================================================
    # WEB VERİ KAZIMA MODÜL ÇAĞRISI
    # =====================================================================
    def toggle_nasa_sim(self):
        if not NASA_SCRAPER_AVAILABLE:
            messagebox.showerror("Eksik Modül",
                                 "nasa_scraper.py dosyası bulunamadı! Lütfen iki kodun aynı klasörde olduğundan emin olun.")
            return

        NasaScraperWindow(self)

    # =====================================================================
    # GÖRSEL EKLEME SİSTEMİ
    # =====================================================================
    def resim_ekle(self):
        if not VISION_AVAILABLE:
            messagebox.showwarning("Eksik Kütüphane",
                                   "Görsel analizi için 'Pillow' kütüphanesini yüklemelisiniz (pip install Pillow).")
            return

        dosya = filedialog.askopenfilename(
            filetypes=[("Resim Dosyaları", "*.png;*.jpg;*.jpeg"), ("Tüm Dosyalar", "*.*")])
        if dosya:
            self.ekli_resim_yolu = dosya
            dosya_adi = os.path.basename(dosya)
            self.lbl_ek_bilgi.configure(text=f"📎 Eklendi: {dosya_adi}")

    # =====================================================================
    # BELGE OKUMA SİSTEMİ (Local Document RAG + .altar Desteği)
    # =====================================================================
    def belge_ekle(self):
        dosya = filedialog.askopenfilename(
            filetypes=[("Desteklenen Belgeler", "*.altar;*.pdf;*.txt;*.docx;*.json;*.md"), ("Tüm Dosyalar", "*.*")])
        if dosya:
            dosya_adi = os.path.basename(dosya)
            self.lbl_ek_bilgi.configure(text=f"📄 İşleniyor: {dosya_adi}")
            threading.Thread(target=self._belgeyi_isle_ve_kaydet, args=(dosya,), daemon=True).start()

    def _belgeyi_isle_ve_kaydet(self, dosya_yolu):
        uzanti = dosya_yolu.lower().split('.')[-1]
        metin = ""
        try:
            if uzanti == "altar":
                with open(dosya_yolu, "r", encoding="utf-8") as f:
                    veri = json.load(f)
                html_kismi = BeautifulSoup(veri.get("icerik_html", ""), "html.parser").get_text(separator="\n", strip=True)
                yan_notlar = veri.get("yan_notlar", "")
                metin = f"[ALTAR PRO BELGESİ]\nYan Notlar:\n{yan_notlar}\n\nAna İçerik:\n{html_kismi}"
            elif uzanti == "txt":
                with open(dosya_yolu, "r", encoding="utf-8") as f:
                    metin = f.read()
            elif uzanti == "pdf":
                if not PDF_AVAILABLE:
                    self.update_chat_safe(
                        "[SİSTEM UYARISI]: PDF okumak için 'PyMuPDF' kütüphanesi eksik (pip install PyMuPDF).\n",
                        final=True)
                    self.lbl_ek_bilgi.configure(text="")
                    return
                doc = fitz.open(dosya_yolu)
                for page in doc:
                    metin += page.get_text() + "\n"
            elif uzanti == "docx":
                if not DOCX_AVAILABLE:
                    self.update_chat_safe(
                        "[SİSTEM UYARISI]: DOCX okumak için 'python-docx' kütüphanesi eksik (pip install python-docx).\n",
                        final=True)
                    self.lbl_ek_bilgi.configure(text="")
                    return
                doc = docx.Document(dosya_yolu)
                for para in doc.paragraphs:
                    metin += para.text + "\n"
            else:
                try:
                    with open(dosya_yolu, 'rb') as f:
                        ilk_kisim = f.read(1024)
                        if b'\x00' in ilk_kisim:
                            self.update_chat_safe(
                                f"[SİSTEM UYARISI]: '{os.path.basename(dosya_yolu)}' metin tabanlı değil (Medya/Program/Binary). Sistemi korumak için okuma reddedildi.\n",
                                final=True)
                            self.lbl_ek_bilgi.configure(text="")
                            return
                except Exception:
                    pass

                try:
                    with open(dosya_yolu, "r", encoding="utf-8") as f:
                        metin = f.read()
                except UnicodeDecodeError:
                    try:
                        with open(dosya_yolu, "r", encoding="latin-1") as f:
                            metin = f.read()
                    except Exception:
                        self.update_chat_safe(
                            f"[SİSTEM UYARISI]: '{os.path.basename(dosya_yolu)}' okunamayan bir format. Lütfen düz metin (text) içeren dosyalar yükleyin.\n",
                            final=True)
                        self.lbl_ek_bilgi.configure(text="")
                        return

            if not metin.strip():
                self.update_chat_safe(
                    f"[SİSTEM UYARISI]: '{os.path.basename(dosya_yolu)}' belgesi boş veya metin okunamadı.\n",
                    final=True)
                self.lbl_ek_bilgi.configure(text="")
                return

            max_karakter = 1000000
            if len(metin) > max_karakter:
                metin = metin[:max_karakter]
                self.update_chat_safe(
                    f"[SİSTEM UYARISI]: Dosya çok büyük! Sistemin donmaması için sadece ilk {max_karakter} karakter (yaklaşık 300 sayfa) hafızaya alındı.\n",
                    final=False)

            chunk_size = 1500
            chunks = [metin[i:i + chunk_size] for i in range(0, len(metin), chunk_size)]

            for i, chunk in enumerate(chunks):
                icerik = f"KAYNAK BELGE: {os.path.basename(dosya_yolu)}\nBÖLÜM: {i + 1}/{len(chunks)}\nİÇERİK:\n{chunk}"
                self.db_manager.mesaj_kaydet("document", icerik)

            sistem_notu = (
                f"[SİSTEM BİLGİSİ]: Kullanıcı az önce '{os.path.basename(dosya_yolu)}' adlı dosyayı "
                f"(toplam {len(chunks)} parça halinde) Vektörel Hafıza'ya yükledi. Kullanıcı bu dosya hakkında "
                f"'analiz et', 'bu dosyaya göre yap' gibi bağlamsız genel bir istekte bulunursa, "
                f"lütfen dosyanın içeriğini görmek için hemen MEMORY_SEARCH:::{os.path.basename(dosya_yolu)} "
                f"aracını kullan."
            )
            self.gecmis.append({'role': 'system', 'content': sistem_notu})

            self.update_chat_safe(
                f"[SİSTEM]: '{os.path.basename(dosya_yolu)}' başarıyla okundu ve {len(chunks)} parça halinde Vektörel Hafıza'ya (ChromaDB) gömüldü. Artık bu belge hakkında serbestçe soru sorabilirsiniz.\n\n",
                final=True)
            self.lbl_ek_bilgi.configure(text=f"📄 Hafızada: {os.path.basename(dosya_yolu)}")

        except Exception as e:
            self.update_chat_safe(f"[SİSTEM HATASI]: Belge işlenirken bir sorun oluştu: {e}\n", final=True)
            self.lbl_ek_bilgi.configure(text="")

    def sesli_yazdir(self):
        if not STT_AVAILABLE:
            messagebox.showwarning("Eksik Kütüphane",
                                   "Ses tanıma için 'SpeechRecognition' ve 'pyaudio' yüklemelisiniz (pip install SpeechRecognition pyaudio).")
            return

        def dinle():
            self.btn_ses.configure(text="Dinliyor...", fg_color="#b85c00")
            r = sr.Recognizer()
            with sr.Microphone() as source:
                try:
                    audio = r.listen(source, timeout=5, phrase_time_limit=15)
                    metin = r.recognize_google(audio, language="tr-TR")
                    self.user_input.insert("end", metin + " ")
                except Exception as e:
                    print(f"Ses anlaşılamadı: {e}")
            self.btn_ses.configure(text="🎤 Ses", fg_color="#006400")

        threading.Thread(target=dinle, daemon=True).start()

    def kodlari_renklendir(self):
        self.chat_display.tag_remove("code_style", "1.0", "end")
        self.chat_display.tag_remove("thought_style", "1.0", "end")
        metin = self.chat_display.get("1.0", "end")

        for match in re.finditer(r'```(.*?)```', metin, re.DOTALL):
            baslangic_indeksi = f"1.0 + {match.start()} chars"
            bitis_indeksi = f"1.0 + {match.end()} chars"
            self.chat_display.tag_add("code_style", baslangic_indeksi, bitis_indeksi)

        for match in re.finditer(r'<düşünce>(.*?)</düşünce>', metin, re.DOTALL):
            baslangic_indeksi = f"1.0 + {match.start()} chars"
            bitis_indeksi = f"1.0 + {match.end()} chars"
            self.chat_display.tag_add("thought_style", baslangic_indeksi, bitis_indeksi)

    def update_chat_safe(self, text, final=False, tag=None):
        def task():
            self.chat_display.configure(state="normal")
            if tag:
                self.chat_display.insert("end", text, tag)
            else:
                self.chat_display.insert("end", text)

            if final:
                self.kodlari_renklendir()
            self.chat_display.see("end")
            self.chat_display.configure(state="disabled")

        self.after(0, task)

    def log_to_chat(self, tag, message, final=False):
        self.update_chat_safe(f"[{tag}]: {message}\n\n", final=final)

    def send_command(self):
        cmd = self.user_input.get("1.0", "end-1c").strip()

        if not cmd and not self.ekli_resim_yolu:
            return

        self.user_input.delete("1.0", "end")

        if cmd.startswith("!"):
            cmd = cmd[1:].strip()

        self.log_to_chat("Sen", cmd, final=True)
        aktif_motor = self.motor_var.get()
        secilen_dil = self.active_lang_var.get()
        resim_dosyasi = self.ekli_resim_yolu

        self.ekli_resim_yolu = None
        self.lbl_ek_bilgi.configure(text="")

        if aktif_motor == "Yerel (Ollama)":
            secilen_model = self.active_model_var.get()
            threading.Thread(target=self.model_ile_konus, args=(secilen_model, secilen_dil, cmd, resim_dosyasi),
                             daemon=True).start()
        else:
            secilen_api_modeli = self.active_api_model_var.get()
            threading.Thread(target=self.api_ile_konus, args=(secilen_api_modeli, secilen_dil, cmd, resim_dosyasi),
                             daemon=True).start()

    def baglam_sikistir(self, aktif_motor, model_adi):
        if len(self.gecmis) > 20:
            self.update_chat_safe("\n[SİSTEM UYARISI: VRAM sınırına yaklaşıldı. Eski sohbetler sıkıştırılıyor...]\n",
                                  final=True)

            eski_mesajlar = self.gecmis[:-8]
            korunan_mesajlar = self.gecmis[-8:]

            eski_metin = ""
            for msg in eski_mesajlar:
                rol_ismi = "Kullanıcı" if msg.get('role') == "user" else (
                    "Sistem Notu" if msg.get('role') == "system" else "Asistan")
                eski_metin += f"{rol_ismi}: {msg.get('content')}\n"

            ozet_istemi = f"Lütfen aşağıdaki eski konuşmaları, teknik detayları ve kodlama çözümlerini unutmadan tek bir özet paragrafa dönüştür:\n{eski_metin}"

            try:
                ozet_sonuc = ""
                if aktif_motor == "Yerel (Ollama)":
                    akim = self.client.generate(model=model_adi, prompt=ozet_istemi)
                    ozet_sonuc = akim['response']
                else:
                    if self.api_engine and self.api_engine.hazir_mi:
                        ozet_sonuc = self.api_engine.soru_sor(kullanici_mesaji=ozet_istemi,
                                                              dinamik_kimlik="Sen uzman bir özetleme asistanısın.")
                    else:
                        ozet_sonuc = "Eski konuşmalar özetlenemedi (API hatası)."

                ozet_sonuc = re.sub(r'<düşünce>.*?</düşünce>', '', ozet_sonuc, flags=re.DOTALL).strip()

                sistem_ozet_mesaji = {"role": "system",
                                      "content": f"[ESKİ KONUŞMALARIN SIKIŞTIRILMIŞ ÖZETİ]: {ozet_sonuc}"}

                self.gecmis = [sistem_ozet_mesaji] + korunan_mesajlar
                self.update_chat_safe(
                    "[SİSTEM UYARISI: Eski sohbetler başarıyla sıkıştırıldı. Hafıza (VRAM) optimize edildi.]\n\n",
                    final=True)

            except Exception as e:
                self.log_to_chat("HATA", f"Sıkıştırma sırasında hata: {e}", final=True)
                self.gecmis = self.gecmis[-16:]

    def model_ile_konus(self, model_adi, dil_secimi, girdi, resim_yolu=None):
        self.log_to_chat("SİSTEM", f"'{model_adi}' ajanı (Yerel) {dil_secimi} modunda yanıt hazırlıyor...", final=True)

        try:
            kesin_kimlik = self.model_kimlikleri.get(model_adi, self.model_kimlikleri["varsayilan"])

            arac_talimati = (
                f"\n\n--- İNTERNET, DOKÜMANTASYON VE GEÇMİŞ HAFIZA REHBERİ ---\n"
                f"Şu anda '{dil_secimi}' modunda çalışıyorsun. Sınırsız Vektörel (ChromaDB) veritabanına erişimin var.\n"
                "Arama yapmak için: SEARCH:::aranacak kelimeler\n"
                "NASA Açık Veri API Araması İçin: NASA_SEARCH:::<aranacak kelime>\n"
                "Web sitesi okumak için: READ:::https://siteadresi.com\n"
                "Geçmiş hataları ve konuşmaları aramak için: MEMORY_SEARCH:::aranacak kelime\n"
                "YouTube Videosu Analizi İçin: YOUTUBE:::<video_linki>\n"
                "Güvenli Ağ/Hedef Taraması (IP/Domain) İçin: NETWORK_SCAN:::<ip_veya_domain>\n"
                "Pasif SSL ve HTTP Güvenlik Başlığı Denetimi İçin: SSL_AUDIT:::<domain>\n"
                "Pasif Alt Alan Adı (Subdomain) Keşfi İçin: SUBDOMAIN_OSINT:::<domain>\n"
                "Yerel Dosya SHA-256 ve Zararlı Sorgusu (Salt-Okunur) İçin: FILE_HASH:::<dosya_yolu>\n"
                "Siber İstihbarat ve Güncel Haber (RSS) İçin: RSS:::haberler\n"
                "Güvenlik Zafiyeti (CVE/NVD) Analizi İçin: CVE_SEARCH:::<CVE-YYYY-NNNN>\n"
                "Canlı API (GET/POST) Testi İçin: API_REQUEST:::<METOT> <URL>\n"
                "GitHub Reposunu Hafızaya Klonlamak İçin: REPO_CLONE:::<repo_linki>\n"
                "Pasif OSINT ve Dizin Keşfi İçin: OSINT_SCAN:::<ip_veya_domain>\n"
                "Kütüphanelerin Güncel Resmi Dokümanlarını Çekmek İçin: DOCS_PULL:::<kutuphane_adi>\n"
            )

            profil_ek_talimat = ""
            if dil_secimi == "G-Code / CNC":
                profil_ek_talimat = "\n[PROFİL AKTİF: CNC VE İMALAT UZMANI] Sen kıdemli bir CNC operatörü ve makine mühendisisin. G-Code programlama, ilerleme (feed/speed) hızları, takım yolları ve imalat parametreleri konusunda teknik jargon kullanarak endüstri standartlarında kesin yanıtlar vermelisin."
            elif dil_secimi == "Ağ Analizi":
                profil_ek_talimat = "\n[PROFİL AKTİF: SİBER GÜVENLİK VE AĞ UZMANI] Sen üst düzey bir ağ trafik analistisin. Wireshark, Scapy, TCP/IP protokollerine ve ağ savunma (defensive monitoring) mimarilerine derinlemesine hakimsin. Güvenlik ve ağ analizlerini profesyonel siber jargonla yapmalısın."
            elif dil_secimi == "GitHub (Açık Kaynak)":
                profil_ek_talimat = "\n[PROFİL AKTİF: AÇIK KAYNAK GÜVENLİK MÜHENDİSİ] Aramalarını doğrudan güvenilir açık kaynak depolarda (GitHub) yapmalısın. İncelediğin repolardaki kodlarda arka kapı (backdoor), gereksiz/tehlikeli sistem komutları olup olmadığını denetle."
            elif dil_secimi == "NASA Yanma Analizi":
                profil_ek_talimat = (
                    "\n[PROFİL AKTİF: MİKRO YERÇEKİMİ YANMA UZMANI] Sen NASA Space Apps 'Flame in Freefall' projesi için "
                    "Kıdemli Yangın Güvenliği Analistisin. Görevin mikro yerçekimindeki küresel alev yapılarını, "
                    "is oluşumunu ve uzay araçları için yangın sönümleme dinamiklerini analiz etmektir."
                )

            fisildanan_ani = self.db_manager.otomatik_hafiza_tarama(girdi)

            nasa_siki_kurallar = ""
            if dil_secimi == "NASA Yanma Analizi":
                nasa_siki_kurallar = (
                    "\n\n[ZORUNLU NASA ANALİZ KURALLARI]:\n"
                    "1. HALON GAZI ASLA ÖNERME! ISS standartlarına göre 'İnce Su Sisi (Water Mist)' veya CO2 öner.\n"
                    "2. Kapalı sistemde OKSİJEN ARTIYORSA bu yanmanın hızlandığını GÖSTERMEZ; havalandırma (fan) açılmıştır veya sızıntı vardır. Bu fiziksel gerçeği atlama.\n"
                    "3. Düşük oksijende (eksik yanma) İS (SOOT) üretiminin ve Karbonmonoksit riskinin artacağını rapora ekle."
                )

            tam_girdi = f"{fisildanan_ani}\n\nKULLANICI SORUSU: {girdi}{nasa_siki_kurallar}" if fisildanan_ani else f"KULLANICI SORUSU: {girdi}{nasa_siki_kurallar}"

            sistem_mesaji = kesin_kimlik + arac_talimati + profil_ek_talimat

            kullanici_mesaji_dict = {'role': 'user', 'content': tam_girdi}
            if resim_yolu and VISION_AVAILABLE:
                import base64
                with open(resim_yolu, "rb") as resim_dosyasi:
                    base64_resim = base64.b64encode(resim_dosyasi.read()).decode('utf-8')
                    kullanici_mesaji_dict['images'] = [base64_resim]

            gonderilecek_mesajlar = [{'role': 'system', 'content': sistem_mesaji}] + self.gecmis + [
                kullanici_mesaji_dict]

            max_adim = 6
            adim = 0

            while adim < max_adim:
                adim += 1

                akim = self.client.chat(
                    model=model_adi,
                    messages=gonderilecek_mesajlar,
                    stream=True,
                    options={
                        'temperature': 0.4,
                        'num_ctx': 24576,
                        'num_predict': -1,
                        'num_gpu': 30,
                        'top_k': 50,
                        'top_p': 0.90,
                        'repeat_penalty': 1.0,
                        'repeat_last_n': 64,
                        'stop': ["<|im_end|>", "<|end_of_text|>", "Kullanıcı:", "Sen:", "[SİSTEM]:"]
                    }
                )

                tam_cevap = ""
                self.update_chat_safe(f"[{model_adi}]:\n")
                ui_uyari_gosterildi = False

                for parca in akim:
                    kelime = parca['message'].get('content', '')
                    if not kelime:
                        continue

                    tam_cevap += kelime

                    if not ui_uyari_gosterildi:
                        if "SEARCH:::" in tam_cevap:
                            self.update_chat_safe("\n[* İlgili ağda arama yapılıyor, Lütfen Bekleyin...]\n")
                            ui_uyari_gosterildi = True
                        elif "NASA_SEARCH:::" in tam_cevap:
                            self.update_chat_safe("\n[* NASA API Üzerinden Açık Uzay Verileri Çekiliyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "READ:::" in tam_cevap:
                            self.update_chat_safe("\n[* Web sayfası detaylıca taranıyor, İşleniyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "MEMORY_SEARCH:::" in tam_cevap:
                            self.update_chat_safe("\n[* Vektörel Hafıza Taranıyor, İşleniyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "YOUTUBE:::" in tam_cevap:
                            self.update_chat_safe("\n[* YouTube Videosu İzleniyor ve Analiz Ediliyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "NETWORK_SCAN:::" in tam_cevap:
                            self.update_chat_safe("\n[* Hedef Ağda Güvenli/Pasif Tarama Yapılıyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "SSL_AUDIT:::" in tam_cevap:
                            self.update_chat_safe("\n[* Pasif SSL ve Güvenlik Başlığı Denetimi Yapılıyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "SUBDOMAIN_OSINT:::" in tam_cevap:
                            self.update_chat_safe("\n[* Pasif Sertifika Şeffaflığı (Alt Alan Adı) Kayıtları Okunuyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "FILE_HASH:::" in tam_cevap:
                            self.update_chat_safe("\n[* Dosya Salt-Okunur SHA-256 Bütünlük Analizi Yapılıyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "RSS:::" in tam_cevap:
                            self.update_chat_safe("\n[* Küresel Siber Güvenlik İstihbarat Akışı Taranıyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "CVE_SEARCH:::" in tam_cevap:
                            self.update_chat_safe("\n[* NVD Siber Zafiyet Veritabanı Sorgulanıyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "API_REQUEST:::" in tam_cevap:
                            self.update_chat_safe("\n[* Canlı Sunucuya API İsteği Gönderiliyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "REPO_CLONE:::" in tam_cevap:
                            self.update_chat_safe("\n[* Kaynak Proje Vektörel Hafızaya İndiriliyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "OSINT_SCAN:::" in tam_cevap:
                            self.update_chat_safe("\n[* Hedef Üzerinde Pasif OSINT ve Dizin Keşfi Yapılıyor...]\n")
                            ui_uyari_gosterildi = True
                        elif "DOCS_PULL:::" in tam_cevap:
                            self.update_chat_safe("\n[* En Güncel Resmi Dokümantasyon Araştırılıyor...]\n")
                            ui_uyari_gosterildi = True
                        else:
                            self.update_chat_safe(kelime)

                match_search = re.search(r'SEARCH:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_nasa = re.search(r'NASA_SEARCH:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_read = re.search(r'READ:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_memory = re.search(r'MEMORY_SEARCH:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_youtube = re.search(r'YOUTUBE:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_network = re.search(r'NETWORK_SCAN:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_ssl = re.search(r'SSL_AUDIT:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_sub = re.search(r'SUBDOMAIN_OSINT:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_file_hash = re.search(r'FILE_HASH:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_rss = re.search(r'RSS:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_cve = re.search(r'CVE_SEARCH:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_api = re.search(r'API_REQUEST:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_repo = re.search(r'REPO_CLONE:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_osint = re.search(r'OSINT_SCAN:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)
                match_docs_pull = re.search(r'DOCS_PULL:::(.*?)(?:\n|$)', tam_cevap, re.IGNORECASE)

                if any([match_search, match_nasa, match_read, match_memory, match_youtube, match_network,
                        match_ssl, match_sub, match_file_hash, match_rss, match_cve, match_api, match_repo,
                        match_osint, match_docs_pull]):
                    gonderilecek_mesajlar.append({'role': 'assistant', 'content': tam_cevap})

                    if match_search:
                        raw_query = match_search.group(1).strip()
                        site_filter = DOCS_MAP.get(dil_secimi, "")
                        full_query = f"{site_filter} {raw_query}".strip()

                        self.update_chat_safe(f"\n[*] AJAN İŞLEMİ: Aranıyor -> '{full_query}'\n", final=True)
                        tool_result = web_search(full_query)
                        bilgi_mesaji = f"[ARAMA VE DOKÜMANTASYON SONUCU]:\n{tool_result}\n\nLütfen bu bilgiyi detaylıca analiz et ve kullanıcıya özgürce açıklama sunarak yardımcı ol."
                        gonderilecek_mesajlar.append({'role': 'user', 'content': bilgi_mesaji})

                    elif match_nasa:
                        raw_query = match_nasa.group(1).strip()
                        self.update_chat_safe(f"\n[*] AJAN İŞLEMİ: NASA Veri Tabanı Taranıyor -> '{raw_query}'\n",
                                              final=True)
                        tool_result = fetch_nasa_api(raw_query)
                        bilgi_mesaji = f"[NASA AÇIK VERİ SONUCU]:\n{tool_result}\n\nBu uzay/yanma verilerine göre kullanıcıya bilimsel bir cevap hazırla."
                        gonderilecek_mesajlar.append({'role': 'user', 'content': bilgi_mesaji})

                    elif match_read:
                        url = match_read.group(1).strip()
                        self.update_chat_safe(f"\n[*] AJAN İŞLEMİ: Okunuyor -> '{url}'\n", final=True)
                        tool_result = read_webpage(url)
                        bilgi_mesaji = f"[SAYFA İÇERİĞİ]:\n{tool_result}\n\nLütfen bu içeriği analiz et ve detay seviyesinde açıklayıcı bir şekilde kullanıcıya sun."
                        gonderilecek_mesajlar.append({'role': 'user', 'content': bilgi_mesaji})

                    elif match_memory:
                        raw_query = match_memory.group(1).strip()
                        self.update_chat_safe(f"\n[*] AJAN İŞLEMİ: Geçmiş Hafıza Aranıyor -> '{raw_query}'\n",
                                              final=True)
                        tool_result = self.db_manager.hafiza_ara(raw_query)
                        bilgi_mesaji = f"{tool_result}\n\nLütfen bu anlamsal geçmiş tecrübelerini incele ve işlemlerini buna göre yap."
                        gonderilecek_mesajlar.append({'role': 'user', 'content': bilgi_mesaji})

                    elif match_youtube:
                        url = match_youtube.group(1).strip()
                        self.update_chat_safe(f"\n[*] AJAN İŞLEMİ: YouTube Video Dökümü Alınıyor -> '{url}'\n",
                                              final=True)
                        tool_result = get_youtube_transcript(url)
                        bilgi_mesaji = f"{tool_result}\n\nYukarıdaki YouTube videosu konuşma dökümüne göre kullanıcının sorusunu yanıtla."
                        gonderilecek_mesajlar.append({'role': 'user', 'content': bilgi_mesaji})

                    elif match_network:
                        hedef = match_network.group(1).strip()
                        self.update_chat_safe(f"\n[*] AJAN İŞLEMİ: Güvenli Ağ Analizi Yapılıyor -> '{hedef}'\n",
                                              final=True)
                        tool_result = safe_network_scan(hedef)
                        bilgi_mesaji = f"[AĞ ANALİZ SONUCU]:\n{tool_result}\n\nLütfen bu ağ bulgularını siber güvenlik perspektifinden analiz edip kullanıcıya detaylıca raporla."
                        gonderilecek_mesajlar.append({'role': 'user', 'content': bilgi_mesaji})

                    elif match_ssl:
                        hedef = match_ssl.group(1).strip()
                        self.update_chat_safe(
                            f"\n[*] AJAN İŞLEMİ: Pasif SSL ve Başlık Denetimi -> '{hedef}'\n", final=True)
                        tool_result = passive_ssl_header_audit(hedef)
                        bilgi_mesaji = f"[PASİF SSL VE BAŞLIK DENETİM SONUCU]:\n{tool_result}\n\nLütfen eksik güvenlik başlıklarını ve sertifika durumunu savunma (defensive) perspektifiyle raporla."
                        gonderilecek_mesajlar.append({'role': 'user', 'content': bilgi_mesaji})

                    elif match_sub:
                        hedef = match_sub.group(1).strip()
                        self.update_chat_safe(
                            f"\n[*] AJAN İŞLEMİ: Pasif Alt Alan Adı (crt.sh) Sorgusu -> '{hedef}'\n", final=True)
                        tool_result = passive_subdomain_osint(hedef)
                        bilgi_mesaji = f"[PASİF ALT ALAN ADI SONUCU]:\n{tool_result}\n\nLütfen bu açık sertifika kayıtlarını analiz et."
                        gonderilecek_mesajlar.append({'role': 'user', 'content': bilgi_mesaji})

                    elif match_file_hash:
                        dosya_yolu = match_file_hash.group(1).strip()
                        self.update_chat_safe(
                            f"\n[*] AJAN İŞLEMİ: Salt-Okunur SHA-256 Dosya Analizi -> '{dosya_yolu}'\n", final=True)
                        tool_result = check_file_hash_and_reputation(dosya_yolu)
                        bilgi_mesaji = f"[DOSYA HASH VE İTİBAR SONUCU]:\n{tool_result}\n\nLütfen bu dosyanın bütünlük ve güvenlik durumunu kullanıcıya açıkla."
                        gonderilecek_mesajlar.append({'role': 'user', 'content': bilgi_mesaji})

                    elif match_rss:
                        self.update_chat_safe("\n[*] AJAN İŞLEMİ: Canlı Siber İstihbarat Çekiliyor...\n", final=True)
                        tool_result = get_cyber_rss()
                        bilgi_mesaji = f"{tool_result}\n\nLütfen bu güncel teknoloji/güvenlik haberlerini incele ve kullanıcıya özetleyerek önemli olanları aktar."
                        gonderilecek_mesajlar.append({'role': 'user', 'content': bilgi_mesaji})

                    elif match_cve:
                        cve_id = match_cve.group(1).strip()
                        self.update_chat_safe(f"\n[*] AJAN İŞLEMİ: CVE Zafiyet Veritabanı Taranıyor -> '{cve_id}'\n",
                                              final=True)
                        tool_result = fetch_cve_details(cve_id)
                        gonderilecek_mesajlar.append({'role': 'user', 'content': tool_result})

                    elif match_api:
                        istek_url = match_api.group(1).strip()
                        self.update_chat_safe(f"\n[*] AJAN İŞLEMİ: Canlı API Testi Yapılıyor -> '{istek_url}'\n",
                                              final=True)
                        tool_result = test_rest_api(istek_url)
                        gonderilecek_mesajlar.append({'role': 'user', 'content': tool_result})

                    elif match_repo:
                        repo_url = match_repo.group(1).strip()
                        self.update_chat_safe(
                            f"\n[*] AJAN İŞLEMİ: GitHub Reposu Hafızaya Klonlanıyor -> '{repo_url}'\n", final=True)
                        tool_result = clone_github_repo_to_memory(repo_url, self.db_manager)
                        gonderilecek_mesajlar.append({'role': 'user', 'content': tool_result})

                    elif match_osint:
                        hedef = match_osint.group(1).strip()
                        self.update_chat_safe(
                            f"\n[*] AJAN İŞLEMİ: Pasif OSINT ve Dizin Keşfi Başlatıldı -> '{hedef}'\n", final=True)
                        tool_result = osint_directory_scan(hedef)
                        bilgi_mesaji = f"[OSINT DİZİN TARAMA SONUCU]:\n{tool_result}\n\nLütfen bu bulguları siber güvenlik bakış açısıyla yorumla."
                        gonderilecek_mesajlar.append({'role': 'user', 'content': bilgi_mesaji})

                    elif match_docs_pull:
                        lib_name = match_docs_pull.group(1).strip()
                        self.update_chat_safe(f"\n[*] AJAN İŞLEMİ: '{lib_name}' İçin Resmi Dokümanlar Çekiliyor...\n",
                                              final=True)
                        tool_result = fetch_latest_docs(lib_name)
                        bilgi_mesaji = f"[GÜNCEL DOKÜMANTASYON VERİSİ]:\n{tool_result}\n\nBu güncel kurallara ve kütüphane dokümantasyonuna dayanarak kullanıcının kodunu/sorusunu yanıtla."
                        gonderilecek_mesajlar.append({'role': 'user', 'content': bilgi_mesaji})

                    continue

                else:
                    self.update_chat_safe("\n\n" + "-" * 40 + "\n\n", final=True)

                    guvenlik_raporu = guvenlik_taramasi_yap(tam_cevap)
                    if guvenlik_raporu:
                        self.update_chat_safe(guvenlik_raporu, tag="warning_style")

                    ast_raporu = ast_python_kontrolu(tam_cevap)
                    if ast_raporu:
                        self.update_chat_safe(ast_raporu, tag="warning_style")

                    gcode_raporu = gcode_safety_analyzer(tam_cevap)
                    if gcode_raporu:
                        self.update_chat_safe(gcode_raporu, tag="telemetry_style")

                    self.gecmis.append({'role': 'user', 'content': girdi})
                    self.gecmis.append({'role': 'assistant', 'content': tam_cevap})

                    self.db_manager.mesaj_kaydet("user", girdi)
                    self.db_manager.mesaj_kaydet("assistant", tam_cevap)

                    self.baglam_sikistir("Yerel (Ollama)", model_adi)
                    break

        except Exception as e:
            self.log_to_chat("HATA", f"Yerel Ajan yanıt üretirken hata oluştu: {e}", final=True)

    def api_ile_konus(self, model_adi, dil_secimi, girdi, resim_yolu=None):
        if not getattr(self, 'api_engine', None) or not self.api_engine.hazir_mi:
            self.log_to_chat("HATA",
                             "Geçerli bir API anahtarı bulunamadı! Lütfen kodun üst kısmındaki GEMİNİ_API_KEY değişkenini veya .env dosyanızı kontrol edin.",
                             final=True)
            return

        self.log_to_chat("SİSTEM", f"'{model_adi}' API ajanı (Bulut) {dil_secimi} modunda yanıt hazırlıyor...",
                         final=True)

        try:
            self.api_engine.model_degistir(model_adi)

            baglam = ""
            for msg in self.gecmis:
                rol_adi = "Sen" if msg['role'] == 'user' else ("Sistem Notu" if msg['role'] == 'system' else "Asistan")
                baglam += f"[{rol_adi}]: {msg['content']}\n"

            fisildanan_ani = self.db_manager.otomatik_hafiza_tarama(girdi)
            if fisildanan_ani:
                baglam += f"\n\n{fisildanan_ani}"

            profil_ek_talimat = ""
            if dil_secimi == "G-Code / CNC":
                profil_ek_talimat = " [PROFİL AKTİF: CNC VE İMALAT UZMANI] CNC makine mühendisliği, G-Code ve talaşlı imalat odaklı endüstriyel standartlarda kesin cevaplar ver."
            elif dil_secimi == "Ağ Analizi":
                profil_ek_talimat = " [PROFİL AKTİF: SİBER GÜVENLİK UZMANI] Ağ trafik analizi, Wireshark/Scapy ve TCP/IP mimarileri üzerine profesyonel siber jargonla odaklan."
            elif dil_secimi == "GitHub (Açık Kaynak)":
                profil_ek_talimat = " [PROFİL AKTİF: AÇIK KAYNAK GÜVENLİK MÜHENDİSİ] Aramalarını açık kaynak (GitHub) depolarında yap. Kodlarda zararlı yazılım (malware, backdoor, rm -rf) kontrolü yaparak güvenilir çözümler sun."
            elif dil_secimi == "NASA Yanma Analizi":
                profil_ek_talimat = " [PROFİL AKTİF: MİKRO YERÇEKİMİ YANMA UZMANI] Sen NASA Space Apps 'Flame in Freefall' projesi için Kıdemli Yangın Güvenliği Analistisin."

            dinamik_kimlik = (
                f"Sen Altar sisteminin yetenekli, zeki ve özgür yapay zeka asistanısın. "
                f"Kullanıcıya her konuda en iyi, en kapsamlı ve en açıklayıcı şekilde yardımcı olmakla görevlisin. "
                f"Şu anki ana odak konun ve dilin: {dil_secimi}.{profil_ek_talimat} "
                f"Kısıtlaman yok; özgürce iletişim kurabilirsin. Gerektiğinde sahip olduğun Google Arama araçlarını kullan. "
                f"Cevabını vermeden önce Düşünce Sürecini SADECE <düşünce> ve </düşünce> etiketleri arasına al."
            )

            tam_soru = f"ÖNCEKİ SOHBET GEÇMİŞİ:\n{baglam}\n\nŞİMDİKİ YENİ SORU:\n{girdi}" if baglam else girdi

            if dil_secimi == "NASA Yanma Analizi":
                nasa_siki_kurallar = (
                    "\n\n[ZORUNLU NASA ANALİZ KURALLARI]:\n"
                    "1. HALON GAZI ASLA ÖNERME! ISS standartlarına göre 'İnce Su Sisi (Water Mist)' veya CO2 öner.\n"
                    "2. Kapalı sistemde OKSİJEN ARTIYORSA bu yanmanın hızlandığını GÖSTERMEZ; havalandırma (fan) açılmıştır veya sızıntı vardır. Bu fiziksel gerçeği atlama.\n"
                    "3. Düşük oksijende (eksik yanma) İS (SOOT) üretiminin ve Karbonmonoksit riskinin artacağını rapora ekle."
                )
                tam_soru += nasa_siki_kurallar

            cevap = self.api_engine.soru_sor(kullanici_mesaji=tam_soru, dinamik_kimlik=dinamik_kimlik,
                                             resim_yolu=resim_yolu)

            self.update_chat_safe(f"[{model_adi} (API)]:\n{cevap}\n\n" + "-" * 40 + "\n\n", final=True)

            guvenlik_raporu = guvenlik_taramasi_yap(cevap)
            if guvenlik_raporu:
                self.update_chat_safe(guvenlik_raporu, tag="warning_style")

            ast_raporu = ast_python_kontrolu(cevap)
            if ast_raporu:
                self.update_chat_safe(ast_raporu, tag="warning_style")

            gcode_raporu = gcode_safety_analyzer(cevap)
            if gcode_raporu:
                self.update_chat_safe(gcode_raporu, tag="telemetry_style")

            self.gecmis.append({'role': 'user', 'content': girdi})
            self.gecmis.append({'role': 'assistant', 'content': cevap})

            self.db_manager.mesaj_kaydet("user", girdi)
            self.db_manager.mesaj_kaydet("assistant", cevap)

            self.baglam_sikistir("Bulut (API)", model_adi)

        except Exception as e:
            self.log_to_chat("HATA", f"API Ajanı yanıt üretirken hata oluştu: {e}", final=True)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = AltarMainUI()
    app.mainloop()