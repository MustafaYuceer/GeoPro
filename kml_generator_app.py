import customtkinter as ctk
from tkinter import filedialog, messagebox
import pandas as pd
import simplekml
import os
import requests
import json
import base64
import hmac
import hashlib
import uuid
from datetime import datetime
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

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
        
        # TKGM Parsel Cache
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
                # Cache it and save
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

        self.title("Excel + TKGM Google Earth KML Dönüştürücü")
        self.geometry("600x450")
        
        self.grid_columnconfigure(0, weight=1)
        
        # Header
        self.header_label = ctk.CTkLabel(self, text="Google Earth Pro KML Entegrasyonu", font=ctk.CTkFont(size=24, weight="bold"))
        self.header_label.grid(row=0, column=0, padx=20, pady=(30, 20))
        
        # Description
        self.desc_label = ctk.CTkLabel(self, text="Excel dosyanızı seçin. Uygulama otomatik olarak TKGM Parsel Sorgu'ya bağlanıp\ngerekli gerçek arsa poligon koordinatlarını indirecek.", 
                                       font=ctk.CTkFont(size=14), justify="center")
        self.desc_label.grid(row=1, column=0, padx=20, pady=(0, 30))
        
        # File Select Frame
        self.file_frame = ctk.CTkFrame(self)
        self.file_frame.grid(row=2, column=0, padx=40, pady=10, sticky="ew")
        self.file_frame.grid_columnconfigure(0, weight=1)
        
        self.file_path_var = ctk.StringVar()
        self.file_entry = ctk.CTkEntry(self.file_frame, textvariable=self.file_path_var, placeholder_text="Excel dosyası seçilmedi...", state="readonly")
        self.file_entry.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        self.select_btn = ctk.CTkButton(self.file_frame, text="Gözat...", command=self.select_file, width=100)
        self.select_btn.grid(row=0, column=1, padx=10, pady=10)
        
        # Process Button
        self.process_btn = ctk.CTkButton(self, text="TKGM'den İndir ve KML Oluştur", command=self.process_file, 
                                         font=ctk.CTkFont(size=16, weight="bold"), height=50, fg_color="#28a745", hover_color="#218838")
        self.process_btn.grid(row=3, column=0, padx=40, pady=40, sticky="ew")

        # Status Label
        self.status_var = ctk.StringVar(value="Hazır.")
        self.status_label = ctk.CTkLabel(self, textvariable=self.status_var, font=ctk.CTkFont(size=12))
        self.status_label.grid(row=4, column=0, padx=20, pady=10)
        
        # Lisans Silme Butonu
        self.license_btn = ctk.CTkButton(self, text="Lisansı Değiştir / Sil", command=self.change_license, 
                                         font=ctk.CTkFont(size=12, weight="bold"), width=150, fg_color="#dc3545", hover_color="#c82333")
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
            self.status_var.set(f"Seçilen dosya: {os.path.basename(file_path)}")

    def change_license(self):
        if messagebox.askyesno("Lisansı Değiştir", "Mevcut lisans anahtarınızı sistemden silmek istediğinize emin misiniz?\n\n(Program kapanacak ve açılışta yeni bir anahtar girmeniz gerekecektir.)"):
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
            messagebox.showwarning("Uyarı", "Lütfen önce bir Excel dosyası seçin!")
            return
            
        try:
            self.status_var.set("Dosya okunuyor...")
            self.update()
            
            df = pd.read_excel(self.selected_file)
            
            # Calculate Metrekare Fiyatı
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

            if 'SATIŞ FİYATI' in df.columns and 'ALAN' in df.columns:
                df['Metrekare Fiyatı'] = df.apply(lambda row: clean_number(row['SATIŞ FİYATI']) / clean_number(row['ALAN']) if clean_number(row['ALAN']) > 0 else 0, axis=1)
                # Format directly to string like 1.500 so it looks good in Excel
                df['Metrekare Fiyatı'] = df['Metrekare Fiyatı'].apply(lambda x: f"{x:,.0f}".replace(',', '.'))
                # Format SATIŞ FİYATI as 7.500.000
                df['SATIŞ FİYATI'] = df['SATIŞ FİYATI'].apply(lambda x: f"{clean_number(x):,.0f}".replace(',', '.') if clean_number(x) > 0 else x)
            if 'TKGM LİNKİ' not in df.columns:
                df['TKGM LİNKİ'] = ""
            if 'E İMAR LİNKİ' not in df.columns:
                df['E İMAR LİNKİ'] = ""
            if 'GÜNCELLEME TARİHİ' not in df.columns:
                df['GÜNCELLEME TARİHİ'] = ""
                
            df = df.fillna("")
            kmls = {
                'aktif': simplekml.Kml(name="Aktif Arsalar"),
                'pasif': simplekml.Kml(name="Pasif Arsalar"),
                'belirsiz': simplekml.Kml(name="Belirsiz Arsalar"),
                'kat_karsiligi': simplekml.Kml(name="kat_karsiligi")
            }
            
            tkgm = TKGMClient()
            
            import re
            from fractions import Fraction
            
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

            points_added = {'aktif': 0, 'pasif': 0, 'belirsiz': 0, 'kat_karsiligi': 0}
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
                    if ada_val != "": ada_val = int(float(ada_val))
                except: pass
                
                parsel_list = []
                try:
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
                
                if not il_val or not ilce_val or not mah_val or ada_val == "" or not parsel_list:
                    continue
                    
                for parsel_val in parsel_list:
                    self.status_var.set(f"TKGM Sorgulanıyor: {mah_val} {ada_val}/{parsel_val} ...")
                    self.update()
                    
                    parsel_data = tkgm.get_parsel(il_val, ilce_val, mah_val, ada_val, parsel_val)
                    if not parsel_data or parsel_data.get('type') != 'Feature':
                        print(f"Failed to fetch {mah_val} {ada_val}/{parsel_val}")
                        continue
                        
                    geom = parsel_data.get('geometry', {})
                    props = parsel_data.get('properties', {})
                    
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

                    
                    mk_fiyat_str = str(row.get('Metrekare Fiyatı', '0'))
                    kac_katli_str = str(row.get('Kaç Katlı', '')).strip()
                    if kac_katli_str == '' or kac_katli_str.lower() == 'nan':
                        kac_katli_str = '?'
                    
                    pm_name = f"{mk_fiyat_str} - {kac_katli_str}"
                    balloon_title = f"{mk_fiyat_str} - {kac_katli_str}"
                    
                    date_val = row.get('GÜNCELLEME TARİHİ', '')
                    if isinstance(date_val, pd.Timestamp):
                        date_str = date_val.strftime('%d.%m.%Y')
                    else:
                        date_str = str(date_val).split(' ')[0] if date_val else ""
                        
                    alan_val = props.get('alan', row.get('ALAN', ''))
                    fiyat_val = row.get('SATIŞ FİYATI', '')
                    
                    mah_id = tkgm.get_mah_id(il_val, ilce_val, mah_val)
                    if mah_id:
                        tkgm_link = f"https://parselsorgu.tkgm.gov.tr/#ara/idari/{mah_id}/{ada_val}/{parsel_val}"
                    else:
                        tkgm_link = str(row.get('TKGM LİNKİ', '#'))
                        if pd.isna(row.get('TKGM LİNKİ')) or str(row.get('TKGM LİNKİ')).strip() == '':
                            tkgm_link = '#'
                        
                    raw_imar_link = str(row.get('E İMAR LİNKİ', ''))
                    if pd.isna(row.get('E İMAR LİNKİ')) or raw_imar_link.strip() == '' or raw_imar_link.lower() == 'nan':
                        imar_link = '#'
                    else:
                        imar_link = raw_imar_link
                    
                    if str(tkgm_link) != '#' and not str(tkgm_link).startswith('http'):
                        tkgm_link = 'http://' + str(tkgm_link)
                        
                    if str(imar_link) != '#' and not str(imar_link).startswith('http'):
                        imar_link = 'http://' + str(imar_link)
                        
                    df.at[index, 'TKGM LİNKİ'] = tkgm_link if tkgm_link != '#' else ''
                    df.at[index, 'E İMAR LİNKİ'] = imar_link if imar_link != '#' else ''
                    
                    current_date = row.get('GÜNCELLEME TARİHİ', '')
                    if pd.isna(current_date) or str(current_date).strip() == '':
                        from datetime import datetime
                        df.at[index, 'GÜNCELLEME TARİHİ'] = datetime.today().strftime('%d.%m.%Y')
                    
                    table_title = f"{props.get('mahalleAd', mah_val)} Mahallesi {ada_val}-ada-{parsel_val}-parsel"
                    
                    description = f"""
                    <div style="font-family: sans-serif; font-size: 14px; min-width: 250px;">
                        <h3 style="margin-top: 0; margin-bottom: 10px;">{balloon_title}</h3>
                        <b>Alan:</b> {alan_val} m²<br/>
                        <b>Fiyat:</b> {fiyat_val}<br/>
                        <b>Güncelleme Tarihi:</b> {date_str}<br/>
                        <br/>
                        <a href="{tkgm_link}">TKGM Linki</a> | <a href="{imar_link}">İmar Linki</a><br/>
                        <br/>
                        <b>{table_title}</b>
                        <table border="1" cellpadding="3" style="border-collapse: collapse; font-size: 12px; width: 100%; margin-top: 5px;">
                            <tr><td style="color:#333; width: 80px;">İl</td><td>{props.get('ilAd', il_val)}</td></tr>
                            <tr><td style="color:#333">İlçe</td><td>{props.get('ilceAd', ilce_val)}</td></tr>
                            <tr><td style="color:#333">Mahalle</td><td>{props.get('mahalleAd', mah_val)}</td></tr>
                            <tr><td style="color:#333">Ada</td><td>{props.get('adaNo', ada_val)}</td></tr>
                            <tr><td style="color:#333">ParselNo</td><td>{props.get('parselNo', parsel_val)}</td></tr>
                            <tr><td style="color:#333">Alan</td><td>{props.get('alan', alan_val)}</td></tr>
                            <tr><td style="color:#333">Pafta</td><td>{props.get('pafta', '')}</td></tr>
                            <tr><td style="color:#333">Nitelik</td><td>{props.get('nitelik', '')}</td></tr>
                            <tr><td style="color:#333">Mevkii</td><td>{props.get('mevkii', '')}</td></tr>
                        </table>
                    </div>
                    """
                    
                    # Make label somewhat larger and remove 'Yol Tarifi'
                    durum_val = 'belirsiz'
                    for col in row.index:
                        if tkgm.to_lower(str(col)) == 'durum':
                            durum_val = str(row[col])
                            break
                            
                    durum_val = tkgm.to_lower(durum_val)
                    if 'kat' in durum_val:
                        category = 'kat_karsiligi'
                    elif 'aktif' in durum_val:
                        category = 'aktif'
                    elif 'pasif' in durum_val:
                        category = 'pasif'
                    else:
                        category = 'belirsiz'
                        
                    color_map = {
                        'aktif': ('ffffbf00', '40ffbf00'),  # Açık Mavi
                        'pasif': ('ff000080', '40000080'),  # Bordo
                        'belirsiz': ('ff00ffff', '4000ffff'), # Sarı
                        'kat_karsiligi': ('ff00ff00', '4000ff00')      # Yeşil
                    }
                    outline_color, fill_color = color_map[category]
                    current_kml = kmls[category]

                    pnt = current_kml.newpoint(name=pm_name, coords=[(lng, lat)])
                    pnt.description = description
                    pnt.style.balloonstyle.text = "$[description]"
                    pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/paddle/wht-blank.png'
                    pnt.style.iconstyle.color = outline_color
                    pnt.style.labelstyle.scale = 1.2
                    pnt.style.labelstyle.color = 'ffffffff'  # White text
                    
                    if poly_coords[0] != poly_coords[-1]:
                        poly_coords.append(poly_coords[0])
                    pol = current_kml.newpolygon(name=pm_name, outerboundaryis=poly_coords)
                    pol.description = description
                    pol.style.balloonstyle.text = "$[description]"
                    pol.style.linestyle.color = outline_color
                    pol.style.linestyle.width = 10
                    pol.style.polystyle.color = fill_color
                    
                    points_added[category] += 1
            
            total_added = sum(points_added.values())
            
            # Save Excel back with new links and formatted prices
            try:
                df_to_save = df
                with pd.ExcelWriter(self.selected_file, engine='openpyxl') as writer:
                    df_to_save.to_excel(writer, index=False)
                    worksheet = list(writer.sheets.values())[0]
                    worksheet.auto_filter.ref = worksheet.dimensions
            except Exception as e:
                print("Excel kaydedilemedi:", e)

            if total_added == 0:
                messagebox.showwarning("Uyarı", "Hiçbir parsel TKGM'den çekilemedi veya geçerli kayıt bulunamadı!")
                self.status_var.set("İşlem başarısız.")
                return
                
            try:
                desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')
                output_dir = os.path.join(desktop_path, 'GeoParsel_Pro Harita')
                if not os.path.exists(output_dir):
                    os.makedirs(output_dir)
            except Exception:
                output_dir = os.path.dirname(self.selected_file)
                
            base_name = os.path.splitext(os.path.basename(self.selected_file))[0]
            
            self.status_var.set("KML dosyaları oluşturuluyor...")
            self.update()
            
            paths_to_open = []
            for cat, k in kmls.items():
                if points_added[cat] > 0:
                    output_path = os.path.join(output_dir, f"{base_name}_{cat.capitalize()}_harita.kml")
                    k.save(output_path)
                    paths_to_open.append(output_path)
            
            self.status_var.set(f"Başarılı! Toplam {total_added} parsel eklendi. Google Earth açılıyor...")
            self.update()
            
            # Google Earth'ün tüm dosyaları tek seferde sorunsuz açabilmesi için bir ana (master) KML oluştur
            if len(paths_to_open) > 1:
                master_kml = simplekml.Kml(name="Tüm KML Dosyaları")
                for path in paths_to_open:
                    netlink = master_kml.newnetworklink(name=os.path.basename(path).replace(".kml", ""))
                    netlink.link.href = os.path.basename(path)
                
                master_path = os.path.join(output_dir, f"{base_name}_Tümü_harita.kml")
                master_kml.save(master_path)
                paths_to_open = [master_path] # Sadece master dosya açılsın
            
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
appdata_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'GoogleEarthKML')
if not os.path.exists(appdata_dir):
    try:
        os.makedirs(appdata_dir)
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(appdata_dir, 2)  # Klasörü gizle
    except:
        pass
LICENSE_FILE = os.path.join(appdata_dir, "sys_config.dat")
FIREBASE_URL = "https://earth-44a6d-default-rtdb.europe-west1.firebasedatabase.app/"  # ADMIN: LÜTFEN FIREBASE LİNKİNİZİ BURAYA YAPIŞTIRIN (Örn: https://projem-default-rtdb.europe-west1.firebasedatabase.app/)
from datetime import timedelta

def get_hwid():
    mac = uuid.getnode()
    return hashlib.md5(str(mac).encode('utf-8')).hexdigest().upper()[:12]

class LicenseManager:
    @staticmethod
    def verify_license(license_key):
        if not FIREBASE_URL:
            return False, "Sistem hatası: FIREBASE_URL tanımlı değil. (Geliştirici ile iletişime geçin)"
            
        url = f"{FIREBASE_URL.rstrip('/')}/licenses/{license_key}.json"
        try:
            res = requests.get(url, timeout=7)
            if res.status_code != 200 or res.json() is None:
                return False, "Geçersiz veya hatalı lisans anahtarı!"
                
            data = res.json()
            my_hwid = get_hwid()
            
            # İnternetten güvenli saati al
            try:
                tres = requests.get("http://worldtimeapi.org/api/timezone/Europe/Istanbul", timeout=5)
                current_time = datetime.strptime(tres.json()['datetime'][:19].replace('T', ' '), "%Y-%m-%d %H:%M:%S")
            except:
                current_time = datetime.now() # Fallback
                
            # Eski sürüm uyumluluğu ve liste hazırlığı
            hwids = data.get('hwids', [])
            if not hwids and data.get('hwid'):
                hwids = [data.get('hwid')]
                
            max_devices = int(data.get('max_devices', 1))
            needs_update = False
            
            # Eğer bu cihaz kayıtlı değilse eklemeye çalış
            if my_hwid not in hwids:
                if len(hwids) >= max_devices:
                    return False, f"Bu lisans için maksimum cihaz limitine ({max_devices}) ulaşıldı!"
                
                hwids.append(my_hwid)
                data['hwids'] = hwids
                needs_update = True
                
            # İlk aktivasyon ise tarihi başlat
            if not data.get('activation_date'):
                data['activation_date'] = current_time.strftime("%Y-%m-%d %H:%M:%S")
                needs_update = True
                
            # Eğer değişiklik yapıldıysa Firebase'e yaz
            if needs_update:
                put_res = requests.put(url, json=data, timeout=7)
                if put_res.status_code != 200:
                    return False, "Aktivasyon başarısız oldu, internet bağlantınızı kontrol edin."
                
            # Süre kontrolü
            activation_time = datetime.strptime(data['activation_date'], "%Y-%m-%d %H:%M:%S")
            exp_time = activation_time + timedelta(days=int(data.get('duration_days', 365)))
            
            if current_time > exp_time:
                return False, f"Lisans süreniz {exp_time.strftime('%d.%m.%Y')} tarihinde dolmuştur."
                
            return True, exp_time.strftime("%d.%m.%Y")
        except Exception as e:
            return False, "Lisans sunucusuna bağlanılamadı. Lütfen internet bağlantınızı kontrol edin."

class LicenseWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Google Earth KML - Lisans Aktivasyonu")
        self.geometry("500x350")
        self.grid_columnconfigure(0, weight=1)
        self.attributes('-topmost', True)
        
        self.label = ctk.CTkLabel(self, text="Ticari Sürüm Aktivasyonu", font=ctk.CTkFont(size=20, weight="bold"))
        self.label.grid(row=0, column=0, pady=(20, 10))
        
        self.hwid = get_hwid()
        self.hwid_label = ctk.CTkLabel(self, text=f"Donanım Kimliğiniz (HWID): {self.hwid}\nLütfen bu kodu geliştiriciye iletin.", text_color="yellow")
        self.hwid_label.grid(row=1, column=0, pady=(0, 20))
        
        self.key_var = ctk.StringVar()
        self.key_var.trace_add("write", lambda *args: self.status_label.configure(text=""))
        
        self.key_entry = ctk.CTkEntry(self, textvariable=self.key_var, placeholder_text="XXXX-XXXX-XXXX...", width=400)
        self.key_entry.grid(row=2, column=0, pady=10)
        
        self.activate_btn = ctk.CTkButton(self, text="Aktive Et", command=self.activate, fg_color="#28a745", hover_color="#218838")
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
                    ctypes.windll.kernel32.SetFileAttributesW(LICENSE_FILE, 128) # Remove hidden attribute
                with open(LICENSE_FILE, "w") as f:
                    f.write(key)
                ctypes.windll.kernel32.SetFileAttributesW(LICENSE_FILE, 2) # Add hidden attribute
            except Exception as e:
                self.status_label.configure(text=f"Lisans dosyası kaydedilemedi: {e}")
                return
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
            lw.status_label.configure(text="Eski lisansınız geçersiz veya silinmiş. Lütfen yeni anahtar girin.")
            lw.mainloop()
    else:
        lw = LicenseWindow()
        lw.mainloop()
# --- LİSANS SİSTEMİ BİTİŞİ ---
