import customtkinter as ctk
from tkinter import filedialog, messagebox
import pandas as pd
import simplekml
import os
import requests
import json
import hashlib
import uuid
from datetime import datetime
import urllib3
import re
from fractions import Fraction

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ctk.set_appearance_mode("Dark")
# Altın/Turuncu renk şeması için manuel renkler kullanacağız

class TKGMClient:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Origin': 'https://parselsorgu.tkgm.gov.tr',
            'Referer': 'https://parselsorgu.tkgm.gov.tr/'
        }
        self.il_cache = {}
        self.ilce_cache = {}
        self.mah_cache = {}
        
        self.parsel_cache_file = os.path.join(os.path.expanduser("~"), ".tkgm_parsel_cache.json")
        self.parsel_cache = {}
        if os.path.exists(self.parsel_cache_file):
            try:
                with open(self.parsel_cache_file, 'r', encoding='utf-8') as f:
                    self.parsel_cache = json.load(f)
            except:
                pass
                
        self._init_il()
        
    def to_lower(self, text):
        t = str(text).replace('I', 'ı').replace('İ', 'i').lower().strip()
        return t.replace('ı', 'i').replace('ş', 's').replace('ç', 'c').replace('ğ', 'g').replace('ö', 'o').replace('ü', 'u')
        
    def _init_il(self):
        try:
            res = requests.get('https://cbsapi.tkgm.gov.tr/megsiswebapi.v3.1/api/idariYapi/ilListe', headers=self.headers, verify=False).json()
            for il in res.get('features', []):
                name = self.to_lower(il['properties'].get('text', ''))
                self.il_cache[name] = il['properties']['id']
        except:
            pass

    def get_ilce_id(self, il_name, ilce_name):
        il_name = self.to_lower(il_name)
        if il_name not in self.il_cache:
            return None
        il_id = self.il_cache[il_name]
        
        if il_id not in self.ilce_cache:
            try:
                res = requests.get(f'https://cbsapi.tkgm.gov.tr/megsiswebapi.v3.1/api/idariYapi/ilceListe/{il_id}', headers=self.headers, verify=False).json()
                self.ilce_cache[il_id] = {}
                for ilce in res.get('features', []):
                    name = self.to_lower(ilce['properties'].get('text', ''))
                    self.ilce_cache[il_id][name] = ilce['properties']['id']
            except:
                pass
                
        ilce_name = self.to_lower(ilce_name)
        return self.ilce_cache.get(il_id, {}).get(ilce_name)
        
    def get_mah_id(self, il_name, ilce_name, mah_name):
        ilce_id = self.get_ilce_id(il_name, ilce_name)
        if not ilce_id: return None
        
        if ilce_id not in self.mah_cache:
            try:
                res = requests.get(f'https://cbsapi.tkgm.gov.tr/megsiswebapi.v3.1/api/idariYapi/mahalleListe/{ilce_id}', headers=self.headers, verify=False).json()
                self.mah_cache[ilce_id] = {}
                for mah in res.get('features', []):
                    name = self.to_lower(mah['properties'].get('text', ''))
                    self.mah_cache[ilce_id][name] = mah['properties']['id']
            except:
                pass
                
        mah_name = self.to_lower(mah_name)
        return self.mah_cache.get(ilce_id, {}).get(mah_name)

    def get_parsel(self, il_name, ilce_name, mah_name, ada, parsel):
        mah_id = self.get_mah_id(il_name, ilce_name, mah_name)
        if not mah_id: return None
        
        cache_key = f"{mah_id}_{ada}_{parsel}"
        if cache_key in self.parsel_cache:
            return self.parsel_cache[cache_key]
            
        try:
            res = requests.get(f'https://cbsapi.tkgm.gov.tr/megsiswebapi.v3.1/api/parsel/{mah_id}/{ada}/{parsel}', headers=self.headers, verify=False)
            if res.status_code == 200:
                data = res.json()
                self.parsel_cache[cache_key] = data
                try:
                    with open(self.parsel_cache_file, 'w', encoding='utf-8') as f:
                        json.dump(self.parsel_cache, f, ensure_ascii=False)
                except:
                    pass
                return data
        except:
            pass
        return None

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("GeoDaire Pro - Emlak & Harita Entegrasyonu")
        self.geometry("650x480")
        
        self.grid_columnconfigure(0, weight=1)
        
        # Premium Theme Colors
        self.primary_color = "#D4AF37" # Gold
        self.primary_hover = "#B8860B"
        
        # Header
        self.header_label = ctk.CTkLabel(self, text="GeoDaire Pro", font=ctk.CTkFont(size=32, weight="bold"), text_color=self.primary_color)
        self.header_label.grid(row=0, column=0, padx=20, pady=(30, 5))
        
        self.sub_header = ctk.CTkLabel(self, text="Daire Portföy Yönetimi ve Google Earth Aktarımı", font=ctk.CTkFont(size=14, slant="italic"))
        self.sub_header.grid(row=1, column=0, padx=20, pady=(0, 20))
        
        # File Select Frame
        self.file_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.file_frame.grid(row=2, column=0, padx=40, pady=10, sticky="ew")
        self.file_frame.grid_columnconfigure(0, weight=1)
        
        self.file_path_var = ctk.StringVar()
        self.file_entry = ctk.CTkEntry(self.file_frame, textvariable=self.file_path_var, placeholder_text="Daireleri içeren Excel dosyasını seçin...", state="readonly", height=40)
        self.file_entry.grid(row=0, column=0, padx=(0, 10), pady=10, sticky="ew")
        
        self.select_btn = ctk.CTkButton(self.file_frame, text="Gözat...", command=self.select_file, width=100, height=40, fg_color="#444", hover_color="#555")
        self.select_btn.grid(row=0, column=1, pady=10)
        
        # Process Button
        self.process_btn = ctk.CTkButton(self, text="Haritayı Oluştur (Google Earth)", command=self.process_file, 
                                         font=ctk.CTkFont(size=16, weight="bold"), height=55, fg_color=self.primary_color, text_color="black", hover_color=self.primary_hover)
        self.process_btn.grid(row=3, column=0, padx=40, pady=30, sticky="ew")

        # Status Label
        self.status_var = ctk.StringVar(value="Sisteme veri yüklemek için hazır.")
        self.status_label = ctk.CTkLabel(self, textvariable=self.status_var, font=ctk.CTkFont(size=12))
        self.status_label.grid(row=4, column=0, padx=20, pady=10)
        
        # Lisans Silme Butonu
        self.license_btn = ctk.CTkButton(self, text="Lisansı Yönet", command=self.change_license, 
                                         font=ctk.CTkFont(size=12), width=120, fg_color="transparent", border_width=1, border_color="#555", hover_color="#333")
        self.license_btn.grid(row=5, column=0, padx=20, pady=5)
        
        self.selected_file = None

    def select_file(self):
        file_path = filedialog.askopenfilename(
            title="Excel Dosyası Seç",
            filetypes=[("Excel Dosyaları", "*.xlsx *.xls")]
        )
        if file_path:
            self.selected_file = file_path
            self.file_path_var.set(file_path)
            self.status_var.set(f"Seçilen portföy: {os.path.basename(file_path)}")

    def change_license(self):
        if messagebox.askyesno("Lisansı Yönet", "Mevcut lisans anahtarınızı sistemden silmek istediğinize emin misiniz?"):
            try:
                if os.path.exists(LICENSE_FILE):
                    import ctypes
                    ctypes.windll.kernel32.SetFileAttributesW(LICENSE_FILE, 128)
                    os.remove(LICENSE_FILE)
            except Exception as e:
                print(e)
            self.destroy()

    def process_file(self):
        if not self.selected_file:
            messagebox.showwarning("Uyarı", "Lütfen bir Excel dosyası seçin!")
            return
            
        try:
            self.status_var.set("Veriler analiz ediliyor...")
            self.update()
            
            df = pd.read_excel(self.selected_file)
            
            def clean_number(x):
                x = str(x).replace(' TL', '').replace('TL', '').replace('₺', '').replace(' ', '')
                if ',' in x and '.' in x:
                    x = x.replace('.', '').replace(',', '.')
                elif ',' in x:
                    x = x.replace(',', '.')
                elif x.count('.') > 1:
                    x = x.replace('.', '')
                elif x.count('.') == 1:
                    parts = x.split('.')
                    if len(parts[1]) == 3:
                        x = x.replace('.', '')
                try:
                    return float(x)
                except:
                    return 0.0

            if 'FİYAT' in df.columns and 'BRÜT M2' in df.columns:
                df['M2 FİYATI'] = df.apply(lambda row: clean_number(row['FİYAT']) / clean_number(row['BRÜT M2']) if clean_number(row['BRÜT M2']) > 0 else 0, axis=1)
                df['M2 FİYATI'] = df['M2 FİYATI'].apply(lambda x: f"{x:,.0f} ₺".replace(',', '.'))
                df['FİYAT'] = df['FİYAT'].apply(lambda x: f"{clean_number(x):,.0f} ₺".replace(',', '.') if clean_number(x) > 0 else x)
            
            if 'TKGM LİNKİ' not in df.columns:
                df['TKGM LİNKİ'] = ""
            if 'E İMAR LİNKİ' not in df.columns:
                df['E İMAR LİNKİ'] = ""
            if 'GÜNCELLEME TARİHİ' not in df.columns:
                df['GÜNCELLEME TARİHİ'] = ""

            df = df.fillna("-")
            
            # Kategorilere göre KML Dosyaları
            kmls = {
                'satilik': simplekml.Kml(name="Satılık Daireler"),
                'kiralik': simplekml.Kml(name="Kiralık Daireler"),
                'pasif': simplekml.Kml(name="Pasif Daireler"),
                'sozlesmeli': simplekml.Kml(name="Sözleşmeli Portföyler"),
                'satildi': simplekml.Kml(name="Satıldı / Kiralandı"),
                'diger': simplekml.Kml(name="Diğer Durumlar")
            }
            
            tkgm = TKGMClient()
            points_added = {k: 0 for k in kmls.keys()}
            
            def get_row_val(row_data, *possible_keys, default='-'):
                def canonical_str(s):
                    if not s: return ''
                    return str(s).upper().replace('İ', 'I').replace('Ü', 'U').replace('Ö', 'O').replace('Ğ', 'G').replace('Ş', 'S').replace('Ç', 'C').strip()
                possible_canonicals = [canonical_str(pk) for pk in possible_keys]
                for col in row_data.index:
                    if canonical_str(col) in possible_canonicals:
                        val = row_data[col]
                        if pd.notna(val) and str(val).strip() != '' and str(val).strip().lower() != 'nan':
                            return str(val).strip()
                return default

            for index, row in df.iterrows():
                gorunurluk_val = get_row_val(row, 'GÖRÜNÜRLÜK', 'GORUNURLUK', default='Görünür')
                durum_val_check = get_row_val(row, 'DURUM', default='')
                
                g_str = str(gorunurluk_val).strip().upper().replace('İ', 'I').replace('Ü', 'U').replace('Ö', 'O')
                d_str = str(durum_val_check).strip().upper().replace('İ', 'I').replace('Ü', 'U').replace('Ö', 'O')
                
                if any(k in g_str for k in ['GORUNMEZ', 'FALSE', '0']) or any(k in d_str for k in ['GORUNMEZ']):
                    continue

                il_val = get_row_val(row, 'İL', 'IL', default='')
                ilce_val = get_row_val(row, 'İLÇE', 'ILCE', default='')
                mah_val = get_row_val(row, 'MAHALLE', default='')
                mah_val = re.sub(r'(?i)\s+\d+\s*PARSEL.*$', '', mah_val).strip()
                ada_val = get_row_val(row, 'ADA', default='')
                parsel_val_raw = get_row_val(row, 'PARSEL', default='')
                
                try:
                    if ada_val != "" and ada_val != "-": ada_val = int(float(ada_val))
                except: pass
                
                parsel_list = []
                try:
                    if parsel_val_raw != "-":
                        p_float = float(parsel_val_raw)
                        if 0 < p_float < 1:
                            frac = Fraction(p_float).limit_denominator(100)
                            parsel_list = [frac.numerator, frac.denominator]
                        else:
                            parsel_list = [int(p_float)]
                except:
                    s = str(parsel_val_raw).replace('/', ',').replace('-', ',')
                    for part in s.split(','):
                        try: parsel_list.append(int(float(part.strip())))
                        except: pass
                
                if not il_val or il_val == "-" or not ilce_val or not mah_val or ada_val == "" or not parsel_list:
                    continue
                    
                for parsel_val in parsel_list:
                    self.status_var.set(f"Konum Bulunuyor: {mah_val} {ada_val}/{parsel_val} ...")
                    self.update()
                    
                    parsel_data = tkgm.get_parsel(il_val, ilce_val, mah_val, ada_val, parsel_val)
                    if not parsel_data or parsel_data.get('type') != 'Feature':
                        continue
                        
                    geom = parsel_data.get('geometry', {})
                    poly_coords = []
                    if geom.get('type') == 'Polygon':
                        for c in geom.get('coordinates', [[]])[0]:
                            poly_coords.append((float(c[0]), float(c[1])))
                    elif geom.get('type') == 'MultiPolygon':
                        for c in geom.get('coordinates', [[[]]])[0][0]:
                            poly_coords.append((float(c[0]), float(c[1])))
                            
                    if len(poly_coords) < 3:
                        continue
                        
                    lng = sum(p[0] for p in poly_coords[:-1]) / (len(poly_coords)-1)
                    lat = sum(p[1] for p in poly_coords[:-1]) / (len(poly_coords)-1)
                    
                    # Link ve Veri Çekimi
                    mah_id = tkgm.get_mah_id(il_val, ilce_val, mah_val)
                    if mah_id:
                        tkgm_link = f"https://parselsorgu.tkgm.gov.tr/#ara/idari/{mah_id}/{ada_val}/{parsel_val}"
                    else:
                        tkgm_link = get_row_val(row, 'TKGM LİNKİ', 'TKGM LİNK', default='-')
                    
                    if 'TKGM LİNKİ' in df.columns:
                        df.at[index, 'TKGM LİNKİ'] = tkgm_link if tkgm_link != '-' else ''

                    # Veri Çekimi
                    fiyat_val = get_row_val(row, 'FİYAT', 'SATIŞ FİYATI')
                    oda_val = get_row_val(row, 'ODA SAYISI', 'ODA')
                    brut_val = get_row_val(row, 'BRÜT M2', 'BRUT M2', 'BRÜT', 'ALAN')
                    net_val = get_row_val(row, 'NET M2', 'NET')
                    kat_val = get_row_val(row, 'BULUNDUĞU KAT', 'KAT')
                    kat_sayisi_val = get_row_val(row, 'KAT SAYISI')
                    bina_yasi_val = get_row_val(row, 'BİNA YAŞI', 'BINA YASI', 'YAŞ')
                    isitma_val = get_row_val(row, 'ISITMA')
                    banyo_val = get_row_val(row, 'BANYO SAYISI', 'BANYO')
                    balkon_val = get_row_val(row, 'BALKON')
                    esyali_val = get_row_val(row, 'EŞYALI', 'ESYALI')
                    site_val = get_row_val(row, 'SİTE İÇERİSİNDE', 'SITE ICERISINDE', 'SİTE İÇİ')
                    aidat_val = get_row_val(row, 'AİDAT', 'AIDAT')
                    cephe_val = get_row_val(row, 'CEPHE')
                    tarih_val = get_row_val(row, 'GÜNCELLEME TARİHİ', 'GÜNCELLEME T', 'GÜNCELLEME TARIHI', 'TARIH')
                    adres_val = get_row_val(row, 'AÇIK ADRES', 'ACIK ADRES', 'ADRES')
                    durum_val_raw = get_row_val(row, 'DURUM', default='Diğer')
                    ilan_linki = get_row_val(row, 'SAHİBİNDEN LİNKİ', 'İLAN LİNKİ', 'İLAN LİNK', default='#')
                    
                    if not ilan_linki.startswith('http') and ilan_linki != '#' and ilan_linki != '-':
                        ilan_linki = 'http://' + ilan_linki
                        
                    pm_name = f"{fiyat_val} | {oda_val}"
                    
                    # HTML Balon Tasarımı
                    description = f"""
                    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; font-size: 14px; min-width: 300px; color: #333; background-color: #fcfcfc; padding: 15px; border-radius: 8px; border: 1px solid #ddd;">
                        
                        <div style="text-align: center; margin-bottom: 15px;">
                            <h2 style="margin: 0; color: #D4AF37; font-size: 22px;">GeoDaire Pro</h2>
                            <p style="margin: 5px 0 0 0; font-weight: bold; font-size: 18px; color: #222;">{fiyat_val}</p>
                            <span style="display: inline-block; background-color: #eee; padding: 4px 10px; border-radius: 12px; font-size: 12px; margin-top: 5px; font-weight: bold;">{durum_val_raw.upper()}</span>
                        </div>
                        
                        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                            <tr style="border-bottom: 1px solid #eee;"><td style="padding: 6px 0; color: #777; width: 40%;">Oda Sayısı:</td><td style="padding: 6px 0; font-weight: bold;">{oda_val}</td></tr>
                            <tr style="border-bottom: 1px solid #eee;"><td style="padding: 6px 0; color: #777;">Brüt / Net m²:</td><td style="padding: 6px 0; font-weight: bold;">{brut_val} / {net_val} m²</td></tr>
                            <tr style="border-bottom: 1px solid #eee;"><td style="padding: 6px 0; color: #777;">Bulunduğu Kat:</td><td style="padding: 6px 0; font-weight: bold;">{kat_val} / {kat_sayisi_val}</td></tr>
                            <tr style="border-bottom: 1px solid #eee;"><td style="padding: 6px 0; color: #777;">Bina Yaşı:</td><td style="padding: 6px 0; font-weight: bold;">{bina_yasi_val}</td></tr>
                            <tr style="border-bottom: 1px solid #eee;"><td style="padding: 6px 0; color: #777;">Isıtma:</td><td style="padding: 6px 0; font-weight: bold;">{isitma_val}</td></tr>
                            <tr style="border-bottom: 1px solid #eee;"><td style="padding: 6px 0; color: #777;">Banyo / Balkon:</td><td style="padding: 6px 0; font-weight: bold;">{banyo_val} / {balkon_val}</td></tr>
                            <tr style="border-bottom: 1px solid #eee;"><td style="padding: 6px 0; color: #777;">Eşyalı / Site İçi:</td><td style="padding: 6px 0; font-weight: bold;">{esyali_val} / {site_val}</td></tr>
                            <tr style="border-bottom: 1px solid #eee;"><td style="padding: 6px 0; color: #777;">Aidat:</td><td style="padding: 6px 0; font-weight: bold;">{aidat_val}</td></tr>
                            <tr style="border-bottom: 1px solid #eee;"><td style="padding: 6px 0; color: #777;">Cephe:</td><td style="padding: 6px 0; font-weight: bold;">{cephe_val}</td></tr>
                            <tr><td style="padding: 6px 0; color: #777;">Güncelleme:</td><td style="padding: 6px 0; font-weight: bold;">{tarih_val}</td></tr>
                        </table>
                        
                        <div style="margin-top: 15px; padding: 10px; background-color: #f5f5f5; border-radius: 5px; font-size: 11px;">
                            <b>Açık Adres:</b> {adres_val}<br/>
                            <b>Resmi Konum:</b> {ilce_val}/{mah_val} Mah. {ada_val} Ada {parsel_val} Parsel
                        </div>
                    """
                    
                    if ilan_linki != '#' and ilan_linki != '-':
                        description += f'<div style="text-align: center; margin-top: 15px;"><a href="{ilan_linki}" style="display: inline-block; padding: 8px 15px; background-color: #D4AF37; color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">İlana Git</a></div>'
                        
                    description += "</div>"
                    
                    # Kategori Belirleme
                    d_lower = tkgm.to_lower(durum_val_raw)
                    if 'satilik' in d_lower: category = 'satilik'
                    elif 'kiralik' in d_lower: category = 'kiralik'
                    elif 'pasif' in d_lower: category = 'pasif'
                    elif 'sozlesme' in d_lower: category = 'sozlesmeli'
                    elif 'satildi' in d_lower or 'kiralandi' in d_lower: category = 'satildi'
                    else: category = 'diger'
                        
                    # Renkler (Daireler için özel ikonlar kullanıyoruz)
                    color_map = {
                        'satilik': 'ffff0000',     # Mavi
                        'kiralik': 'ff00ffff',     # Sarı
                        'pasif': 'ff000080',       # Bordo
                        'sozlesmeli': 'ff00ff00',  # Yeşil
                        'satildi': 'ff0000ff',     # Kırmızı
                        'diger': 'ffaaaaaa'        # Gri
                    }
                    icon_color = color_map[category]
                    
                    current_kml = kmls[category]

                    # Bina İkonu (Placemark)
                    pnt = current_kml.newpoint(name=pm_name, coords=[(lng, lat)])
                    pnt.description = description
                    pnt.style.balloonstyle.text = "$[description]"
                    pnt.style.balloonstyle.bgcolor = "ffffffff"
                    pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/homegardenbusiness.png' # Ev ikonu
                    pnt.style.iconstyle.color = icon_color
                    pnt.style.iconstyle.scale = 1.3
                    pnt.style.labelstyle.scale = 1.2
                    pnt.style.labelstyle.color = 'ffffffff'
                    
                    # Arsa Sınırlarını da ince bir çizgi ile çizelim ki bina alanı belli olsun
                    if poly_coords[0] != poly_coords[-1]:
                        poly_coords.append(poly_coords[0])
                    pol = current_kml.newpolygon(name=pm_name, outerboundaryis=poly_coords)
                    pol.description = description
                    pol.style.balloonstyle.text = "$[description]"
                    pol.style.linestyle.color = icon_color
                    pol.style.linestyle.width = 3
                    pol.style.polystyle.color = '20ffffff' # Çok şeffaf dolgu
                    
                    points_added[category] += 1
            
            total_added = sum(points_added.values())
            
            try:
                df_to_save = df
                with pd.ExcelWriter(self.selected_file, engine='openpyxl') as writer:
                    df_to_save.to_excel(writer, index=False)
                    worksheet = list(writer.sheets.values())[0]
                    worksheet.auto_filter.ref = worksheet.dimensions
            except Exception as e:
                print("Excel kaydedilemedi:", e)

            if total_added == 0:
                messagebox.showwarning("Uyarı", "Konumlar bulunamadı! Lütfen İl, İlçe, Mahalle, Ada, Parsel bilgilerini kontrol edin.")
                self.status_var.set("İşlem başarısız.")
                return
                
            desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')
            output_dir = os.path.join(desktop_path, 'GeoDaire_Pro_Harita')
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                
            base_name = os.path.splitext(os.path.basename(self.selected_file))[0]
            self.status_var.set("KML dosyaları paketleniyor...")
            self.update()
            
            paths_to_open = []
            for cat, k in kmls.items():
                if points_added[cat] > 0:
                    output_path = os.path.join(output_dir, f"{base_name}_{cat.capitalize()}.kml")
                    k.save(output_path)
                    paths_to_open.append(output_path)
            
            self.status_var.set(f"Başarılı! Toplam {total_added} daire eklendi. Harita açılıyor...")
            self.update()
            
            if len(paths_to_open) > 1:
                master_kml = simplekml.Kml(name="Tüm Daire Portföyleri")
                for path in paths_to_open:
                    netlink = master_kml.newnetworklink(name=os.path.basename(path).replace(".kml", ""))
                    netlink.link.href = os.path.basename(path)
                
                master_path = os.path.join(output_dir, f"{base_name}_Genel_Harita.kml")
                master_kml.save(master_path)
                paths_to_open = [master_path]
            
            for path in paths_to_open:
                if os.name == 'nt':
                    os.startfile(path)
                else:
                    import subprocess, sys
                    opener = "open" if sys.platform == "darwin" else "xdg-open"
                    subprocess.call([opener, path])
        except Exception as e:
            messagebox.showerror("Hata", f"Bir hata oluştu:\n{str(e)}")
            self.status_var.set("İşlem başarısız.")

# --- LİSANS SİSTEMİ BAŞLANGICI ---
appdata_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'GeoDairePro')
if not os.path.exists(appdata_dir):
    try:
        os.makedirs(appdata_dir)
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(appdata_dir, 2)
    except:
        pass
LICENSE_FILE = os.path.join(appdata_dir, "sys_config.dat")
FIREBASE_URL = "https://earth-44a6d-default-rtdb.europe-west1.firebasedatabase.app/"
from datetime import timedelta

def get_hwid():
    mac = uuid.getnode()
    return hashlib.md5(str(mac).encode('utf-8')).hexdigest().upper()[:12]

class LicenseManager:
    @staticmethod
    def verify_license(license_key):
        if not FIREBASE_URL:
            return False, "Sistem hatası: FIREBASE_URL tanımlı değil."
            
        url = f"{FIREBASE_URL.rstrip('/')}/licenses/{license_key}.json"
        try:
            res = requests.get(url, timeout=7)
            if res.status_code != 200 or res.json() is None:
                return False, "Geçersiz veya hatalı lisans anahtarı!"
                
            data = res.json()
            my_hwid = get_hwid()
            
            try:
                tres = requests.get("http://worldtimeapi.org/api/timezone/Europe/Istanbul", timeout=5)
                current_time = datetime.strptime(tres.json()['datetime'][:19].replace('T', ' '), "%Y-%m-%d %H:%M:%S")
            except:
                current_time = datetime.now()
                
            hwids = data.get('hwids', [])
            if not hwids and data.get('hwid'):
                hwids = [data.get('hwid')]
                
            max_devices = int(data.get('max_devices', 1))
            needs_update = False
            
            if my_hwid not in hwids:
                if len(hwids) >= max_devices:
                    return False, f"Bu lisans limiti dolu! ({max_devices} cihaz)"
                hwids.append(my_hwid)
                data['hwids'] = hwids
                needs_update = True
                
            if not data.get('activation_date'):
                data['activation_date'] = current_time.strftime("%Y-%m-%d %H:%M:%S")
                needs_update = True
                
            if needs_update:
                requests.put(url, json=data, timeout=7)
                
            activation_time = datetime.strptime(data['activation_date'], "%Y-%m-%d %H:%M:%S")
            exp_time = activation_time + timedelta(days=int(data.get('duration_days', 365)))
            
            if current_time > exp_time:
                return False, f"Lisans süreniz dolmuştur."
                
            return True, exp_time.strftime("%d.%m.%Y")
        except:
            return False, "Sunucuya bağlanılamadı."

class LicenseWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("GeoDaire Pro - Aktivasyon")
        self.geometry("500x350")
        self.grid_columnconfigure(0, weight=1)
        self.attributes('-topmost', True)
        ctk.set_appearance_mode("Dark")
        
        self.label = ctk.CTkLabel(self, text="GeoDaire Pro Aktivasyonu", font=ctk.CTkFont(size=20, weight="bold"), text_color="#D4AF37")
        self.label.grid(row=0, column=0, pady=(20, 10))
        
        self.hwid = get_hwid()
        self.hwid_label = ctk.CTkLabel(self, text=f"Donanım Kimliği (HWID): {self.hwid}\nBu kodu geliştiriciye iletin.", text_color="#ccc")
        self.hwid_label.grid(row=1, column=0, pady=(0, 20))
        
        self.key_var = ctk.StringVar()
        self.key_var.trace_add("write", lambda *args: self.status_label.configure(text=""))
        
        self.key_entry = ctk.CTkEntry(self, textvariable=self.key_var, placeholder_text="XXXX-XXXX-XXXX...", width=400, height=40)
        self.key_entry.grid(row=2, column=0, pady=10)
        
        self.activate_btn = ctk.CTkButton(self, text="Uygulamayı Aç", command=self.activate, fg_color="#D4AF37", hover_color="#B8860B", text_color="black", height=45)
        self.activate_btn.grid(row=3, column=0, pady=20)
        
        self.status_label = ctk.CTkLabel(self, text="", text_color="red")
        self.status_label.grid(row=4, column=0, pady=10)

    def activate(self):
        key = self.key_entry.get().strip()
        is_valid, msg = LicenseManager.verify_license(key)
        if is_valid:
            try:
                import ctypes
                if os.path.exists(LICENSE_FILE):
                    ctypes.windll.kernel32.SetFileAttributesW(LICENSE_FILE, 128)
                with open(LICENSE_FILE, "w") as f:
                    f.write(key)
                ctypes.windll.kernel32.SetFileAttributesW(LICENSE_FILE, 2)
            except:
                pass
            messagebox.showinfo("Başarılı", f"Lisans aktif edildi!\nBitiş Tarihi: {msg}")
            self.destroy()
            start_app()
        else:
            self.status_label.configure(text=msg)

import sys

def start_app():
    app = App()
    
    auto_file = None
    if "--auto-run" in sys.argv:
        idx = sys.argv.index("--auto-run")
        if idx + 1 < len(sys.argv):
            auto_file = " ".join(sys.argv[idx+1:]).strip('"').strip("'")
            
    if auto_file and os.path.exists(auto_file):
        app.selected_file = auto_file
        app.file_path_var.set(app.selected_file)
        app.status_var.set(f"Otomatik İşlem Başlatılıyor: {os.path.basename(auto_file)}")
        
        # Override messagebox to not block if auto-running
        import tkinter.messagebox as mb
        mb.showinfo = lambda title, message: print(f"INFO: {title} - {message}")
        mb.showwarning = lambda title, message: print(f"WARNING: {title} - {message}")
        mb.showerror = lambda title, message: print(f"ERROR: {title} - {message}")
        
        def do_process():
            try:
                app.process_file()
            except Exception as e:
                print("Hata:", e)
            finally:
                app.after(1000, lambda: os._exit(0))
        app.after(500, do_process)
        
    app.mainloop()

if __name__ == "__main__":
    if os.path.exists(LICENSE_FILE):
        with open(LICENSE_FILE, "r") as f:
            saved_key = f.read().strip()
        is_valid, msg = LicenseManager.verify_license(saved_key)
        if is_valid:
            start_app()
        else:
            lw = LicenseWindow()
            lw.status_label.configure(text="Geçersiz lisans! Lütfen yeni anahtar girin.")
            lw.mainloop()
    else:
        lw = LicenseWindow()
        lw.mainloop()
