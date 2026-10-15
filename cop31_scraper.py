import os
import time
import threading
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import customtkinter as ctk
from PIL import Image
from tkinter import messagebox
from datetime import datetime

# COP31 Sağlık ve İklim Renk Paleti (Tıbbi/Ekolojik Tema)
PANEL_COLOR = "#0D2A20"
BTN_COLOR = "#00A86B"
BTN_HOVER = "#007F50"


class Cop31ScraperWindow(ctk.CTkToplevel):
    def __init__(self, main_app):
        super().__init__(main_app)
        self.main_app = main_app  # Ana uygulamanın (router/core) referansını hafızaya alıyoruz
        self.title("COP31 Erken Uyarı ve Veri İzleme Köprüsü")

        # Tam ekran (zoomed) başlatma komutu
        self.geometry("900x600")
        self.after(0, lambda: self.state('zoomed'))

        # Bu pencere kapatıldığında arka plandaki döngüyü durdur
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Arka Plan Görseli
        self.bg_image_path = "climate_health_bg.jpg"
        self._arka_plani_hazirla()

        # Web Kazıma Değişkenleri
        self.taramaya_devam_et = False
        self.bulunan_linkler = set()

        # --- ARAYÜZ TASARIMI ---
        self.main_frame = ctk.CTkFrame(self, fg_color=PANEL_COLOR, corner_radius=15, border_width=2,
                                       border_color="#1B3B2B")
        self.main_frame.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.85, relheight=0.85)

        self.lbl_baslik = ctk.CTkLabel(self.main_frame, text="🌍 İKLİM VE SALGIN İZLEME MERKEZİ",
                                       font=ctk.CTkFont(family="Consolas", size=24, weight="bold"),
                                       text_color=BTN_COLOR)
        self.lbl_baslik.pack(pady=(20, 10))

        self.lbl_alt_baslik = ctk.CTkLabel(self.main_frame,
                                           text="Hava kalitesi, halk sağlığı uyarıları ve salgın veri portallarını tarar ve Altar çekirdeğine RAG ile gömer.",
                                           font=ctk.CTkFont(size=12), text_color="#A9CBA9")
        self.lbl_alt_baslik.pack(pady=(0, 20))

        self.input_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.input_frame.pack(fill="x", padx=40, pady=10)

        ctk.CTkLabel(self.input_frame, text="Hedef Sağlık/İklim Veri URL'si:", font=ctk.CTkFont(weight="bold")).pack(
            side="left", padx=5)

        self.url_entry = ctk.CTkEntry(self.input_frame,
                                      placeholder_text="Örn: https://who.int/data/ VEYA https://aqicn.org/",
                                      width=400, fg_color="#1B3B2B", border_color=BTN_COLOR)
        self.url_entry.pack(side="left", padx=10, fill="x", expand=True)

        self.btn_tara = ctk.CTkButton(self.input_frame, text="📡 İzlemeyi Başlat", width=120, fg_color=BTN_COLOR,
                                      hover_color=BTN_HOVER, command=self.toggle_tarama)
        self.btn_tara.pack(side="right", padx=5)

        self.log_ekrani = ctk.CTkTextbox(self.main_frame, fg_color="#000000", text_color="#00FFAA",
                                         font=ctk.CTkFont(family="Consolas", size=13), corner_radius=8, border_width=1,
                                         border_color="#333333")
        self.log_ekrani.pack(fill="both", expand=True, padx=40, pady=(10, 20))
        self.log_ekrani.insert("end",
                               "[SİSTEM]: Epidemiyolojik Veri Köprüsü Çevrimiçi. İzlenecek veri portalını girin...\n")
        self.log_ekrani.configure(state="disabled")

        self.lbl_status = ctk.CTkLabel(self.main_frame, text="Durum: Bekleniyor...",
                                       font=ctk.CTkFont(size=12, weight="bold"), text_color="#A9CBA9")
        self.lbl_status.pack(side="bottom", pady=10)

    def _arka_plani_hazirla(self):
        try:
            if not os.path.exists(self.bg_image_path):
                # Ekolojik/Sağlık temalı bir arka plan (Ağaçlar/Doğa)
                url = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=1080"
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    with open(self.bg_image_path, "wb") as f:
                        f.write(response.content)

            bg_image = Image.open(self.bg_image_path)

            # Dinamik ekran boyutu tespiti
            ekran_genisligi = self.winfo_screenwidth()
            ekran_yuksekligi = self.winfo_screenheight()

            self.bg_photo = ctk.CTkImage(light_image=bg_image, dark_image=bg_image,
                                         size=(ekran_genisligi, ekran_yuksekligi))
            self.bg_label = ctk.CTkLabel(self, image=self.bg_photo, text="")
            self.bg_label.place(relx=0.5, rely=0.5, anchor="center")
            self.bg_label.lower()  # Arka planı en alta gönder
        except Exception:
            pass

    def log_yaz(self, mesaj):
        self.log_ekrani.configure(state="normal")
        saat = datetime.now().strftime("%H:%M:%S")
        self.log_ekrani.insert("end", f"[{saat}] {mesaj}\n")
        self.log_ekrani.see("end")
        self.log_ekrani.configure(state="disabled")

    def toggle_tarama(self):
        if not self.taramaya_devam_et:
            hedef_url = self.url_entry.get().strip()
            if not hedef_url.startswith("http"):
                messagebox.showerror("Hata", "Lütfen geçerli bir 'http://' veya 'https://' URL'si girin.", parent=self)
                return

            self.taramaya_devam_et = True
            self.btn_tara.configure(text="🛑 Aramayı Durdur", fg_color="#8B0000", hover_color="#5C0000")
            self.lbl_status.configure(text="Durum: İklim/Sağlık Portalı Sürekli İzleniyor...", text_color=BTN_COLOR)
            self.log_yaz(f"📡 '{hedef_url}' adresi izlemeye alındı. Erken uyarı verileri aranıyor...")

            threading.Thread(target=self.web_site_dinleme_dongusu, args=(hedef_url,), daemon=True).start()
        else:
            self.taramaya_devam_et = False
            self.btn_tara.configure(text="📡 İzlemeyi Başlat", fg_color=BTN_COLOR, hover_color=BTN_HOVER)
            self.lbl_status.configure(text="Durum: Tarama Durduruldu.", text_color="#A9CBA9")
            self.log_yaz("🛑 İzleme görevi durduruldu.")

    def web_site_dinleme_dongusu(self, url):
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) COP31-AI-Agent'}

        while self.taramaya_devam_et:
            try:
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.content, 'html.parser')

                    for a_tag in soup.find_all('a', href=True):
                        link = a_tag['href']
                        if link.endswith('.csv') or link.endswith('.json') or link.endswith('.txt'):
                            tam_link = urljoin(url, link)
                            dosya_adi = os.path.basename(tam_link)

                            if tam_link not in self.bulunan_linkler:
                                self.bulunan_linkler.add(tam_link)
                                self.log_yaz(f"⚠️ YENİ EPİDEMİYOLOJİK/İKLİM VERİSİ BULUNDU: {dosya_adi}")
                                self.after(0, lambda l=tam_link, d=dosya_adi: self.kullanici_onayi_ve_indir(l, d))
                else:
                    self.log_yaz(f"Web sitesine erişilemedi. Durum Kodu: {res.status_code}")
            except Exception as e:
                self.log_yaz(f"Tarama hatası: {e}")

            # Sayfaya yeni dosya eklenmiş mi diye 15 saniyede bir bak
            for _ in range(15):
                if not self.taramaya_devam_et: break
                time.sleep(1)

    def kullanici_onayi_ve_indir(self, link, dosya_adi):
        cevap = messagebox.askyesno("Yeni Sağlık/İklim Verisi Bulundu!",
                                    f"Taranan sayfaya yeni bir veri seti eklendi:\n\n'{dosya_adi}'\n\nBu veriyi indirip Altar Çekirdeği ile salgın/iklim analizi başlatalım mı?",
                                    parent=self)
        if cevap:
            self.log_yaz(f"📥 İndirme başlatılıyor: {dosya_adi}...")
            threading.Thread(target=self.dosyayi_indir_ve_aktar, args=(link, dosya_adi), daemon=True).start()
        else:
            self.log_yaz(f"🚫 İndirme reddedildi: {dosya_adi}")

    def dosyayi_indir_ve_aktar(self, link, dosya_adi):
        kayit_klasoru = "cop31_datasets"
        if not os.path.exists(kayit_klasoru):
            os.makedirs(kayit_klasoru)

        dosya_yolu = os.path.join(kayit_klasoru, dosya_adi)

        try:
            res = requests.get(link, timeout=20)
            with open(dosya_yolu, "wb") as f:
                f.write(res.content)

            self.log_yaz(f"✅ Başarıyla indirildi: {dosya_yolu}")
            self.veriyi_ana_koda_isle(dosya_yolu, dosya_adi)

        except Exception as e:
            self.log_yaz(f"❌ İndirme hatası: {e}")

    def veriyi_ana_koda_isle(self, dosya_yolu, dosya_adi):
        """İndirilen dosyayı DOĞRUDAN ana uygulamanın (core) beynine aktarır."""
        self.log_yaz("⚙️ Veri Ana Çekirdeğe aktarılıyor. Lütfen ana pencereyi (Altar) kontrol edin...")

        # 1. Ana koddaki eski hafızayı sil (Yeni salgın/iklim verisine odaklanması için)
        self.main_app.gecmis.clear()

        # 2. Ana koddaki RAG motorunu tetikle ve yeni dosyayı doğrudan içeri al
        self.main_app._belgeyi_isle_ve_kaydet(dosya_yolu)

        # Vektörel gömme işlemi için kısa bir bekleme
        time.sleep(2)

        # 3. Prompt (İstem) oluştur
        sorgu = (
            f"--- DİKKAT: YENİ İKLİM/SAĞLIK VERİSİ İNDİRİLDİ ({dosya_adi}) ---\n"
            "Vektörel hafızana az önce yüklenen bu yeni epidemiyolojik veya hava kalitesi verisini analiz et. "
            "COP31 bağlamında, bu verilerin kırılgan gruplar üzerindeki etkisini ve olası salgın/sağlık risklerini "
            "tespit ederek acil bir erken uyarı raporu oluştur.\n"
        )

        aktif_motor = self.main_app.motor_var.get()
        secilen_dil = self.main_app.active_lang_var.get()

        self.main_app.update_chat_safe(
            f"\n📡 [COP31 KÖPRÜSÜ]: '{dosya_adi}' modül üzerinden başarıyla indirildi. Analiz başlatılıyor...\n",
            tag="warning_style", final=True)

        # 4. Modül içerisinden ana koddaki yapay zeka analizini tetikle
        if aktif_motor == "Yerel (Ollama)":
            secilen_model = self.main_app.active_model_var.get()
            threading.Thread(target=self.main_app.model_ile_konus, args=(secilen_model, secilen_dil, sorgu),
                             daemon=True).start()
        else:
            secilen_api_modeli = self.main_app.active_api_model_var.get()
            threading.Thread(target=self.main_app.api_ile_konus, args=(secilen_api_modeli, secilen_dil, sorgu),
                             daemon=True).start()

    def on_closing(self):
        self.taramaya_devam_et = False
        self.destroy()