import sys
import os
import json
import base64
import hashlib
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QFileDialog, QFontComboBox,
    QSpinBox, QColorDialog, QToolBar, QMessageBox, QStatusBar, QLabel,
    QInputDialog, QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QDockWidget, QPlainTextEdit
)
from PyQt6.QtGui import (
    QFont, QColor, QTextCursor, QAction, QTextCharFormat,
    QTextBlockFormat, QTextListFormat, QTextTableFormat, QKeySequence
)
from PyQt6.QtCore import Qt
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog


class BulDegistirPenceresi(QDialog):
    """Belge içinde kelime bulma ve değiştirme penceresi."""
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setWindowTitle("🔍 Bul ve Değiştir")
        self.setFixedSize(380, 160)

        yerlesim = QVBoxLayout(self)

        # Aranan metin
        bul_layout = QHBoxLayout()
        bul_layout.addWidget(QLabel("Aranan:"))
        self.bul_input = QLineEdit()
        bul_layout.addWidget(self.bul_input)
        yerlesim.addLayout(bul_layout)

        # Yeni metin
        degistir_layout = QHBoxLayout()
        degistir_layout.addWidget(QLabel("Yeni Metin:"))
        self.degistir_input = QLineEdit()
        degistir_layout.addWidget(self.degistir_input)
        yerlesim.addLayout(degistir_layout)

        # Butonlar
        buton_layout = QHBoxLayout()
        btn_bul = QPushButton("Sonrakini Bul")
        btn_bul.clicked.connect(self.sonrakini_bul)

        btn_degistir = QPushButton("Değiştir")
        btn_degistir.clicked.connect(self.degistir)

        btn_tumunu_degistir = QPushButton("Tümünü Değiştir")
        btn_tumunu_degistir.clicked.connect(self.tumunu_degistir)

        buton_layout.addWidget(btn_bul)
        buton_layout.addWidget(btn_degistir)
        buton_layout.addWidget(btn_tumunu_degistir)
        yerlesim.addLayout(buton_layout)

    def sonrakini_bul(self):
        aranan = self.bul_input.text()
        if not aranan:
            return
        if not self.editor.find(aranan):
            # Sayfa sonuna gelindiyse baştan tekrar ara
            self.editor.moveCursor(QTextCursor.MoveOperation.Start)
            if not self.editor.find(aranan):
                QMessageBox.information(self, "Sonuç", f"'{aranan}' belgede bulunamadı.")

    def degistir(self):
        imlec = self.editor.textCursor()
        if imlec.hasSelection() and imlec.selectedText().lower() == self.bul_input.text().lower():
            imlec.insertText(self.degistir_input.text())
        self.sonrakini_bul()

    def tumunu_degistir(self):
        aranan = self.bul_input.text()
        yeni = self.degistir_input.text()
        if not aranan:
            return

        self.editor.moveCursor(QTextCursor.MoveOperation.Start)
        sayac = 0
        imlec = self.editor.textCursor()
        imlec.beginEditBlock()

        while self.editor.find(aranan):
            aktif_imlec = self.editor.textCursor()
            aktif_imlec.insertText(yeni)
            sayac += 1

        imlec.endEditBlock()
        QMessageBox.information(self, "Tamamlandı", f"Toplam {sayac} eşleşme değiştirildi.")


class AltarEditorPro(QMainWindow):
    def __init__(self):
        super().__init__()

        self.aktif_dosya_yolu = None
        self.karanlik_mod = False
        self.degisiklik_var_mi = False

        self.setWindowTitle("Altar Metin Editörü Pro - [Yeni Belge.altar]")
        self.resize(1200, 800)

        # Ana metin alanı
        self.editor = QTextEdit()
        self.editor.setFont(QFont("Segoe UI", 12))
        self.editor.textChanged.connect(self.metin_degisti)
        self.setCentralWidget(self.editor)

        # Bileşenleri başlat
        self.yan_not_paneli_olustur()
        self.menuleri_olustur()
        self.arac_cubuklarini_olustur()
        self.durum_cubugu_olustur()
        self.tema_uygula()

    # ---------------- YAN NOT PANELİ (SCRATCHPAD) ----------------
    def yan_not_paneli_olustur(self):
        self.not_dock = QDockWidget("📌 Hızlı Notlar & Taslak (.altar'a Dahil)", self)
        self.not_dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.not_defteri = QPlainTextEdit()
        self.not_defteri.setPlaceholderText(
            "Buraya belgeyle ilgili yan notlarınızı, yapılacakları veya şablonlarınızı "
            "yazabilirsiniz.\n\nBu notlar ana belgeyi bozmaz ancak .altar dosyası "
            "kaydedildiğinde dosyanın içine özel olarak saklanır."
        )
        self.not_defteri.textChanged.connect(self.metin_degisti)
        self.not_dock.setWidget(self.not_defteri)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.not_dock)

    # ---------------- ÜST MENÜLER ----------------
    def menuleri_olustur(self):
        menubar = self.menuBar()

        # 1. Dosya Menüsü
        dosya_menu = menubar.addMenu("Dosya")

        yeni_act = QAction("📄 Yeni Belge", self)
        yeni_act.setShortcut(QKeySequence("Ctrl+N"))
        yeni_act.triggered.connect(self.yeni_dosya)
        dosya_menu.addAction(yeni_act)

        ac_act = QAction("📂 Aç (.altar / .html / .txt)", self)
        ac_act.setShortcut(QKeySequence("Ctrl+O"))
        ac_act.triggered.connect(self.dosya_ac)
        dosya_menu.addAction(ac_act)

        kaydet_act = QAction("💾 Kaydet (.altar)", self)
        kaydet_act.setShortcut(QKeySequence("Ctrl+S"))
        kaydet_act.triggered.connect(self.dosya_kaydet)
        dosya_menu.addAction(kaydet_act)

        farkli_kaydet_act = QAction("📥 Farklı Kaydet...", self)
        farkli_kaydet_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        farkli_kaydet_act.triggered.connect(self.farkli_kaydet)
        dosya_menu.addAction(farkli_kaydet_act)

        dosya_menu.addSeparator()

        pdf_act = QAction("📕 PDF Olarak Dışa Aktar", self)
        pdf_act.triggered.connect(self.pdf_aktar)
        dosya_menu.addAction(pdf_act)

        yazdir_act = QAction("🖨️ Yazdır...", self)
        yazdir_act.setShortcut(QKeySequence("Ctrl+P"))
        yazdir_act.triggered.connect(self.belge_yazdir)
        dosya_menu.addAction(yazdir_act)

        dosya_menu.addSeparator()

        cikis_act = QAction("🚪 Çıkış", self)
        cikis_act.triggered.connect(self.close)
        dosya_menu.addAction(cikis_act)

        # 2. Düzen Menüsü
        duzen_menu = menubar.addMenu("Düzen")

        geri_act = QAction("↩️ Geri Al", self)
        geri_act.setShortcut(QKeySequence("Ctrl+Z"))
        geri_act.triggered.connect(self.editor.undo)
        duzen_menu.addAction(geri_act)

        ileri_act = QAction("↪️ Yinele", self)
        ileri_act.setShortcut(QKeySequence("Ctrl+Y"))
        ileri_act.triggered.connect(self.editor.redo)
        duzen_menu.addAction(ileri_act)

        duzen_menu.addSeparator()

        bul_act = QAction("🔍 Bul ve Değiştir", self)
        bul_act.setShortcut(QKeySequence("Ctrl+F"))
        bul_act.triggered.connect(self.bul_degistir_ac)
        duzen_menu.addAction(bul_act)

        duzen_menu.addSeparator()

        buyuk_harf_act = QAction("🔠 Seçimi BÜYÜK HARF Yap", self)
        buyuk_harf_act.triggered.connect(lambda: self.harf_donustur("buyuk"))
        duzen_menu.addAction(buyuk_harf_act)

        kucuk_harf_act = QAction("🔡 Seçimi küçük harf Yap", self)
        kucuk_harf_act.triggered.connect(lambda: self.harf_donustur("kucuk"))
        duzen_menu.addAction(kucuk_harf_act)

        baslik_harf_act = QAction("🔤 Baş Harfleri Büyüt", self)
        baslik_harf_act.triggered.connect(lambda: self.harf_donustur("baslik"))
        duzen_menu.addAction(baslik_harf_act)

        temizle_act = QAction("🧹 Seçimin Biçimlendirmesini Temizle", self)
        temizle_act.triggered.connect(self.bicimlendirme_temizle)
        duzen_menu.addAction(temizle_act)

        # 3. Ekle Menüsü
        ekle_menu = menubar.addMenu("Ekle")

        gorsel_act = QAction("🖼️ Görsel Ekle (Gömülü Base64)", self)
        gorsel_act.triggered.connect(self.gorsel_ekle)
        ekle_menu.addAction(gorsel_act)

        tablo_act = QAction("📊 Tablo Ekle", self)
        tablo_act.triggered.connect(self.tablo_ekle)
        ekle_menu.addAction(tablo_act)

        kod_act = QAction("💻 Kod Bloğu Ekle", self)
        kod_act.triggered.connect(self.kod_blogu_ekle)
        ekle_menu.addAction(kod_act)

        cizgi_act = QAction("➖ Yatay Ayırıcı Çizgi Ekle", self)
        cizgi_act.triggered.connect(self.yatay_cizgi_ekle)
        ekle_menu.addAction(cizgi_act)

        tarih_act = QAction("🕒 Tarih ve Saat Damgası", self)
        tarih_act.triggered.connect(self.tarih_ekle)
        ekle_menu.addAction(tarih_act)

        # 4. Görünüm Menüsü
        gorunum_menu = menubar.addMenu("Görünüm")

        tema_act = QAction("🌙 Karanlık / Aydınlık Mod Değiştir", self)
        tema_act.triggered.connect(self.tema_degistir)
        gorunum_menu.addAction(tema_act)

        not_panel_act = self.not_dock.toggleViewAction()
        not_panel_act.setText("📌 Hızlı Not Panelini Göster/Gizle")
        gorunum_menu.addAction(not_panel_act)

        kilit_act = QAction("🔒 Salt Okunur (Kilit) Modu", self)
        kilit_act.setCheckable(True)
        kilit_act.triggered.connect(self.kilit_modu_degistir)
        gorunum_menu.addAction(kilit_act)

        gorunum_menu.addSeparator()

        yakinlastir_act = QAction("➕ Yakınlaştır", self)
        yakinlastir_act.setShortcut(QKeySequence("Ctrl++"))
        yakinlastir_act.triggered.connect(lambda: self.editor.zoomIn(2))
        gorunum_menu.addAction(yakinlastir_act)

        uzaklastir_act = QAction("➖ Uzaklaştır", self)
        uzaklastir_act.setShortcut(QKeySequence("Ctrl+-"))
        uzaklastir_act.triggered.connect(lambda: self.editor.zoomOut(2))
        gorunum_menu.addAction(uzaklastir_act)

    # ---------------- ARAÇ ÇUBUKLARI ----------------
    def arac_cubuklarini_olustur(self):
        # 1. Üst Araç Çubuğu (Dosya ve Zengin İçerik)
        ust_bar = QToolBar("Dosya ve Ekleme Araçları")
        ust_bar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, ust_bar)

        btn_yeni = QAction("📄 Yeni", self)
        btn_yeni.triggered.connect(self.yeni_dosya)
        ust_bar.addAction(btn_yeni)

        btn_ac = QAction("📂 Aç", self)
        btn_ac.triggered.connect(self.dosya_ac)
        ust_bar.addAction(btn_ac)

        btn_kaydet = QAction("💾 .altar Kaydet", self)
        btn_kaydet.triggered.connect(self.dosya_kaydet)
        ust_bar.addAction(btn_kaydet)

        btn_pdf = QAction("📕 PDF Çıktı", self)
        btn_pdf.triggered.connect(self.pdf_aktar)
        ust_bar.addAction(btn_pdf)

        ust_bar.addSeparator()

        btn_geri = QAction("↩️", self)
        btn_geri.setToolTip("Geri Al (Ctrl+Z)")
        btn_geri.triggered.connect(self.editor.undo)
        ust_bar.addAction(btn_geri)

        btn_ileri = QAction("↪️", self)
        btn_ileri.setToolTip("Yinele (Ctrl+Y)")
        btn_ileri.triggered.connect(self.editor.redo)
        ust_bar.addAction(btn_ileri)

        btn_bul = QAction("🔍 Bul", self)
        btn_bul.triggered.connect(self.bul_degistir_ac)
        ust_bar.addAction(btn_bul)

        ust_bar.addSeparator()

        btn_gorsel = QAction("🖼️ Görsel", self)
        btn_gorsel.triggered.connect(self.gorsel_ekle)
        ust_bar.addAction(btn_gorsel)

        btn_tablo = QAction("📊 Tablo", self)
        btn_tablo.triggered.connect(self.tablo_ekle)
        ust_bar.addAction(btn_tablo)

        btn_kod = QAction("💻 Kod Bloğu", self)
        btn_kod.triggered.connect(self.kod_blogu_ekle)
        ust_bar.addAction(btn_kod)

        btn_tarih = QAction("🕒 Tarih", self)
        btn_tarih.triggered.connect(self.tarih_ekle)
        ust_bar.addAction(btn_tarih)

        ust_bar.addSeparator()

        btn_tema = QAction("🌙 Tema", self)
        btn_tema.triggered.connect(self.tema_degistir)
        ust_bar.addAction(btn_tema)

        # Yeni satıra ikinci araç çubuğunu ekle
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)

        # 2. Alt Araç Çubuğu (Yazı Biçimlendirme ve Hizalama)
        format_bar = QToolBar("Biçimlendirme Araçları")
        format_bar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, format_bar)

        self.font_kutusu = QFontComboBox()
        self.font_kutusu.setCurrentFont(QFont("Segoe UI"))
        self.font_kutusu.currentFontChanged.connect(self.font_degistir)
        format_bar.addWidget(self.font_kutusu)

        self.boyut_kutusu = QSpinBox()
        self.boyut_kutusu.setRange(6, 96)
        self.boyut_kutusu.setValue(12)
        self.boyut_kutusu.valueChanged.connect(self.boyut_degistir)
        format_bar.addWidget(self.boyut_kutusu)

        format_bar.addSeparator()

        # Kalın
        kalin_act = QAction("B", self)
        kalin_act.setFont(QFont("Arial", 11, QFont.Weight.Bold.value))
        kalin_act.setShortcut(QKeySequence("Ctrl+B"))
        kalin_act.triggered.connect(self.kalin_yap)
        format_bar.addAction(kalin_act)

        # İtalik
        italik_act = QAction("I", self)
        italik_f = QFont("Arial", 11)
        italik_f.setItalic(True)
        italik_act.setFont(italik_f)
        italik_act.setShortcut(QKeySequence("Ctrl+I"))
        italik_act.triggered.connect(self.italik_yap)
        format_bar.addAction(italik_act)

        # Altı Çizili
        cizili_act = QAction("U", self)
        cizili_f = QFont("Arial", 11)
        cizili_f.setUnderline(True)
        cizili_act.setFont(cizili_f)
        cizili_act.setShortcut(QKeySequence("Ctrl+U"))
        cizili_act.triggered.connect(self.alti_cizili_yap)
        format_bar.addAction(cizili_act)

        # Üstü Çizili
        ustu_cizili_act = QAction("S̶", self)
        ustu_cizili_act.setToolTip("Üstü Çizili")
        ustu_cizili_act.triggered.connect(self.ustu_cizili_yap)
        format_bar.addAction(ustu_cizili_act)

        # Üst Simge / Alt Simge
        ust_simge_act = QAction("x²", self)
        ust_simge_act.setToolTip("Üst Simge")
        ust_simge_act.triggered.connect(self.ust_simge_yap)
        format_bar.addAction(ust_simge_act)

        alt_simge_act = QAction("x₂", self)
        alt_simge_act.setToolTip("Alt Simge")
        alt_simge_act.triggered.connect(self.alt_simge_yap)
        format_bar.addAction(alt_simge_act)

        format_bar.addSeparator()

        # Renkler
        yazi_renk_act = QAction("🎨 Yazı Rengi", self)
        yazi_renk_act.triggered.connect(self.renk_sec)
        format_bar.addAction(yazi_renk_act)

        vurgu_renk_act = QAction("🖍️ Vurgula", self)
        vurgu_renk_act.triggered.connect(self.vurgu_rengi_sec)
        format_bar.addAction(vurgu_renk_act)

        format_bar.addSeparator()

        # Hizalama
        sol_act = QAction("⬅️ Sol", self)
        sol_act.triggered.connect(lambda: self.editor.setAlignment(Qt.AlignmentFlag.AlignLeft))
        format_bar.addAction(sol_act)

        orta_act = QAction("↔️ Orta", self)
        orta_act.triggered.connect(lambda: self.editor.setAlignment(Qt.AlignmentFlag.AlignCenter))
        format_bar.addAction(orta_act)

        sag_act = QAction("➡️ Sağ", self)
        sag_act.triggered.connect(lambda: self.editor.setAlignment(Qt.AlignmentFlag.AlignRight))
        format_bar.addAction(sag_act)

        iki_yana_act = QAction("☰ İki Yana", self)
        iki_yana_act.triggered.connect(lambda: self.editor.setAlignment(Qt.AlignmentFlag.AlignJustify))
        format_bar.addAction(iki_yana_act)

        format_bar.addSeparator()

        # Listeler
        madde_act = QAction("• Liste", self)
        madde_act.triggered.connect(lambda: self.liste_olustur(QTextListFormat.Style.ListDisc))
        format_bar.addAction(madde_act)

        numara_act = QAction("1. Numaralı", self)
        numara_act.triggered.connect(lambda: self.liste_olustur(QTextListFormat.Style.ListDecimal))
        format_bar.addAction(numara_act)

    # ---------------- DURUM ÇUBUĞU (İSTATİSTİKLER) ----------------
    def durum_cubugu_olustur(self):
        self.durum_cubugu = QStatusBar()
        self.setStatusBar(self.durum_cubugu)

        self.istatistik_etiketi = QLabel(
            "Kelime: 0 | Karakter: 0 | Satır: 1 | Tahmini Okuma: 0 dk"
        )
        self.durum_cubugu.addPermanentWidget(self.istatistik_etiketi)
        self.durum_cubugu.showMessage("Altar Metin Editörü Pro hazır.", 4000)

    def metin_degisti(self):
        self.degisiklik_var_mi = True
        metin = self.editor.toPlainText()
        kelimeler = [k for k in metin.split() if k.strip()]
        kelime_sayisi = len(kelimeler)
        karakter_sayisi = len(metin)
        satir_sayisi = metin.count("\n") + 1 if metin else 1
        okuma_suresi = max(1, round(kelime_sayisi / 200)) if kelime_sayisi > 0 else 0

        self.istatistik_etiketi.setText(
            f"Kelime: {kelime_sayisi} | Karakter: {karakter_sayisi} | "
            f"Satır: {satir_sayisi} | Tahmini Okuma: ~{okuma_suresi} dk"
        )

    # ---------------- .ALTAR ÖZEL DOSYA SİSTEMİ ----------------
    def imzayi_hesapla(self, html_icerik, not_icerik):
        birlesik = (html_icerik + "||" + not_icerik).encode("utf-8")
        return hashlib.sha256(birlesik).hexdigest()

    def yeni_dosya(self):
        if self.degisiklik_kontrolu():
            self.editor.clear()
            self.not_defteri.clear()
            self.aktif_dosya_yolu = None
            self.degisiklik_var_mi = False
            self.setWindowTitle("Altar Metin Editörü Pro - [Yeni Belge.altar]")
            self.durum_cubugu.showMessage("Yeni belge oluşturuldu.", 3000)

    def dosya_kaydet(self):
        if self.aktif_dosya_yolu and self.aktif_dosya_yolu.endswith(".altar"):
            self.altar_dosyasina_yaz(self.aktif_dosya_yolu)
        else:
            self.farkli_kaydet()

    def farkli_kaydet(self):
         filtre = (
             "Altar Belgesi (*.altar);;"
             "HTML Belgesi (*.html);;"
             "Düz Metin (*.txt)"
         )
         yol, secilen_filtre = QFileDialog.getSaveFileName(
             self, "Belgeyi Kaydet", "Yeni_Belge.altar", filtre
         )
         if not yol:
             return

         if "Altar Belgesi" in secilen_filtre and not yol.endswith(".altar"):
             yol += ".altar"

         if yol.endswith(".altar"):
             self.altar_dosyasina_yaz(yol)
         elif yol.endswith(".html") or yol.endswith(".htm"):
             try:
                 with open(yol, "w", encoding="utf-8") as f:
                     f.write(self.editor.toHtml())
                 self.durum_cubugu.showMessage(f"HTML olarak kaydedildi: {yol}", 4000)
             except Exception as e:
                 QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{e}")
         else:
             try:
                 with open(yol, "w", encoding="utf-8") as f:
                     f.write(self.editor.toPlainText())
                 self.durum_cubugu.showMessage(f"Metin olarak kaydedildi: {yol}", 4000)
             except Exception as e:
                 QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{e}")

    def altar_dosyasina_yaz(self, yol):
        try:
            html_icerik = self.editor.toHtml()
            notlar = self.not_defteri.toPlainText()
            imza = self.imzayi_hesapla(html_icerik, notlar)

            altar_paketi = {
                "dosya_format": "ALTAR_PRO_BELGESI",
                "surum": "2.0",
                "kayit_tarihi": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "karanlik_mod": self.karanlik_mod,
                "yan_notlar": notlar,
                "icerik_html": html_icerik,
                "sha256_imza": imza
            }

            with open(yol, "w", encoding="utf-8") as f:
                json.dump(altar_paketi, f, ensure_ascii=False, indent=2)

            self.aktif_dosya_yolu = yol
            self.degisiklik_var_mi = False
            dosya_adi = os.path.basename(yol)
            self.setWindowTitle(f"Altar Metin Editörü Pro - [{dosya_adi}]")
            self.durum_cubugu.showMessage(f"✅ '{dosya_adi}' başarıyla kaydedildi.", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Kayıt Hatası", f".altar dosyası kaydedilemedi:\n{e}")

    def dosya_ac(self):
        if not self.degisiklik_kontrolu():
            return

        filtre = (
            "Desteklenen Belgeler (*.altar *.html *.htm *.txt *.py *.md);;"
            "Altar Belgeleri (*.altar);;"
            "Tüm Dosyalar (*.*)"
        )
        yol, _ = QFileDialog.getOpenFileName(self, "Belge Aç", "", filtre)
        if not yol:
            return

        try:
            if yol.endswith(".altar"):
                with open(yol, "r", encoding="utf-8") as f:
                    veri = json.load(f)

                if veri.get("dosya_format") != "ALTAR_PRO_BELGESI":
                    raise ValueError("Geçersiz .altar dosya yapısı!")

                html_icerik = veri.get("icerik_html", "")
                notlar = veri.get("yan_notlar", "")
                kayitli_imza = veri.get("sha256_imza", "")
                hesaplanan_imza = self.imzayi_hesapla(html_icerik, notlar)

                self.editor.setHtml(html_icerik)
                self.not_defteri.setPlainText(notlar)
                self.karanlik_mod = bool(veri.get("karanlik_mod", False))
                self.tema_uygula()

                if kayitli_imza == hesaplanan_imza:
                    self.durum_cubugu.showMessage(
                        f"🛡️ .altar dosyası açıldı (SHA-256 Bütünlük Doğrulandı - {veri.get('kayit_tarihi')})",
                        6000
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Bütünlük Uyarısı",
                        "Bu .altar dosyası harici bir programla değiştirilmiş olabilir!"
                    )
            elif yol.endswith(".html") or yol.endswith(".htm"):
                with open(yol, "r", encoding="utf-8") as f:
                    self.editor.setHtml(f.read())
                self.not_defteri.clear()
            else:
                with open(yol, "r", encoding="utf-8") as f:
                    self.editor.setPlainText(f.read())
                self.not_defteri.clear()

            self.aktif_dosya_yolu = yol
            self.degisiklik_var_mi = False
            self.setWindowTitle(f"Altar Metin Editörü Pro - [{os.path.basename(yol)}]")

        except Exception as e:
            QMessageBox.critical(self, "Açma Hatası", f"Dosya açılamadı:\n{e}")

    def pdf_aktar(self):
        yol, _ = QFileDialog.getSaveFileName(self, "PDF Olarak Kaydet", "Rapor.pdf", "PDF Dosyaları (*.pdf)")
        if yol:
            if not yol.endswith(".pdf"):
                yol += ".pdf"
            yazici = QPrinter(QPrinter.PrinterMode.HighResolution)
            yazici.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            yazici.setOutputFileName(yol)
            self.editor.document().print(yazici)
            self.durum_cubugu.showMessage(f"📕 PDF başarıyla oluşturuldu: {yol}", 5000)

    def belge_yazdir(self):
        yazici = QPrinter(QPrinter.PrinterMode.HighResolution)
        diyalog = QPrintDialog(yazici, self)
        if diyalog.exec() == QDialog.DialogCode.Accepted:
            self.editor.document().print(yazici)

    # ---------------- BİÇİMLENDİRME FONKSİYONLARI ----------------
    def font_degistir(self, font):
        fmt = QTextCharFormat()
        fmt.setFontFamilies([font.family()])
        self.editor.mergeCurrentCharFormat(fmt)

    def boyut_degistir(self, boyut):
        fmt = QTextCharFormat()
        fmt.setFontPointSize(float(boyut))
        self.editor.mergeCurrentCharFormat(fmt)

    def kalin_yap(self):
        fmt = QTextCharFormat()
        mevcut_kalin = self.editor.fontWeight() >= QFont.Weight.Bold.value
        yeni_agirlik = QFont.Weight.Normal.value if mevcut_kalin else QFont.Weight.Bold.value
        fmt.setFontWeight(yeni_agirlik)
        self.editor.mergeCurrentCharFormat(fmt)

    def italik_yap(self):
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.editor.fontItalic())
        self.editor.mergeCurrentCharFormat(fmt)

    def alti_cizili_yap(self):
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.editor.fontUnderline())
        self.editor.mergeCurrentCharFormat(fmt)

    def ustu_cizili_yap(self):
        mevcut = self.editor.currentCharFormat()
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not mevcut.fontStrikeOut())
        self.editor.mergeCurrentCharFormat(fmt)

    def ust_simge_yap(self):
        mevcut = self.editor.currentCharFormat()
        fmt = QTextCharFormat()
        if mevcut.verticalAlignment() == QTextCharFormat.VerticalAlignment.AlignSuperScript:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal)
        else:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSuperScript)
        self.editor.mergeCurrentCharFormat(fmt)

    def alt_simge_yap(self):
        mevcut = self.editor.currentCharFormat()
        fmt = QTextCharFormat()
        if mevcut.verticalAlignment() == QTextCharFormat.VerticalAlignment.AlignSubScript:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal)
        else:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSubScript)
        self.editor.mergeCurrentCharFormat(fmt)

    def renk_sec(self):
        renk = QColorDialog.getColor(self.editor.textColor(), self, "Yazı Rengi Seç")
        if renk.isValid():
            fmt = QTextCharFormat()
            fmt.setForeground(renk)
            self.editor.mergeCurrentCharFormat(fmt)

    def vurgu_rengi_sec(self):
        renk = QColorDialog.getColor(QColor("#ffff00"), self, "Vurgu (Arka Plan) Rengi Seç")
        if renk.isValid():
            fmt = QTextCharFormat()
            fmt.setBackground(renk)
            self.editor.mergeCurrentCharFormat(fmt)

    def bicimlendirme_temizle(self):
        imlec = self.editor.textCursor()
        if not imlec.hasSelection():
            imlec.select(QTextCursor.SelectionType.WordUnderCursor)
        temiz_fmt = QTextCharFormat()
        temiz_fmt.setFont(QFont("Segoe UI", 12))
        imlec.setCharFormat(temiz_fmt)

    def harf_donustur(self, mod):
        imlec = self.editor.textCursor()
        if not imlec.hasSelection():
            return
        secili = imlec.selectedText()
        if mod == "buyuk":
            imlec.insertText(secili.upper())
        elif mod == "kucuk":
            imlec.insertText(secili.lower())
        elif mod == "baslik":
            imlec.insertText(secili.title())

    def liste_olustur(self, stil):
        imlec = self.editor.textCursor()
        imlec.createList(stil)

    # ---------------- ZENGİN İÇERİK EKLEME ----------------
    def gorsel_ekle(self):
        yol, _ = QFileDialog.getOpenFileName(
            self, "Görsel Seç", "", "Resim Dosyaları (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if not yol:
            return

        genislik, tamam = QInputDialog.getInt(
            self, "Görsel Boyutu", "Görsel genişliği (piksel):", 450, 50, 1600, 25
        )
        if not tamam:
            return

        try:
            with open(yol, "rb") as f:
                ham_veri = f.read()
            b64_veri = base64.b64encode(ham_veri).decode("utf-8")
            uzanti = os.path.splitext(yol)[1].lower().replace(".", "")
            if uzanti == "jpg":
                uzanti = "jpeg"

            html_resim = (
                f'<br><img src="data:image/{uzanti};base64,{b64_veri}" '
                f'width="{genislik}" /><br>'
            )
            self.editor.textCursor().insertHtml(html_resim)
            self.durum_cubugu.showMessage("🖼️ Görsel belgeye gömülü (Base64) olarak eklendi.", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Görsel Hatası", f"Görsel eklenemedi:\n{e}")

    def tablo_ekle(self):
        satir, ok1 = QInputDialog.getInt(self, "Tablo Ekle", "Satır sayısı:", 3, 1, 50, 1)
        if not ok1:
            return
        sutun, ok2 = QInputDialog.getInt(self, "Tablo Ekle", "Sütun sayısı:", 3, 1, 15, 1)
        if not ok2:
            return

        imlec = self.editor.textCursor()
        tablo_fmt = QTextTableFormat()
        tablo_fmt.setBorder(1.0)
        tablo_fmt.setCellPadding(8.0)
        tablo_fmt.setCellSpacing(0.0)
        imlec.insertTable(satir, sutun, tablo_fmt)

    def kod_blogu_ekle(self):
        kod_html = (
            '<br><table width="100%" bgcolor="#1e1e2e" cellpadding="12" cellspacing="0" border="1">'
            '<tr><td><font face="Consolas, monospace" color="#a6e3a1">'
            '# Kodunuzu buraya yazın...<br>'
            '</font></td></tr></table><br>'
        )
        self.editor.textCursor().insertHtml(kod_html)

    def yatay_cizgi_ekle(self):
        self.editor.textCursor().insertHtml("<hr><br>")

    def tarih_ekle(self):
        simdi = datetime.now().strftime("%d.%m.%Y - %H:%M")
        self.editor.textCursor().insertText(f"[{simdi}] ")

    # ---------------- DİYALOG VE GÖRÜNÜM ----------------
    def bul_degistir_ac(self):
        pencere = BulDegistirPenceresi(self.editor, self)
        pencere.exec()

    def kilit_modu_degistir(self, kilitli_mi):
        self.editor.setReadOnly(kilitli_mi)
        durum = "🔒 Salt Okunur Modu Aktif (Düzenleme Kilitli)" if kilitli_mi else "🔓 Düzenleme Modu Aktif"
        self.durum_cubugu.showMessage(durum, 4000)

    def tema_degistir(self):
        self.karanlik_mod = not self.karanlik_mod
        self.tema_uygula()

    def tema_uygula(self):
        if self.karanlik_mod:
            self.setStyleSheet("""
                QMainWindow, QToolBar, QStatusBar, QMenuBar {
                    background-color: #1e1e2e;
                    color: #cdd6f4;
                }
                QMenuBar::item:selected, QMenu::item:selected {
                    background-color: #45475a;
                }
                QMenu {
                    background-color: #1e1e2e;
                    color: #cdd6f4;
                }
                QTextEdit, QPlainTextEdit {
                    background-color: #181825;
                    color: #cdd6f4;
                    border: 1px solid #313244;
                    padding: 12px;
                }
            """)
        else:
            self.setStyleSheet("""
                QTextEdit {
                    background-color: #ffffff;
                    color: #1e1e2e;
                    padding: 12px;
                }
                QPlainTextEdit {
                    background-color: #f8f9fa;
                    color: #1e1e2e;
                    padding: 8px;
                }
            """)

    def degisiklik_kontrolu(self):
        if not self.degisiklik_var_mi:
            return True
        cevap = QMessageBox.question(
            self,
            "Kaydedilmemiş Değişiklikler",
            "Belgede kaydedilmemiş değişiklikler var. Kaydetmek ister misiniz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
        )
        if cevap == QMessageBox.StandardButton.Yes:
            self.dosya_kaydet()
            return True
        elif cevap == QMessageBox.StandardButton.No:
            return True
        return False

    def closeEvent(self, event):
        if self.degisiklik_kontrolu():
            event.accept()
        else:
            event.ignore()


if __name__ == '__main__':
    uygulama = QApplication(sys.argv)
    pencere = AltarEditorPro()
    pencere.showMaximized()  # Her koşulda tam ekran açılmasını sağlar
    sys.exit(uygulama.exec())