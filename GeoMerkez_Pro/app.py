import os
import sys
import uuid
import hashlib
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.utils import secure_filename
from models import db, Portfolio, Note, CustomerDemand, Showing, Appointment, PriceHistory

# PyInstaller freeze support
if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
    
    appdata_dir = os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), 'GeoMerkez_Pro')
    os.makedirs(appdata_dir, exist_ok=True)
    uploads_dir = os.path.join(appdata_dir, 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    db_path = os.path.join(appdata_dir, 'geomerkez.db')
else:
    app = Flask(__name__)
    local_instance = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    os.makedirs(local_instance, exist_ok=True)
    uploads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    
    db_path = os.path.join(local_instance, 'geomerkez.db')
    appdata_dir = os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), 'GeoMerkez_Pro')

app.config['SECRET_KEY'] = 'super-secret-geomerkez-key'
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = uploads_dir

db.init_app(app)

FIREBASE_URL = "https://earth-44a6d-default-rtdb.europe-west1.firebasedatabase.app/"

LICENSE_FILE = os.path.join(appdata_dir, "sys_config.dat")

def get_hwid():
    try:
        mac = uuid.getnode()
        if mac:
            return hashlib.md5(str(mac).encode('utf-8')).hexdigest().upper()[:12]
    except:
        pass
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        if guid:
            return hashlib.md5(guid.encode('utf-8')).hexdigest().upper()[:12]
    except:
        pass
    return "UNKNOWN_HWID"

def verify_license(license_key):
    if not FIREBASE_URL:
        return False, "Sistem hatası: FIREBASE_URL tanımlı değil."
        
    url = f"{FIREBASE_URL.rstrip('/')}/licenses/{license_key}.json"
    try:
        # Windows 7 / 8 / 10 / 11 SSL Compatibility Fallback
        try:
            res = requests.get(url, timeout=7)
        except Exception:
            res = requests.get(url, timeout=7, verify=False)

        if res.status_code != 200 or res.json() is None:
            return False, "Geçersiz veya hatalı lisans anahtarı!"
            
        data = res.json()
        my_hwid = get_hwid()
        
        try:
            try:
                tres = requests.get("http://worldtimeapi.org/api/timezone/Europe/Istanbul", timeout=5)
            except Exception:
                tres = requests.get("http://worldtimeapi.org/api/timezone/Europe/Istanbul", timeout=5, verify=False)
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
            try:
                requests.put(url, json=data, timeout=7)
            except Exception:
                requests.put(url, json=data, timeout=7, verify=False)
            
        activation_time = datetime.strptime(data['activation_date'], "%Y-%m-%d %H:%M:%S")
        exp_time = activation_time + timedelta(days=int(data.get('duration_days', 365)))
        
        if current_time > exp_time:
            return False, f"Lisans süreniz dolmuştur."
            
        return True, exp_time.strftime("%d.%m.%Y %H:%M:%S")
    except Exception as e:
        # İnternet yoksa veya hata varsa yerel dosyadaki tarihi kontrol et (Offline Mod)
        if os.path.exists(LICENSE_FILE):
            try:
                with open(LICENSE_FILE, "r") as f:
                    saved_data = json.load(f)
                if saved_data.get('key') == license_key:
                    exp_time = datetime.strptime(saved_data.get('exp_time'), "%d.%m.%Y %H:%M:%S")
                    if datetime.now() < exp_time:
                        return True, saved_data.get('exp_time')
            except:
                pass
        return False, "Sunucuya bağlanılamadı ve çevrimdışı doğrulama başarısız."

@app.before_request
def require_activation():
    # Sadece belli sayfalara serbest izin ver
    allowed_endpoints = ['activation', 'static']
    if request.endpoint and request.endpoint not in allowed_endpoints:
        # Kullanıcı session'da onaylıysa her defasında Firebase'e sormaması için
        if not session.get('activated'):
            # Session yoksa dosyayı oku
            if os.path.exists(LICENSE_FILE):
                try:
                    with open(LICENSE_FILE, 'r') as f:
                        data = json.load(f)
                    
                    key = data.get('key')
                    if key:
                        success, msg = verify_license(key)
                        if success:
                            session['activated'] = True
                            session['hwid'] = get_hwid()
                            
                            # Çevrimdışı mod için yerel tarihi güncelle
                            with open(LICENSE_FILE, "w") as f:
                                json.dump({"key": key, "exp_time": msg}, f)
                                
                            return None # Yola devam
                except:
                    pass
            
            return redirect(url_for('activation'))

def sync_to_excel():
    """Tüm veritabanını anlık olarak hedeflenen Excel'lere senkronize eder."""
    try:
        current_settings = load_settings()
        daire_excel = current_settings.get('daire_excel')
        arsa_excel = current_settings.get('arsa_excel')
        
        portfolios = Portfolio.query.all()
        
        def canonical_tr(s):
            if not s: return ''
            return str(s).upper().replace('İ', 'I').replace('Ü', 'U').replace('Ö', 'O').replace('Ğ', 'G').replace('Ş', 'S').replace('Ç', 'C').strip()

        def to_upper_tr(s):
            return str(s).replace('i', 'İ').replace('ı', 'I').upper().strip()
            
        def update_key(d, val, *possible_keys):
            if val is None or str(val).strip() == '' or str(val).lower() in ['none', 'nan']:
                return
            target_keys = [to_upper_tr(pk) for pk in possible_keys]
            target_canonicals = [canonical_tr(pk) for pk in possible_keys]
            found = False
            for k in list(d.keys()):
                if to_upper_tr(k) in target_keys or canonical_tr(k) in target_canonicals:
                    d[k] = val
                    found = True
            if not found:
                d[possible_keys[0]] = val

        # Daireleri ayır ve dışa aktar
        if daire_excel and os.path.exists(os.path.dirname(daire_excel)):
            daire_data = []
            for p in portfolios:
                if p.tip == 'Daire':
                    gorunurluk_yazi = "Görünür" if p.is_active else "Görünmez"
                    row_dict = {}
                    if p.extra_data:
                        try:
                            row_dict = json.loads(p.extra_data)
                        except:
                            pass
                    
                    update_key(row_dict, p.tip, 'TİP')
                    update_key(row_dict, p.il, 'İL')
                    update_key(row_dict, p.ilce, 'İLÇE')
                    update_key(row_dict, p.mahalle, 'MAHALLE')
                    update_key(row_dict, p.ada, 'ADA')
                    update_key(row_dict, p.parsel, 'PARSEL')
                    update_key(row_dict, p.fiyat, 'FİYAT', 'SATIŞ FİYATI')
                    update_key(row_dict, p.durum, 'DURUM')
                    update_key(row_dict, p.danisman, 'Danışman', 'DANIŞMAN')
                    update_key(row_dict, p.musteri_adi, 'Müşteri Ad - Soyad', 'MÜŞTERİ AD - SOYAD', 'Mal Sahibi', 'MÜŞTERİ ADI')
                    update_key(row_dict, p.musteri_no, 'Müşteri no', 'MÜŞTERİ NO', 'Mal Sahibi Telefon', 'MÜŞTERİ TELEFON')
                    update_key(row_dict, gorunurluk_yazi, 'GÖRÜNÜRLÜK', 'GORUNURLUK')
                    update_key(row_dict, p.kat, 'KAT', 'BULUNDUĞU KAT')
                    update_key(row_dict, p.oda_sayisi, 'ODA SAYISI', 'ODA')
                    update_key(row_dict, p.brut_m2, 'BRÜT M2', 'BRUT M2', 'BRÜT')
                    update_key(row_dict, p.net_m2, 'NET M2', 'NET')
                    update_key(row_dict, p.bina_yasi, 'BİNA YAŞI', 'BINA YASI', 'YAŞ')
                    update_key(row_dict, p.ilan_linki, 'SAHİBİNDEN LİNKİ', 'İLAN LİNKİ', 'İLAN LİNK')
                    update_key(row_dict, p.e_imar_linki, 'E-İMAR LİNKİ', 'E İMAR LİNKİ', 'İMAR LİNKİ', 'İMAR LİNK')
                    update_key(row_dict, p.tkgm_linki, 'TKGM LİNKİ', 'TKGM LİNK')
                    
                    if p.display_m2_fiyati:
                        update_key(row_dict, p.display_m2_fiyati, 'Metrekare Fiyatı', 'METREKARE FİYATI', 'm² Fiyatı', 'M2 FİYATI')
                    if p.created_at:
                        update_key(row_dict, p.created_at.strftime('%Y-%m-%d %H:%M'), 'EKLENME TARİHİ', 'GÜNCELLEME TARİHİ')
                        
                    daire_data.append(row_dict)
                    
            if daire_data:
                pd.DataFrame(daire_data).to_excel(daire_excel, index=False, sheet_name='Daireler')

        # Arsaları ayır ve dışa aktar
        if arsa_excel and os.path.exists(os.path.dirname(arsa_excel)):
            arsa_data = []
            for p in portfolios:
                if p.tip == 'Arsa':
                    gorunurluk_yazi = "Görünür" if p.is_active else "Görünmez"
                    row_dict = {}
                    if p.extra_data:
                        try:
                            row_dict = json.loads(p.extra_data)
                        except:
                            pass
                    
                    update_key(row_dict, p.tip, 'TİP')
                    update_key(row_dict, p.il, 'İL')
                    update_key(row_dict, p.ilce, 'İLÇE')
                    update_key(row_dict, p.mahalle, 'MAHALLE')
                    update_key(row_dict, p.ada, 'ADA')
                    update_key(row_dict, p.parsel, 'PARSEL')
                    update_key(row_dict, p.fiyat, 'SATIŞ FİYATI', 'FİYAT')
                    update_key(row_dict, p.durum, 'DURUM')
                    update_key(row_dict, p.danisman, 'Danışman', 'DANIŞMAN')
                    update_key(row_dict, p.musteri_adi, 'Müşteri Ad - Soyad', 'MÜŞTERİ AD - SOYAD', 'Mal Sahibi', 'MÜŞTERİ ADI')
                    update_key(row_dict, p.musteri_no, 'Müşteri no', 'MÜŞTERİ NO', 'Mal Sahibi Telefon', 'MÜŞTERİ TELEFON')
                    update_key(row_dict, gorunurluk_yazi, 'GÖRÜNÜRLÜK', 'GORUNURLUK')
                    update_key(row_dict, p.ilan_linki, 'SAHİBİNDEN LİNKİ', 'İLAN LİNKİ', 'İLAN LİNK')
                    update_key(row_dict, p.e_imar_linki, 'E İMAR LİNKİ', 'E-İMAR LİNKİ', 'İMAR LİNKİ', 'İMAR LİNK')
                    update_key(row_dict, p.tkgm_linki, 'TKGM LİNKİ', 'TKGM LİNK')
                    
                    if p.display_m2_fiyati:
                        update_key(row_dict, p.display_m2_fiyati, 'Metrekare Fiyatı', 'METREKARE FİYATI', 'm² Fiyatı', 'M2 FİYATI')
                    if p.created_at:
                        update_key(row_dict, p.created_at.strftime('%Y-%m-%d %H:%M'), 'GÜNCELLEME TARİHİ', 'EKLENME TARİHİ')
                        
                    arsa_data.append(row_dict)
                    
            if arsa_data:
                pd.DataFrame(arsa_data).to_excel(arsa_excel, index=False, sheet_name='Arsalar')
                
    except Exception as e:
        print(f"Excel senkronizasyon hatası: {e}")

with app.app_context():
    db.create_all()
    # Otomatik SQLite Sütun Göçü (Migration)
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            columns_info = conn.execute(text("PRAGMA table_info(portfolio);")).fetchall()
            existing_cols = [col[1] for col in columns_info]
            
            if 'danisman' not in existing_cols:
                conn.execute(text("ALTER TABLE portfolio ADD COLUMN danisman VARCHAR(100);"))
            if 'musteri_adi' not in existing_cols:
                conn.execute(text("ALTER TABLE portfolio ADD COLUMN musteri_adi VARCHAR(100);"))
            if 'musteri_no' not in existing_cols:
                conn.execute(text("ALTER TABLE portfolio ADD COLUMN musteri_no VARCHAR(50);"))
            conn.commit()
    except Exception as migration_err:
        print("Veritabanı sütun güncelleme hatası:", migration_err)

@app.route('/activation', methods=['GET', 'POST'])
def activation():
    if session.get('activated'):
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        code = request.form.get('code')
        if not code:
            flash('Lütfen aktivasyon kodunu girin.', 'error')
            return redirect(url_for('activation'))
            
        success, msg = verify_license(code.strip())
        
        if success:
            session['activated'] = True
            session['hwid'] = get_hwid()
            
            # Yerel dosyaya kaydet
            try:
                with open(LICENSE_FILE, "w") as f:
                    json.dump({"key": code.strip(), "exp_time": msg}, f)
            except Exception as e:
                pass
                
            flash('Aktivasyon Başarılı!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash(msg, 'error')
            
    return render_template('activation.html')

import subprocess
import threading

SETTINGS_FILE = os.path.join(appdata_dir, 'settings.json')

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    alt_settings = os.path.join(app.config['UPLOAD_FOLDER'], 'settings.json')
    if os.path.exists(alt_settings):
        try:
            with open(alt_settings, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"daire_excel": "", "arsa_excel": "", "musteri_excel": ""}

def save_settings(settings_data):
    os.makedirs(appdata_dir, exist_ok=True)
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings_data, f, ensure_ascii=False, indent=4)
    try:
        alt_settings = os.path.join(app.config['UPLOAD_FOLDER'], 'settings.json')
        os.makedirs(os.path.dirname(alt_settings), exist_ok=True)
        with open(alt_settings, 'w', encoding='utf-8') as f:
            json.dump(settings_data, f, ensure_ascii=False, indent=4)
    except Exception:
        pass

def sync_customers_to_excel():
    """Tüm müşteri taleplerini anlık olarak hedef Müşteri Excel dosyasına senkronize eder."""
    try:
        current_settings = load_settings()
        musteri_excel = current_settings.get('musteri_excel')
        if not musteri_excel:
            return
            
        excel_dir = os.path.dirname(os.path.abspath(musteri_excel))
        if excel_dir:
            os.makedirs(excel_dir, exist_ok=True)
            
        customers = CustomerDemand.query.order_by(CustomerDemand.created_at.desc()).all()
        rows = []
        for c in customers:
            rows.append({
                'Müşteri Adı - Soyadı': c.ad_soyad or '',
                'İletişim / Telefon': c.telefon or '',
                'Aradığı Tip': c.tip or 'Hepsi',
                'İl': c.il or '',
                'İlçe': c.ilce or '',
                'Mahalle': c.mahalle or '',
                'Min Bütçe (TL)': c.min_fiyat if c.min_fiyat else '',
                'Max Bütçe (TL)': c.max_fiyat if c.max_fiyat else '',
                'Min m²': c.min_m2 if c.min_m2 else '',
                'Max m²': c.max_m2 if c.max_m2 else '',
                'Durum': c.durum or 'Aktif',
                'Özel Notlar': c.notlar or '',
                'Eklenme Tarihi': c.created_at.strftime('%Y-%m-%d %H:%M') if c.created_at else ''
            })
            
        df = pd.DataFrame(rows)
        if df.empty:
            df = pd.DataFrame(columns=[
                'Müşteri Adı - Soyadı', 'İletişim / Telefon', 'Aradığı Tip', 'İl', 'İlçe', 'Mahalle',
                'Min Bütçe (TL)', 'Max Bütçe (TL)', 'Min m²', 'Max m²', 'Durum', 'Özel Notlar', 'Eklenme Tarihi'
            ])
        df.to_excel(musteri_excel, index=False, sheet_name='Müşteri Talepleri', engine='openpyxl')
    except Exception as e:
        print("Müşteri Excel senkronizasyon hatası:", e)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'hwid' not in session:
        return redirect(url_for('activation'))
        
    current_settings = load_settings()
    
    if request.method == 'POST':
        current_settings['daire_excel'] = request.form.get('daire_excel', '').strip()
        current_settings['arsa_excel'] = request.form.get('arsa_excel', '').strip()
        current_settings['musteri_excel'] = request.form.get('musteri_excel', '').strip()
        save_settings(current_settings)
        
        # Müşteri Excel'ini anında oluştur/senkronize et
        sync_customers_to_excel()
        
        flash('Ayarlar başarıyla kaydedildi!', 'success')
        return redirect(url_for('settings'))
        
    return render_template('settings.html', settings=current_settings)

@app.route('/run_app/<app_type>')
def run_app(app_type):
    if 'hwid' not in session:
        return redirect(url_for('activation'))
        
    # Anlık veritabanı durumunu Excel'e senkronize et!
    sync_to_excel()
    
    current_settings = load_settings()
    
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        exe_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    if app_type == 'daire':
        target_excel = current_settings.get('daire_excel')
        exe_candidates = [
            os.path.join(exe_dir, 'GeoDaire_Pro.exe'),
            os.path.join(exe_dir, 'GeoDaire_Pro', 'GeoDaire_Pro.exe'),
            os.path.join(exe_dir, 'GeoDaire_Pro', 'dist', 'GeoDaire_Pro.exe')
        ]
        exe_path = next((p for p in exe_candidates if os.path.exists(p)), None)
        script_path = os.path.join(exe_dir, 'GeoDaire_Pro', 'geodaire_pro_app.py')
        
        appdata_app_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'GeoDairePro')
        license_file = os.path.join(appdata_app_dir, "sys_config.dat")

    elif app_type == 'arsa':
        target_excel = current_settings.get('arsa_excel')
        exe_candidates = [
            os.path.join(exe_dir, 'GeoParsel_Pro.exe'),
            os.path.join(exe_dir, 'kml_generator_app.exe'),
            os.path.join(exe_dir, 'dist', 'GeoParsel_Pro.exe')
        ]
        exe_path = next((p for p in exe_candidates if os.path.exists(p)), None)
        script_path = os.path.join(exe_dir, 'kml_generator_app.py')
        
        appdata_app_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'GoogleEarthKML')
        license_file = os.path.join(appdata_app_dir, "sys_config.dat")

    else:
        flash('Geçersiz uygulama tipi!', 'danger')
        return redirect(url_for('dashboard'))
        
    if not os.path.exists(license_file):
        flash(f'{app_type.capitalize()} uygulaması için ürün anahtarı bulunamadı! Lütfen önce o uygulamayı normal şekilde açıp lisansınızı girin.', 'danger')
        return redirect(url_for('dashboard'))
        
    if not target_excel or not os.path.exists(target_excel):
        flash(f'Lütfen ayarlardan {app_type.capitalize()} Excel yolunu doğru bir şekilde belirleyin!', 'danger')
        return redirect(url_for('dashboard'))
        
    if not exe_path and not os.path.exists(script_path):
        flash('Çalıştırılacak uygulamanın EXE veya Python dosyası bulunamadı!', 'danger')
        return redirect(url_for('dashboard'))

    def run_script():
        if exe_path and os.path.exists(exe_path):
            subprocess.Popen([exe_path, "--auto-run", target_excel])
        elif os.path.exists(script_path):
            subprocess.Popen([sys.executable, script_path, "--auto-run", target_excel])
        
    threading.Thread(target=run_script).start()
    
    flash(f'{app_type.capitalize()} uygulaması arka planda başlatıldı! Lütfen bekleyin, Google Earth açılacaktır.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    # Opsiyonel olarak lisans dosyasını silebiliriz ama genelde cihaz lisanslı kalır.
    # os.remove(LICENSE_FILE) 
    return redirect(url_for('activation'))

@app.route('/')
def dashboard():
    if not session.get('activated'):
        return redirect(url_for('activation'))
        
    tip_filter = request.args.get('tip', 'all')
    search = request.args.get('search', '').strip()
    sort_by = request.args.get('sort_by', 'created_at')
    sort_dir = request.args.get('sort_dir', 'desc')
    page = request.args.get('page', 1, type=int)
    show_all = request.args.get('show_all', '0')
    
    selected_il = request.args.getlist('il')
    selected_durum = request.args.getlist('durum')
    selected_ilce = request.args.getlist('ilce')
    selected_mahalle = request.args.getlist('mahalle')

    query = Portfolio.query
    
    if tip_filter == 'Daire':
        query = query.filter_by(tip='Daire')
    elif tip_filter == 'Arsa':
        query = query.filter_by(tip='Arsa')

    if selected_il:
        conditions = [Portfolio.il.ilike(f"%{i}%") for i in selected_il]
        query = query.filter(db.or_(*conditions))

    if selected_durum:
        conditions = [Portfolio.durum.ilike(f"%{d}%") for d in selected_durum]
        query = query.filter(db.or_(*conditions))

    if selected_ilce:
        conditions = [Portfolio.ilce.ilike(f"%{i}%") for i in selected_ilce]
        query = query.filter(db.or_(*conditions))

    if selected_mahalle:
        conditions = [Portfolio.mahalle.ilike(f"%{m}%") for m in selected_mahalle]
        query = query.filter(db.or_(*conditions))

    if search:
        query = query.filter(
            db.or_(
                Portfolio.il.ilike(f'%{search}%'),
                Portfolio.ilce.ilike(f'%{search}%'),
                Portfolio.mahalle.ilike(f'%{search}%'),
                Portfolio.ada.ilike(f'%{search}%'),
                Portfolio.parsel.ilike(f'%{search}%'),
                Portfolio.fiyat.ilike(f'%{search}%')
            )
        )
        
    sort_column = None
    if sort_by == 'il': sort_column = Portfolio.il
    elif sort_by == 'ilce': sort_column = Portfolio.ilce
    elif sort_by == 'mahalle': sort_column = Portfolio.mahalle
    elif sort_by == 'ada': sort_column = Portfolio.ada
    elif sort_by == 'parsel': sort_column = Portfolio.parsel
    elif sort_by == 'fiyat': sort_column = Portfolio.fiyat
    elif sort_by == 'durum': sort_column = Portfolio.durum
    elif sort_by == 'is_active': sort_column = Portfolio.is_active
    elif sort_by in ['m2', 'brut_m2']: sort_column = Portfolio.brut_m2
    elif hasattr(Portfolio, sort_by): sort_column = getattr(Portfolio, sort_by)

    if sort_column is not None:
        if sort_dir == 'asc':
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(Portfolio.is_active.desc(), Portfolio.created_at.desc())
        
    per_page = 999999 if show_all == '1' else 20
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    portfolios = pagination.items

    # Türkiye 81 İl ve İlçe Listesi
    from turkey_data import TURKEY_CITIES, get_all_ils, get_ilces_by_il

    db_ils = [r[0] for r in db.session.query(Portfolio.il).distinct().all() if r[0]]
    filter_ils = sorted(list(set(get_all_ils() + db_ils)))

    filter_ilces = []
    if selected_il:
        for il_item in selected_il:
            filter_ilces.extend(get_ilces_by_il(il_item))
        db_ilces = [r[0] for r in db.session.query(Portfolio.ilce).distinct().all() if r[0]]
        filter_ilces.extend(db_ilces)
    else:
        db_ilces = [r[0] for r in db.session.query(Portfolio.ilce).distinct().all() if r[0]]
        denizli_ilces = get_ilces_by_il('Denizli')
        filter_ilces = db_ilces + denizli_ilces

    filter_ilces = sorted(list(set(filter_ilces)))
    filter_mahalles = sorted([r[0] for r in db.session.query(Portfolio.mahalle).distinct().all() if r[0]])
    filter_durums = ['aktif', 'pasif', 'kat', 'belirsiz', 'Satılık', 'Kiralık']
        
    # Dynamic m² Chart Data Calculation based on selected tab (tip_filter):
    chart_query = Portfolio.query
    if tip_filter == 'Daire':
        chart_query = chart_query.filter_by(tip='Daire')
    elif tip_filter == 'Arsa':
        chart_query = chart_query.filter_by(tip='Arsa')

    all_filtered_ports = chart_query.all()
    mahalle_m2_sums = {}
    mahalle_m2_counts = {}
    for p in all_filtered_ports:
        m_name = (p.mahalle or 'Diğer').upper().strip()
        m2_price_str = p.display_m2_fiyati
        if m2_price_str:
            try:
                num = float(m2_price_str.replace('.', '').replace(',', '.'))
                mahalle_m2_sums[m_name] = mahalle_m2_sums.get(m_name, 0.0) + num
                mahalle_m2_counts[m_name] = mahalle_m2_counts.get(m_name, 0) + 1
            except:
                pass
                
    mahalle_avg_m2 = {}
    for m, sum_val in mahalle_m2_sums.items():
        if mahalle_m2_counts[m] > 0:
            mahalle_avg_m2[m] = round(sum_val / mahalle_m2_counts[m], 0)
            
    # Sort top 7 neighborhoods by average m² price
    top_mahalles = sorted(mahalle_avg_m2.items(), key=lambda x: x[1], reverse=True)[:7]
    chart_labels = [item[0] for item in top_mahalles]
    chart_values = [item[1] for item in top_mahalles]

    return render_template(
        'dashboard.html', 
        portfolios=portfolios, 
        current_tip=tip_filter, 
        pagination=pagination,
        filter_ils=filter_ils,
        filter_ilces=filter_ilces,
        filter_mahalles=filter_mahalles,
        filter_durums=filter_durums,
        selected_il=selected_il,
        selected_durum=selected_durum,
        selected_ilce=selected_ilce,
        selected_mahalle=selected_mahalle,
        show_all=show_all,
        chart_labels=json.dumps(chart_labels, ensure_ascii=False),
        chart_values=json.dumps(chart_values),
        turkey_cities_json=json.dumps(TURKEY_CITIES, ensure_ascii=False)
    )

def import_excel_file_to_db(filepath, secilen_tip):
    if not filepath or not os.path.exists(filepath):
        return 0
    try:
        df = pd.read_excel(filepath)
        def to_upper_tr(s):
            return str(s).replace('i', 'İ').replace('ı', 'I').upper().strip()

        def get_val(row_data, *possible_keys):
            target_keys = [to_upper_tr(pk) for pk in possible_keys]
            for k in row_data.keys():
                if to_upper_tr(k) in target_keys:
                    return str(row_data[k]).strip()
            return ''

        updated_count = 0
        for index, row in df.iterrows():
            row_dict_temp = row.to_dict()
            il = get_val(row_dict_temp, 'İL', 'IL')
            if il == 'nan' or not il: continue 
            
            ilce = get_val(row_dict_temp, 'İLÇE', 'ILCE')
            mahalle = get_val(row_dict_temp, 'MAHALLE')
            ada = get_val(row_dict_temp, 'ADA')
            parsel = get_val(row_dict_temp, 'PARSEL')
            fiyat = get_val(row_dict_temp, 'FİYAT', 'SATIŞ FİYATI')
            durum = get_val(row_dict_temp, 'DURUM')
            
            danisman = get_val(row_dict_temp, 'DANIŞMAN', 'DANISMAN')
            musteri_adi = get_val(row_dict_temp, 'MÜŞTERİ AD - SOYAD', 'MÜŞTERİ ADI', 'MÜŞTERİ AD SOYAD', 'MAL SAHİBİ', 'MUSTERI ADI')
            musteri_no = get_val(row_dict_temp, 'MÜŞTERİ NO', 'MÜŞTERİ TELEFON', 'MAL SAHİBİ TELEFON', 'DANİŞMAN TELEFON', 'MUSTERI NO')

            kat = get_val(row_dict_temp, 'KAT', 'BULUNDUĞU KAT')
            oda_sayisi = get_val(row_dict_temp, 'ODA SAYISI', 'ODA')
            brut_m2 = get_val(row_dict_temp, 'BRÜT M2', 'BRUT M2', 'BRÜT', 'ALAN')
            net_m2 = get_val(row_dict_temp, 'NET M2', 'NET')
            bina_yasi = get_val(row_dict_temp, 'BİNA YAŞI', 'BINA YASI', 'YAŞ')
            
            ilan_linki = get_val(row_dict_temp, 'SAHİBİNDEN LİNKİ', 'İLAN LİNKİ', 'İLAN LİNK')
            e_imar_linki = get_val(row_dict_temp, 'E-İMAR LİNKİ', 'E İMAR LİNKİ', 'İMAR LİNKİ', 'İMAR LİNK')
            tkgm_linki = get_val(row_dict_temp, 'TKGM LİNKİ', 'TKGM LİNK')
            gorunurluk = get_val(row_dict_temp, 'GÖRÜNÜRLÜK', 'GORUNURLUK')
            
            is_active_val = True
            if gorunurluk:
                is_active_val = str(gorunurluk).strip().lower() not in ['görünmez', 'gorunmez', 'false', '0']
            
            if durum == 'nan': durum = ''
            if fiyat == 'nan': fiyat = ''
            if danisman == 'nan': danisman = ''
            if musteri_adi == 'nan': musteri_adi = ''
            if musteri_no == 'nan': musteri_no = ''
            if kat == 'nan': kat = ''
            if oda_sayisi == 'nan': oda_sayisi = ''
            if brut_m2 == 'nan': brut_m2 = ''
            if net_m2 == 'nan': net_m2 = ''
            if bina_yasi == 'nan': bina_yasi = ''
            if ilan_linki == 'nan': ilan_linki = ''
            if e_imar_linki == 'nan': e_imar_linki = ''
            if tkgm_linki == 'nan': tkgm_linki = ''
            
            raw_dict = row.to_dict()
            import math
            clean_dict = {}
            for k, v in raw_dict.items():
                if isinstance(v, float) and math.isnan(v):
                    clean_dict[k] = ''
                elif str(type(v)) == "<class 'pandas._libs.tslibs.timestamps.Timestamp'>" or 'Timestamp' in str(type(v)):
                    clean_dict[k] = v.strftime('%Y-%m-%d %H:%M:%S')
                elif str(type(v)) == "<class 'datetime.datetime'>":
                    clean_dict[k] = v.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    clean_dict[k] = v
                    
            extra_data_json = json.dumps(clean_dict, ensure_ascii=False)
            
            clean_il = il if il != 'nan' else ''
            clean_ilce = ilce if ilce != 'nan' else ''
            clean_mahalle = mahalle if mahalle != 'nan' else ''
            clean_ada = ada if ada != 'nan' else ''
            clean_parsel = parsel if parsel != 'nan' else ''
            clean_fiyat = fiyat if fiyat != 'nan' else ''
            clean_durum = durum if durum != 'nan' else ''
            
            existing = Portfolio.query.filter_by(
                tip=secilen_tip,
                il=clean_il,
                ilce=clean_ilce,
                mahalle=clean_mahalle,
                ada=clean_ada,
                parsel=clean_parsel
            ).first()
            
            if existing:
                if clean_fiyat: existing.fiyat = clean_fiyat
                if clean_durum: existing.durum = clean_durum
                if danisman: existing.danisman = danisman
                if musteri_adi: existing.musteri_adi = musteri_adi
                if musteri_no: existing.musteri_no = musteri_no
                if kat: existing.kat = kat
                if oda_sayisi: existing.oda_sayisi = oda_sayisi
                if brut_m2: existing.brut_m2 = brut_m2
                if net_m2: existing.net_m2 = net_m2
                if bina_yasi: existing.bina_yasi = bina_yasi
                if ilan_linki: existing.ilan_linki = ilan_linki
                if e_imar_linki: existing.e_imar_linki = e_imar_linki
                if tkgm_linki: existing.tkgm_linki = tkgm_linki
                
                existing_extra = {}
                if existing.extra_data:
                    try: existing_extra = json.loads(existing.extra_data)
                    except: pass
                existing_extra.update(clean_dict)
                
                # Kullanıcının GeoMerkez Pro'daki Görünürlük seçimini koru
                current_gorunurluk = "Görünür" if existing.is_active else "Görünmez"
                for k in list(existing_extra.keys()):
                    if to_upper_tr(k) in [to_upper_tr('GÖRÜNÜRLÜK'), to_upper_tr('GORUNURLUK')]:
                        existing_extra[k] = current_gorunurluk
                existing_extra['GÖRÜNÜRLÜK'] = current_gorunurluk
                existing.extra_data = json.dumps(existing_extra, ensure_ascii=False)
                updated_count += 1
            else:
                new_port = Portfolio(
                    tip=secilen_tip,
                    il=clean_il,
                    ilce=clean_ilce,
                    mahalle=clean_mahalle,
                    ada=clean_ada,
                    parsel=clean_parsel,
                    fiyat=clean_fiyat,
                    durum=clean_durum,
                    danisman=danisman,
                    musteri_adi=musteri_adi,
                    musteri_no=musteri_no,
                    kat=kat,
                    oda_sayisi=oda_sayisi,
                    brut_m2=brut_m2,
                    net_m2=net_m2,
                    bina_yasi=bina_yasi,
                    ilan_linki=ilan_linki,
                    e_imar_linki=e_imar_linki,
                    tkgm_linki=tkgm_linki,
                    is_active=is_active_val,
                    extra_data=extra_data_json
                )
                db.session.add(new_port)
                updated_count += 1
                
        db.session.commit()
        return updated_count
    except Exception as e:
        print("Excel okuma hatası:", e)
        return 0

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        filepath = request.form.get('filepath')
        file = request.files.get('file')
        
        # "Yol olarak kopyala" yapıldığında gelen çift tırnakları temizle
        if filepath:
            filepath = filepath.strip('"').strip("'")
            
        # Eğer ikisi de boşsa hata ver
        if not filepath and (not file or file.filename == ''):
            flash('Dosya yolu girilmedi veya dosya seçilmedi!', 'danger')
            return redirect(request.url)

        # 1. Öncelik: Sürükle Bırak (File var ise)
        if file and file.filename != '':
            if file.filename.endswith('.xlsx') or file.filename.endswith('.xls'):
                filename = secure_filename(file.filename)
                filepath = os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                file.save(filepath)
            else:
                flash('Lütfen sadece Excel dosyası yükleyin.', 'danger')
                return redirect(request.url)
        # 2. Öncelik: Dosya Yolu
        else:
            if not os.path.exists(filepath):
                flash('Girdiğiniz dosya yolu bulunamadı!', 'danger')
                return redirect(request.url)
            
        if filepath and (filepath.endswith('.xlsx') or filepath.endswith('.xls')):
            
            # Form'dan gelen "tip" değerini al (Varsayılan Daire)
            secilen_tip = request.form.get('tip', 'Daire')
            
            # Otomatik ayar kaydetme: Yüklenen dosyanın yolunu otomatik olarak Ayarlara kaydet
            current_settings = load_settings()
            if secilen_tip == 'Daire':
                current_settings['daire_excel'] = filepath
            elif secilen_tip in ['Müsteri', 'Müşteri']:
                current_settings['musteri_excel'] = filepath
            else:
                current_settings['arsa_excel'] = filepath
            save_settings(current_settings)
            
            # Müşteri Excel Yükleme İşlemi
            if secilen_tip in ['Müsteri', 'Müşteri']:
                try:
                    # Dosya yoksa veya 0-byte (boş) ise otomatik başlıklarla oluştur ve bilgilendir
                    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
                        sync_customers_to_excel()
                        flash('Girdiğiniz Excel dosyası boş olduğu için standart müşteri başlıklarıyla otomatik olarak oluşturuldu ve eşitlendi.', 'info')
                        return redirect(url_for('list_customers'))

                    try:
                        df = pd.read_excel(filepath, engine='openpyxl')
                    except Exception:
                        df = pd.read_excel(filepath)

                    def to_upper_tr(s):
                        return str(s).replace('i', 'İ').replace('ı', 'I').upper().strip()

                    def get_val(row_data, *possible_keys):
                        target_keys = [to_upper_tr(pk) for pk in possible_keys]
                        for k in row_data.keys():
                            if to_upper_tr(k) in target_keys:
                                return str(row_data[k]).strip()
                        return ''

                    added_count = 0
                    for index, row in df.iterrows():
                        row_dict_temp = row.to_dict()
                        ad_soyad = get_val(row_dict_temp, 'MÜŞTERİ ADI - SOYADI', 'MÜŞTERİ ADI', 'MÜŞTERİ AD SOYAD', 'AD SOYAD', 'MÜŞTERİ')
                        if not ad_soyad or ad_soyad == 'nan':
                            continue
                            
                        telefon = get_val(row_dict_temp, 'İLETİŞİM / TELEFON', 'TELEFON', 'İLETİŞİM', 'MÜŞTERİ NO')
                        tip = get_val(row_dict_temp, 'ARADIĞI TİP', 'TİP', 'GAYRİMENKUL TİPİ') or 'Hepsi'
                        il = get_val(row_dict_temp, 'İL', 'IL', 'ŞEHİR')
                        ilce = get_val(row_dict_temp, 'İLÇE', 'ILCE')
                        mahalle = get_val(row_dict_temp, 'MAHALLE')
                        
                        min_fiyat = clean_num_val(get_val(row_dict_temp, 'MİN BÜTÇE (TL)', 'MİN BÜTÇE', 'MİN FİYAT', 'MIN FIYAT'))
                        max_fiyat = clean_num_val(get_val(row_dict_temp, 'MAX BÜTÇE (TL)', 'MAX BÜTÇE', 'MAX FİYAT', 'MAX FIYAT', 'BÜTÇE'))
                        min_m2 = clean_num_val(get_val(row_dict_temp, 'MİN M2', 'MİN M²', 'MIN M2'))
                        max_m2 = clean_num_val(get_val(row_dict_temp, 'MAX M2', 'MAX M²', 'MAX M2'))
                        durum = get_val(row_dict_temp, 'DURUM') or 'Aktif'
                        notlar = get_val(row_dict_temp, 'ÖZEL NOTLAR', 'NOTLAR', 'NOT', 'AÇIKLAMA')

                        existing = CustomerDemand.query.filter_by(
                            ad_soyad=ad_soyad,
                            telefon=telefon
                        ).first()
                        
                        if existing:
                            if il and il != 'nan': existing.il = il
                            if ilce and ilce != 'nan': existing.ilce = ilce
                            if mahalle and mahalle != 'nan': existing.mahalle = mahalle
                            if min_fiyat > 0: existing.min_fiyat = min_fiyat
                            if max_fiyat > 0: existing.max_fiyat = max_fiyat
                            if min_m2 > 0: existing.min_m2 = min_m2
                            if max_m2 > 0: existing.max_m2 = max_m2
                            if durum and durum != 'nan': existing.durum = durum
                            if notlar and notlar != 'nan': existing.notlar = notlar
                        else:
                            new_c = CustomerDemand(
                                ad_soyad=ad_soyad, telefon=telefon if telefon != 'nan' else '', tip=tip if tip != 'nan' else 'Hepsi',
                                il=il if il != 'nan' else '', ilce=ilce if ilce != 'nan' else '', mahalle=mahalle if mahalle != 'nan' else '',
                                min_fiyat=min_fiyat if min_fiyat > 0 else None,
                                max_fiyat=max_fiyat if max_fiyat > 0 else None,
                                min_m2=min_m2 if min_m2 > 0 else None,
                                max_m2=max_m2 if max_m2 > 0 else None,
                                durum=durum if durum != 'nan' else 'Aktif',
                                notlar=notlar if notlar != 'nan' else ''
                            )
                            db.session.add(new_c)
                            added_count += 1
                            
                    db.session.commit()
                    sync_customers_to_excel()
                    flash(f'{added_count} müşteri talebi sisteme aktarıldı ve Excel ile eşitlendi!', 'success')
                    return redirect(url_for('list_customers'))
                except Exception as e:
                    flash(f'Müşteri Excel aktarım hatası: {str(e)}', 'danger')
                    return redirect(request.url)
            
            try:
                # Daire / Arsa Excel için 0-byte kontrolü
                if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
                    flash('Girdiğiniz Excel dosyası boş (0 byte) veya geçersiz!', 'danger')
                    return redirect(request.url)

                try:
                    df = pd.read_excel(filepath, engine='openpyxl')
                except Exception:
                    df = pd.read_excel(filepath)
                # Sütun isimlerini olduğu gibi bırak (GeoParsel büyük/küçük harfe duyarlı olabilir)
                
                def to_upper_tr(s):
                    return str(s).replace('i', 'İ').replace('ı', 'I').upper().strip()

                def get_val(row_data, *possible_keys):
                    target_keys = [to_upper_tr(pk) for pk in possible_keys]
                    for k in row_data.keys():
                        if to_upper_tr(k) in target_keys:
                            return str(row_data[k]).strip()
                    return ''

                added_count = 0
                for index, row in df.iterrows():
                    row_dict_temp = row.to_dict()
                    il = get_val(row_dict_temp, 'İL', 'IL')
                    if il == 'nan' or not il: continue 
                    
                    ilce = get_val(row_dict_temp, 'İLÇE', 'ILCE')
                    mahalle = get_val(row_dict_temp, 'MAHALLE')
                    ada = get_val(row_dict_temp, 'ADA')
                    parsel = get_val(row_dict_temp, 'PARSEL')
                    fiyat = get_val(row_dict_temp, 'FİYAT', 'SATIŞ FİYATI')
                    durum = get_val(row_dict_temp, 'DURUM')
                    
                    kat = get_val(row_dict_temp, 'KAT', 'BULUNDUĞU KAT')
                    oda_sayisi = get_val(row_dict_temp, 'ODA SAYISI', 'ODA')
                    brut_m2 = get_val(row_dict_temp, 'BRÜT M2', 'BRUT M2', 'BRÜT', 'ALAN')
                    net_m2 = get_val(row_dict_temp, 'NET M2', 'NET')
                    bina_yasi = get_val(row_dict_temp, 'BİNA YAŞI', 'BINA YASI', 'YAŞ')
                    
                    ilan_linki = get_val(row_dict_temp, 'SAHİBİNDEN LİNKİ', 'İLAN LİNKİ', 'İLAN LİNK')
                    e_imar_linki = get_val(row_dict_temp, 'E-İMAR LİNKİ', 'E İMAR LİNKİ', 'İMAR LİNKİ', 'İMAR LİNK')
                    tkgm_linki = get_val(row_dict_temp, 'TKGM LİNKİ', 'TKGM LİNK')
                    
                    gorunurluk = get_val(row_dict_temp, 'GÖRÜNÜRLÜK', 'GORUNURLUK')
                    is_active_val = True
                    if gorunurluk:
                        is_active_val = str(gorunurluk).strip().lower() not in ['görünmez', 'gorunmez', 'false', '0']
                    
                    if durum == 'nan': durum = ''
                    if fiyat == 'nan': fiyat = ''
                    if kat == 'nan': kat = ''
                    if oda_sayisi == 'nan': oda_sayisi = ''
                    if brut_m2 == 'nan': brut_m2 = ''
                    if net_m2 == 'nan': net_m2 = ''
                    if bina_yasi == 'nan': bina_yasi = ''
                    if ilan_linki == 'nan': ilan_linki = ''
                    if e_imar_linki == 'nan': e_imar_linki = ''
                    if tkgm_linki == 'nan': tkgm_linki = ''
                    
                    # Tüm satırı JSON olarak sakla ki orijinal format/sütunlar kaybolmasın
                    raw_dict = row.to_dict()
                    import math
                    # Clean NaN floats and Timestamps before json serialization
                    clean_dict = {}
                    for k, v in raw_dict.items():
                        if isinstance(v, float) and math.isnan(v):
                            clean_dict[k] = ''
                        elif str(type(v)) == "<class 'pandas._libs.tslibs.timestamps.Timestamp'>" or 'Timestamp' in str(type(v)):
                            clean_dict[k] = v.strftime('%Y-%m-%d %H:%M:%S')
                        elif str(type(v)) == "<class 'datetime.datetime'>":
                            clean_dict[k] = v.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            clean_dict[k] = v
                            
                    extra_data_json = json.dumps(clean_dict, ensure_ascii=False)
                    
                    clean_il = il if il != 'nan' else ''
                    clean_ilce = ilce if ilce != 'nan' else ''
                    clean_mahalle = mahalle if mahalle != 'nan' else ''
                    clean_ada = ada if ada != 'nan' else ''
                    clean_parsel = parsel if parsel != 'nan' else ''
                    clean_fiyat = fiyat if fiyat != 'nan' else ''
                    clean_durum = durum if durum != 'nan' else ''
                    
                    # Veritabanında bu kayıt var mı kontrol et (Ada ve Parsel eşleşmesine göre)
                    existing = Portfolio.query.filter_by(
                        tip=secilen_tip,
                        il=clean_il,
                        ilce=clean_ilce,
                        mahalle=clean_mahalle,
                        ada=clean_ada,
                        parsel=clean_parsel
                    ).first()
                    
                    if existing:
                        # Var olan kaydı Excel'deki güncel bilgilerle güncelle!
                        if clean_fiyat: existing.fiyat = clean_fiyat
                        if clean_durum: existing.durum = clean_durum
                        if kat: existing.kat = kat
                        if oda_sayisi: existing.oda_sayisi = oda_sayisi
                        if brut_m2: existing.brut_m2 = brut_m2
                        if net_m2: existing.net_m2 = net_m2
                        if bina_yasi: existing.bina_yasi = bina_yasi
                        if ilan_linki: existing.ilan_linki = ilan_linki
                        if e_imar_linki: existing.e_imar_linki = e_imar_linki
                        if tkgm_linki: existing.tkgm_linki = tkgm_linki
                        if gorunurluk: existing.is_active = is_active_val
                        
                        existing_extra = {}
                        if existing.extra_data:
                            try: existing_extra = json.loads(existing.extra_data)
                            except: pass
                        existing_extra.update(clean_dict)
                        existing.extra_data = json.dumps(existing_extra, ensure_ascii=False)
                    else:
                        new_port = Portfolio(
                            tip=secilen_tip,
                            il=clean_il,
                            ilce=clean_ilce,
                            mahalle=clean_mahalle,
                            ada=clean_ada,
                            parsel=clean_parsel,
                            fiyat=clean_fiyat,
                            durum=clean_durum,
                            kat=kat,
                            oda_sayisi=oda_sayisi,
                            brut_m2=brut_m2,
                            net_m2=net_m2,
                            bina_yasi=bina_yasi,
                            ilan_linki=ilan_linki,
                            e_imar_linki=e_imar_linki,
                            tkgm_linki=tkgm_linki,
                            is_active=is_active_val,
                            extra_data=extra_data_json
                        )
                        db.session.add(new_port)
                        added_count += 1
                
                db.session.commit()
                sync_to_excel()
                flash(f'Başarılı! {added_count} adet portföy veritabanına eklendi.', 'success')
                return redirect(url_for('dashboard'))
                
            except Exception as e:
                flash(f'Hata oluştu: {str(e)}', 'error')
                return redirect(request.url)
                
    return render_template('upload.html')

@app.route('/portfolio/<int:id>', methods=['GET'])
def detail(id):
    portfolio = Portfolio.query.get_or_404(id)
    return render_template('detail.html', portfolio=portfolio)

@app.route('/portfolio/<int:id>/update', methods=['POST'])
def update_portfolio(id):
    portfolio = Portfolio.query.get_or_404(id)
    
    eski_fiyat = portfolio.fiyat
    yeni_fiyat = request.form.get('fiyat', portfolio.fiyat)
    if eski_fiyat and yeni_fiyat and str(eski_fiyat).strip() != str(yeni_fiyat).strip():
        ph = PriceHistory(
            portfolio_id=portfolio.id,
            eski_fiyat=str(eski_fiyat).strip(),
            yeni_fiyat=str(yeni_fiyat).strip()
        )
        db.session.add(ph)

    portfolio.tip = request.form.get('tip', portfolio.tip)
    portfolio.il = request.form.get('il', portfolio.il)
    portfolio.ilce = request.form.get('ilce', portfolio.ilce)
    portfolio.mahalle = request.form.get('mahalle', portfolio.mahalle)
    portfolio.ada = request.form.get('ada', portfolio.ada)
    portfolio.parsel = request.form.get('parsel', portfolio.parsel)
    portfolio.fiyat = yeni_fiyat
    portfolio.durum = request.form.get('durum', portfolio.durum)
    portfolio.danisman = request.form.get('danisman', portfolio.danisman)
    portfolio.musteri_adi = request.form.get('musteri_adi', portfolio.musteri_adi)
    portfolio.musteri_no = request.form.get('musteri_no', portfolio.musteri_no)
    
    # Checkbox logic
    portfolio.is_active = 'is_active' in request.form
    
    if portfolio.tip == 'Daire':
        portfolio.kat = request.form.get('kat', portfolio.kat)
        portfolio.oda_sayisi = request.form.get('oda_sayisi', portfolio.oda_sayisi)
        portfolio.brut_m2 = request.form.get('brut_m2', portfolio.brut_m2)
        portfolio.net_m2 = request.form.get('net_m2', portfolio.net_m2)
        portfolio.bina_yasi = request.form.get('bina_yasi', portfolio.bina_yasi)
    elif portfolio.tip == 'Arsa':
        alan = request.form.get('alan')
        kac_katli = request.form.get('kac_katli')
        if alan is not None: update_dict(row_dict, alan, 'ALAN', 'Alan')
        if kac_katli is not None: update_dict(row_dict, kac_katli, 'Kaç Katlı', 'KAÇ KATLI')
        
    portfolio.ilan_linki = request.form.get('ilan_linki', portfolio.ilan_linki)
    portfolio.e_imar_linki = request.form.get('e_imar_linki', portfolio.e_imar_linki)
    portfolio.tkgm_linki = request.form.get('tkgm_linki', portfolio.tkgm_linki)
    
    # Extra data JSON verisini de güncelle
    row_dict = {}
    if portfolio.extra_data:
        try: row_dict = json.loads(portfolio.extra_data)
        except: pass
        
    def to_upper_tr(s):
        return str(s).replace('i', 'İ').replace('ı', 'I').upper().strip()

    def update_dict(d, val, *possible_keys):
        if val is None or str(val).strip() == '': return
        target_keys = [to_upper_tr(pk) for pk in possible_keys]
        for k in d.keys():
            if to_upper_tr(k) in target_keys:
                d[k] = val
                return
        d[possible_keys[0]] = val

    update_dict(row_dict, portfolio.tip, 'TİP')
    update_dict(row_dict, portfolio.il, 'İL')
    update_dict(row_dict, portfolio.ilce, 'İLÇE')
    update_dict(row_dict, portfolio.mahalle, 'MAHALLE')
    update_dict(row_dict, portfolio.ada, 'ADA')
    update_dict(row_dict, portfolio.parsel, 'PARSEL')
    update_dict(row_dict, portfolio.fiyat, 'FİYAT', 'SATIŞ FİYATI')
    update_dict(row_dict, portfolio.durum, 'DURUM')
    update_dict(row_dict, portfolio.danisman, 'Danışman', 'DANIŞMAN')
    update_dict(row_dict, portfolio.musteri_adi, 'Müşteri Ad - Soyad', 'MÜŞTERİ AD - SOYAD', 'Mal Sahibi')
    update_dict(row_dict, portfolio.musteri_no, 'Müşteri no', 'MÜŞTERİ NO', 'Mal Sahibi Telefon')
    update_dict(row_dict, portfolio.kat, 'KAT', 'BULUNDUĞU KAT')
    update_dict(row_dict, portfolio.oda_sayisi, 'ODA SAYISI', 'ODA')
    update_dict(row_dict, portfolio.brut_m2, 'BRÜT M2', 'BRUT M2', 'BRÜT')
    update_dict(row_dict, portfolio.net_m2, 'NET M2', 'NET')
    update_dict(row_dict, portfolio.bina_yasi, 'BİNA YAŞI', 'YAŞ')
    update_dict(row_dict, portfolio.ilan_linki, 'SAHİBİNDEN LİNKİ', 'İLAN LİNKİ', 'İLAN LİNK')
    update_dict(row_dict, portfolio.e_imar_linki, 'E-İMAR LİNKİ', 'E İMAR LİNKİ', 'İMAR LİNKİ', 'İMAR LİNK')
    update_dict(row_dict, portfolio.tkgm_linki, 'TKGM LİNKİ', 'TKGM LİNK')

    # Form üzerindeki tüm dinamik Excel sütun güncellemelerini kaydet
    for form_key, form_val in request.form.items():
        if form_key.startswith('extra_field_'):
            real_col_name = form_key[12:]
            row_dict[real_col_name] = form_val.strip()

    portfolio.extra_data = json.dumps(row_dict, ensure_ascii=False)
    
    db.session.commit()
    sync_to_excel()
    flash('Portföy detayları güncellendi!', 'success')
    return redirect(url_for('detail', id=portfolio.id))

@app.route('/portfolio/<int:id>/add_note', methods=['POST'])
def add_note(id):
    portfolio = Portfolio.query.get_or_404(id)
    note_content = request.form.get('content')
    if note_content:
        new_note = Note(portfolio_id=portfolio.id, content=note_content)
        db.session.add(new_note)
        db.session.commit()
        flash('Not eklendi!', 'success')
    return redirect(url_for('detail', id=portfolio.id))

@app.route('/api/toggle_status/<int:id>', methods=['POST'])
def toggle_status(id):
    portfolio = Portfolio.query.get_or_404(id)
    data = request.get_json()
    is_active = data.get('is_active', True)
    
    portfolio.is_active = is_active
    gorunurluk_str = "Görünür" if is_active else "Görünmez"
    def update_extra_gorunurluk(extra_dict, val_str):
        def c_tr(s):
            return str(s).upper().replace('İ', 'I').replace('Ü', 'U').replace('Ö', 'O').replace('Ğ', 'G').replace('Ş', 'S').replace('Ç', 'C').strip()
        for k in list(extra_dict.keys()):
            if c_tr(k) == 'GORUNURLUK':
                extra_dict[k] = val_str
        extra_dict['GÖRÜNÜRLÜK'] = val_str

    if portfolio.extra_data:
        try:
            extra = json.loads(portfolio.extra_data)
            update_extra_gorunurluk(extra, gorunurluk_str)
            portfolio.extra_data = json.dumps(extra, ensure_ascii=False)
        except:
            pass

    db.session.commit()
    sync_to_excel()
    
    return jsonify({'success': True, 'is_active': portfolio.is_active})

@app.route('/api/mass_toggle_status', methods=['POST'])
def mass_toggle_status():
    if not session.get('activated'):
        return jsonify({'success': False, 'error': 'Yetkisiz erişim'}), 401
    
    data = request.get_json()
    ids = data.get('ids', [])
    is_active = data.get('is_active', True)
    
    if not ids:
        return jsonify({'success': False, 'error': 'ID listesi boş'})
        
    Portfolio.query.filter(Portfolio.id.in_(ids)).update({Portfolio.is_active: is_active}, synchronize_session=False)
    gorunurluk_str = "Görünür" if is_active else "Görünmez"
    for p in Portfolio.query.filter(Portfolio.id.in_(ids)).all():
        if p.extra_data:
            try:
                extra = json.loads(p.extra_data)
                update_extra_gorunurluk(extra, gorunurluk_str)
                p.extra_data = json.dumps(extra, ensure_ascii=False)
            except:
                pass

    db.session.commit()
    sync_to_excel()
    return jsonify({'success': True})

@app.route('/api/mass_delete', methods=['POST'])
def mass_delete():
    if not session.get('activated'):
        return jsonify({'success': False, 'error': 'Yetkisiz erişim'}), 401
        
    data = request.get_json()
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'success': False, 'error': 'ID listesi boş'})
        
    Portfolio.query.filter(Portfolio.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()
    sync_to_excel()
    return jsonify({'success': True})

@app.route('/api/delete_portfolio/<int:id>', methods=['DELETE'])
def delete_portfolio(id):
    portfolio = Portfolio.query.get_or_404(id)
    db.session.delete(portfolio)
    db.session.commit()
    sync_to_excel()
    return jsonify({'success': True})

def get_detected_custom_headers():
    custom_headers = set()
    standard_keys = {
        'TİP', 'TIP', 'İL', 'IL', 'İLÇE', 'ILCE', 'MAHALLE', 'ADA', 'PARSEL', 
        'FİYAT', 'FIYAT', 'SATIŞ FİYATI', 'SATIS FIYATI', 'DURUM', 
        'DANIŞMAN', 'DANISMAN', 'MÜŞTERİ AD - SOYAD', 'MUSTERI AD - SOYAD', 'MÜŞTERİ ADI', 'MAL SAHİBİ',
        'MÜŞTERİ NO', 'MUSTERI NO', 'MAL SAHİBİ TELEFON', 'GÖRÜNÜRLÜK', 'GORUNURLUK',
        'KAT', 'BULUNDUĞU KAT', 'ODA SAYISI', 'ODA', 'BRÜT M2', 'BRUT M2', 'BRÜT', 'NET M2', 'NET', 'BİNA YAŞI', 'YAŞ',
        'ALAN', 'ALAN (M2)', 'KAÇ KATLI', 'KAC KATLI', 'METREKARE FİYATI', 'METREKARE FIYATI', 'M2 FİYATI',
        'SAHİBİNDEN LİNKİ', 'İLAN LİNKİ', 'İLAN LİNK', 'E-İMAR LİNKİ', 'E İMAR LİNKİ', 'İMAR LİNKİ', 'TKGM LİNKİ', 'TKGM LİNK',
        'EKLENME TARİHİ', 'GÜNCELLEME TARİHİ'
    }
    
    current_settings = load_settings()
    for key in ['daire_excel', 'arsa_excel']:
        excel_path = current_settings.get(key)
        if excel_path and os.path.exists(excel_path):
            try:
                df = pd.read_excel(excel_path, nrows=0)
                for col in df.columns:
                    col_str = str(col).strip()
                    if not col_str or col_str.startswith('Unnamed:'):
                        continue
                    col_upper = col_str.upper().replace('İ','I').replace('Ü','U').replace('Ö','O').replace('Ğ','G').replace('Ş','S').replace('Ç','C')
                    if col_upper not in standard_keys:
                        custom_headers.add(col_str)
            except Exception:
                pass

    try:
        all_ports = Portfolio.query.all()
        for p in all_ports:
            if p.extra_data:
                try:
                    data = json.loads(p.extra_data)
                    for k in data.keys():
                        k_str = str(k).strip()
                        if not k_str or k_str.startswith('Unnamed:'):
                            continue
                        k_upper = k_str.upper().replace('İ','I').replace('Ü','U').replace('Ö','O').replace('Ğ','G').replace('Ş','S').replace('Ç','C')
                        if k_upper not in standard_keys:
                            custom_headers.add(k_str)
                except Exception:
                    pass
    except Exception:
        pass
        
    return sorted(list(custom_headers))

@app.route('/add', methods=['GET', 'POST'])
def add_portfolio():
    if not session.get('activated'):
        return redirect(url_for('activation'))
        
    if request.method == 'POST':
        tip = request.form.get('tip', 'Daire')
        
        current_settings = load_settings()
        if tip == 'Daire' and not current_settings.get('daire_excel'):
            flash("Daireler için hedef Excel ayarlanmamış! Lütfen önce Excel Yükle ekranından dosya yolu tanımlayın. Aksi halde verileriniz kaydedilemez.", 'danger')
            return redirect(url_for('add_portfolio'))
        elif tip == 'Arsa' and not current_settings.get('arsa_excel'):
            flash("Arsalar için hedef Excel ayarlanmamış! Lütfen önce Excel Yükle ekranından dosya yolu tanımlayın. Aksi halde verileriniz kaydedilemez.", 'danger')
            return redirect(url_for('add_portfolio'))
            
        il = request.form.get('il', '').strip()
        ilce = request.form.get('ilce', '').strip()
        mahalle = request.form.get('mahalle', '').strip()
        ada = request.form.get('ada', '').strip()
        parsel = request.form.get('parsel', '').strip()
        fiyat = request.form.get('fiyat', '').strip()
        durum = request.form.get('durum', '').strip()
        danisman = request.form.get('danisman', '').strip()
        musteri_adi = request.form.get('musteri_adi', '').strip()
        musteri_no = request.form.get('musteri_no', '').strip()
        
        kat = request.form.get('kat', '').strip() if tip == 'Daire' else ''
        oda_sayisi = request.form.get('oda_sayisi', '').strip() if tip == 'Daire' else ''
        brut_m2 = request.form.get('brut_m2', '').strip() if tip == 'Daire' else ''
        net_m2 = request.form.get('net_m2', '').strip() if tip == 'Daire' else ''
        bina_yasi = request.form.get('bina_yasi', '').strip() if tip == 'Daire' else ''
        alan = request.form.get('alan', '').strip() if tip == 'Arsa' else ''
        kac_katli = request.form.get('kac_katli', '').strip() if tip == 'Arsa' else ''
        
        ilan_linki = request.form.get('ilan_linki', '').strip()
        e_imar_linki = request.form.get('e_imar_linki', '').strip()
        tkgm_linki = request.form.get('tkgm_linki', '').strip()
        
        row_dict_add = {
            'TİP': tip, 'İL': il, 'İLÇE': ilce, 'MAHALLE': mahalle, 'ADA': ada, 'PARSEL': parsel,
            'FİYAT': fiyat, 'SATIŞ FİYATI': fiyat, 'DURUM': durum,
            'Danışman': danisman, 'Müşteri Ad - Soyad': musteri_adi, 'Müşteri no': musteri_no,
            'GÖRÜNÜRLÜK': 'Görünür'
        }
        if tip == 'Daire':
            row_dict_add.update({
                'KAT': kat, 'ODA SAYISI': oda_sayisi, 'BRÜT M2': brut_m2, 'NET M2': net_m2, 'BİNA YAŞI': bina_yasi
            })
        elif tip == 'Arsa':
            row_dict_add.update({
                'ALAN': alan, 'Kaç Katlı': kac_katli
            })
        row_dict_add.update({
            'SAHİBİNDEN LİNKİ': ilan_linki, 'E İMAR LİNKİ': e_imar_linki, 'TKGM LİNKİ': tkgm_linki
        })
        
        custom_headers = request.form.getlist('custom_header[]')
        custom_values = request.form.getlist('custom_value[]')
        for h, v in zip(custom_headers, custom_values):
            if h and h.strip():
                row_dict_add[h.strip()] = v.strip() if v else ''
        
        new_port = Portfolio(
            tip=tip, il=il, ilce=ilce, mahalle=mahalle, ada=ada, parsel=parsel, 
            fiyat=fiyat, durum=durum, danisman=danisman, musteri_adi=musteri_adi, musteri_no=musteri_no,
            kat=kat, oda_sayisi=oda_sayisi, brut_m2=brut_m2, 
            net_m2=net_m2, bina_yasi=bina_yasi, ilan_linki=ilan_linki, 
            e_imar_linki=e_imar_linki, tkgm_linki=tkgm_linki,
            extra_data=json.dumps(row_dict_add, ensure_ascii=False)
        )
        db.session.add(new_port)
        db.session.commit()
        sync_to_excel()
        
        flash('Portföy başarıyla eklendi!', 'success')
        return redirect(url_for('dashboard'))
        
    from turkey_data import TURKEY_CITIES, get_all_ils
    detected_headers = get_detected_custom_headers()
    return render_template('add.html', all_ils=get_all_ils(), turkey_cities_json=json.dumps(TURKEY_CITIES, ensure_ascii=False), detected_custom_headers=detected_headers)

@app.route('/force_sync', methods=['POST'])
def force_sync():
    if not session.get('activated'):
        return redirect(url_for('activation'))
    
    # Veritabanındaki güncel durumu (Görünür / Görünmez tüm seçimler dahil) anında Excel dosyalarına yaz
    sync_to_excel()
    
    flash('Excel dosyaları veritabanındaki görünürlük ve tüm güncel verilerle başarıyla güncellendi!', 'success')
    return redirect(url_for('dashboard'))

import io
from flask import send_file

@app.route('/export')
def export_excel():
    if not session.get('activated'):
        return redirect(url_for('activation'))
        
    tip_filter = request.args.get('tip', 'all')
    
    # 1. Anlık olarak tüm verileri Excel'e senkronize et ki en güncel hal indirilsin
    sync_to_excel()
    
    current_settings = load_settings()
    daire_excel = current_settings.get('daire_excel')
    arsa_excel = current_settings.get('arsa_excel')
    
    def get_portfolios_dataframe(tip_name):
        ports = Portfolio.query.filter_by(tip=tip_name).all()
        rows = []
        for p in ports:
            row_dict = {}
            if p.extra_data:
                try:
                    row_dict = json.loads(p.extra_data)
                except:
                    pass
            gorunurluk_yazi = "Görünür" if p.is_active else "Görünmez"
            row_dict['TİP'] = p.tip
            row_dict['İL'] = p.il
            row_dict['İLÇE'] = p.ilce
            row_dict['MAHALLE'] = p.mahalle
            row_dict['ADA'] = p.ada
            row_dict['PARSEL'] = p.parsel
            row_dict['DURUM'] = p.durum
            row_dict['Danışman'] = p.danisman or row_dict.get('Danışman') or row_dict.get('DANIŞMAN') or ''
            row_dict['Müşteri Ad - Soyad'] = p.musteri_adi or row_dict.get('Müşteri Ad - Soyad') or row_dict.get('Mal Sahibi') or ''
            row_dict['Müşteri no'] = p.musteri_no or row_dict.get('Müşteri no') or row_dict.get('Mal Sahibi Telefon') or ''
            row_dict['GÖRÜNÜRLÜK'] = gorunurluk_yazi
            if p.fiyat:
                if tip_name == 'Arsa':
                    row_dict['SATIŞ FİYATI'] = p.fiyat
                else:
                    row_dict['FİYAT'] = p.fiyat
            rows.append(row_dict)
        return pd.DataFrame(rows)

    if tip_filter == 'Arsa':
        if arsa_excel and os.path.exists(arsa_excel):
            return send_file(arsa_excel, as_attachment=True, download_name=f"GeoArsa_Portfoyler_{datetime.now().strftime('%Y%m%d')}.xlsx")
        else:
            df = get_portfolios_dataframe('Arsa')
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Arsalar')
            output.seek(0)
            return send_file(output, as_attachment=True, download_name=f"GeoArsa_Portfoyler_{datetime.now().strftime('%Y%m%d')}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    elif tip_filter == 'Daire':
        if daire_excel and os.path.exists(daire_excel):
            return send_file(daire_excel, as_attachment=True, download_name=f"GeoDaire_Portfoyler_{datetime.now().strftime('%Y%m%d')}.xlsx")
        else:
            df = get_portfolios_dataframe('Daire')
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Daireler')
            output.seek(0)
            return send_file(output, as_attachment=True, download_name=f"GeoDaire_Portfoyler_{datetime.now().strftime('%Y%m%d')}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    else:
        df_arsa = get_portfolios_dataframe('Arsa')
        df_daire = get_portfolios_dataframe('Daire')
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            if not df_arsa.empty:
                df_arsa.to_excel(writer, index=False, sheet_name='Arsalar')
            if not df_daire.empty:
                df_daire.to_excel(writer, index=False, sheet_name='Daireler')
        output.seek(0)
        return send_file(output, as_attachment=True, download_name=f"GeoMerkez_Tum_Portfoyler_{datetime.now().strftime('%Y%m%d')}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# ----------------------------------------------------
# Müşteri Talepleri ve Akıllı Eşleştirme Motoru
# ----------------------------------------------------
def clean_num_val(x):
    if not x: return 0.0
    s = str(x).replace('TL','').replace('₺','').replace('m²','').replace('M2','').replace(' ','').strip()
    if ',' in s and '.' in s: s = s.replace('.','').replace(',', '.')
    elif ',' in s: s = s.replace(',', '.')
    elif s.count('.') > 1: s = s.replace('.','')
    try: return float(s)
    except: return 0.0

@app.route('/customers')
def list_customers():
    if not session.get('activated'):
        return redirect(url_for('activation'))
    
    status_filter = request.args.get('status', 'Aktif')
    search_q = request.args.get('search', '').strip()
    
    query = CustomerDemand.query
    if status_filter != 'Hepsi':
        query = query.filter_by(durum=status_filter)
    if search_q:
        search_like = f"%{search_q}%"
        query = query.filter(
            (CustomerDemand.ad_soyad.like(search_like)) | 
            (CustomerDemand.telefon.like(search_like)) |
            (CustomerDemand.ilce.like(search_like)) |
            (CustomerDemand.notlar.like(search_like))
        )
        
    customers = query.order_by(CustomerDemand.created_at.desc()).all()
    return render_template('customers.html', customers=customers, current_status=status_filter, search=search_q)

@app.route('/customers/add', methods=['GET', 'POST'])
def add_customer():
    if not session.get('activated'):
        return redirect(url_for('activation'))
        
    if request.method == 'POST':
        ad_soyad = request.form.get('ad_soyad', '').strip()
        telefon = request.form.get('telefon', '').strip()
        tip = request.form.get('tip', 'Hepsi')
        il_check_list = request.form.getlist('il_check[]')
        ilce_check_list = request.form.getlist('ilce_check[]')
        
        if il_check_list:
            il = ", ".join([x.strip() for x in il_check_list if x.strip()])
        else:
            il = request.form.get('il', '').strip()

        if ilce_check_list:
            ilce = ", ".join([x.strip() for x in ilce_check_list if x.strip()])
        else:
            ilce = request.form.get('ilce', '').strip()

        mahalle = request.form.get('mahalle', '').strip()
        
        min_fiyat_raw = request.form.get('min_fiyat', '')
        max_fiyat_raw = request.form.get('max_fiyat', '')
        min_m2_raw = request.form.get('min_m2', '')
        max_m2_raw = request.form.get('max_m2', '')
        
        min_fiyat = clean_num_val(min_fiyat_raw) if min_fiyat_raw else None
        max_fiyat = clean_num_val(max_fiyat_raw) if max_fiyat_raw else None
        min_m2 = clean_num_val(min_m2_raw) if min_m2_raw else None
        max_m2 = clean_num_val(max_m2_raw) if max_m2_raw else None
        
        notlar = request.form.get('notlar', '').strip()
        durum = request.form.get('durum', 'Aktif')
        
        new_cust = CustomerDemand(
            ad_soyad=ad_soyad, telefon=telefon, tip=tip,
            il=il, ilce=ilce, mahalle=mahalle,
            min_fiyat=min_fiyat, max_fiyat=max_fiyat,
            min_m2=min_m2, max_m2=max_m2,
            durum=durum, notlar=notlar
        )
        db.session.add(new_cust)
        db.session.commit()
        sync_customers_to_excel()
        flash('Müşteri talebi başarıyla kaydedildi!', 'success')
        return redirect(url_for('list_customers'))
        
    from turkey_data import TURKEY_CITIES
    return render_template('customer_add.html', customer=None, turkey_cities=TURKEY_CITIES)

@app.route('/customers/<int:id>/edit', methods=['GET', 'POST'])
def edit_customer(id):
    if not session.get('activated'):
        return redirect(url_for('activation'))
        
    customer = CustomerDemand.query.get_or_404(id)
    if request.method == 'POST':
        customer.ad_soyad = request.form.get('ad_soyad', customer.ad_soyad).strip()
        customer.telefon = request.form.get('telefon', customer.telefon).strip()
        customer.tip = request.form.get('tip', customer.tip)
        
        il_check_list = request.form.getlist('il_check[]')
        ilce_check_list = request.form.getlist('ilce_check[]')
        
        if il_check_list:
            customer.il = ", ".join([x.strip() for x in il_check_list if x.strip()])
        else:
            customer.il = request.form.get('il', customer.il).strip()

        if ilce_check_list:
            customer.ilce = ", ".join([x.strip() for x in ilce_check_list if x.strip()])
        else:
            customer.ilce = request.form.get('ilce', customer.ilce).strip()

        customer.mahalle = request.form.get('mahalle', customer.mahalle).strip()
        
        min_fiyat_raw = request.form.get('min_fiyat', '')
        max_fiyat_raw = request.form.get('max_fiyat', '')
        min_m2_raw = request.form.get('min_m2', '')
        max_m2_raw = request.form.get('max_m2', '')
        
        customer.min_fiyat = clean_num_val(min_fiyat_raw) if min_fiyat_raw else None
        customer.max_fiyat = clean_num_val(max_fiyat_raw) if max_fiyat_raw else None
        customer.min_m2 = clean_num_val(min_m2_raw) if min_m2_raw else None
        customer.max_m2 = clean_num_val(max_m2_raw) if max_m2_raw else None
        
        customer.notlar = request.form.get('notlar', customer.notlar).strip()
        customer.durum = request.form.get('durum', customer.durum)
        
        db.session.commit()
        sync_customers_to_excel()
        flash('Müşteri talebi güncellendi!', 'success')
        return redirect(url_for('list_customers'))
        
    from turkey_data import TURKEY_CITIES
    return render_template('customer_add.html', customer=customer, turkey_cities=TURKEY_CITIES)

@app.route('/customers/<int:id>/delete', methods=['POST'])
def delete_customer(id):
    if not session.get('activated'):
        return redirect(url_for('activation'))
        
    customer = CustomerDemand.query.get_or_404(id)
    db.session.delete(customer)
    db.session.commit()
    sync_customers_to_excel()
    flash('Müşteri kaydı silindi.', 'success')
    return redirect(url_for('list_customers'))

@app.route('/customers/<int:id>/match')
def match_customer(id):
    if not session.get('activated'):
        return redirect(url_for('activation'))
        
    customer = CustomerDemand.query.get_or_404(id)
    all_portfolios = Portfolio.query.filter_by(is_active=True).all()
    
    matched_results = []
    
    def normalize_str(s):
        if not s: return ''
        st = str(s).strip().upper()
        return st.replace('İ', 'I').replace('İ', 'I').replace('ı', 'I').replace('i', 'I')\
                 .replace('Ü', 'U').replace('ü', 'U')\
                 .replace('Ö', 'O').replace('ö', 'O')\
                 .replace('Ğ', 'G').replace('ğ', 'G')\
                 .replace('Ş', 'S').replace('ş', 'S')\
                 .replace('Ç', 'C').replace('ç', 'C')

    c_tip = normalize_str(customer.tip)
    c_il_str = customer.il or ''
    c_ilce_str = customer.ilce or ''
    
    c_il_list = [normalize_str(x) for x in c_il_str.split(',') if x.strip()]
    c_ilce_list = [normalize_str(x) for x in c_ilce_str.split(',') if x.strip()]
    c_mahalle = normalize_str(customer.mahalle)

    for p in all_portfolios:
        score = 0
        reasons = []
        
        # 1. Tip Kontrolü (20 puan)
        p_tip = normalize_str(p.tip)
        if not c_tip or c_tip in ['HEPSI', 'HEPSİ', 'TÜMÜ', 'TUMU', 'FARK ETMEZ'] or 'HEPS' in c_tip:
            score += 20
            reasons.append(f"Tip ({p.tip})")
        elif p_tip == c_tip:
            score += 20
            reasons.append(f"Tip Uyumlu ({p.tip})")
        else:
            continue

        # 2. Şehir / İl Kontrolü (20 puan)
        p_il = normalize_str(p.il)
        has_il_filter = bool(c_il_list and not any(k in c for c in c_il_list for k in ['TÜM', 'TUM', 'TÜRKİYE', 'TURKIYE']))
        if not has_il_filter:
            score += 20
        elif any(p_il == c or c in p_il or p_il in c for c in c_il_list):
            score += 20
            reasons.append(f"İl Uyumlu ({p.il})")
        else:
            score += 0

        # 3. İlçe / Mahalle Kontrolü (25 puan)
        p_ilce = normalize_str(p.ilce)
        p_mahalle = normalize_str(p.mahalle)
        
        has_ilce_filter = bool(c_ilce_list and not any(k in c for c in c_ilce_list for k in ['TÜM', 'TUM']))
        has_mahalle_filter = bool(c_mahalle and 'TÜM' not in c_mahalle and 'TUM' not in c_mahalle)

        if not has_ilce_filter:
            score += 25
            if has_mahalle_filter and (c_mahalle in p_mahalle or p_mahalle in c_mahalle):
                reasons.append(f"Mahalle Uyumlu ({p.mahalle})")
        else:
            ilce_matched = any(
                (p_ilce == c) or (c in p_mahalle) or (p_mahalle in c) or (p_ilce in c)
                for c in c_ilce_list
            )
            mahalle_matched = has_mahalle_filter and ((c_mahalle in p_mahalle) or (p_mahalle in c_mahalle) or (c_mahalle in p_ilce))

            if ilce_matched:
                score += 25
                reasons.append(f"İlçe/Bölge Uyumlu ({p.ilce}{' - ' + p.mahalle if p.mahalle else ''})")
                if mahalle_matched:
                    reasons.append(f"Mahalle Uyumlu ({p.mahalle})")
            elif mahalle_matched:
                score += 20
                reasons.append(f"Mahalle Uyumlu ({p.mahalle})")
            else:
                score -= 15

        # 4. Fiyat Bütçesi Kontrolü (20 puan)
        p_fiyat = clean_num_val(p.fiyat)
        if p_fiyat > 0:
            if customer.min_fiyat and customer.max_fiyat:
                if customer.min_fiyat <= p_fiyat <= customer.max_fiyat:
                    score += 20
                    reasons.append("Bütçeye Tam Uyuyor")
                elif p_fiyat <= customer.max_fiyat * 1.15:
                    score += 12
                    reasons.append("Bütçeye Yakın (%15 Esneme)")
            elif customer.max_fiyat:
                if p_fiyat <= customer.max_fiyat:
                    score += 20
                    reasons.append("Max Bütçe Altında")
                elif p_fiyat <= customer.max_fiyat * 1.15:
                    score += 12
                    reasons.append("Bütçeye Yakın")
            elif customer.min_fiyat:
                if p_fiyat >= customer.min_fiyat:
                    score += 20
            else:
                score += 20
        else:
            score += 15

        # 5. Metrekare Kontrolü (15 puan)
        p_m2 = clean_num_val(p.display_m2)
        if p_m2 > 0:
            if customer.min_m2 and customer.max_m2:
                if customer.min_m2 <= p_m2 <= customer.max_m2:
                    score += 15
                    reasons.append("m² İstenen Aralıkta")
                elif p_m2 >= customer.min_m2 * 0.85:
                    score += 8
            elif customer.min_m2:
                if p_m2 >= customer.min_m2:
                    score += 15
                    reasons.append("Min m² Sağlandı")
            elif customer.max_m2:
                if p_m2 <= customer.max_m2:
                    score += 15
            else:
                score += 15
        else:
            score += 10

        score = min(100, max(0, score))
        if score >= 45:
            matched_results.append({
                'portfolio': p,
                'score': score,
                'reasons': reasons
            })

    matched_results.sort(key=lambda x: x['score'], reverse=True)
    return render_template('customer_match.html', customer=customer, results=matched_results)

# ----------------------------------------------------
# 📄 1. PDF Portföy Sunum Kartı & Yer Gösterme Belgesi
# ----------------------------------------------------
@app.route('/portfolio/<int:id>/brochure')
def portfolio_brochure(id):
    if not session.get('activated'):
        return redirect(url_for('activation'))
    portfolio = Portfolio.query.get_or_404(id)
    return render_template('brochure.html', portfolio=portfolio)

@app.route('/portfolio/<int:id>/showing/create', methods=['GET', 'POST'])
def create_showing(id):
    if not session.get('activated'):
        return redirect(url_for('activation'))
    portfolio = Portfolio.query.get_or_404(id)
    
    if request.method == 'POST':
        musteri_adi = request.form.get('musteri_adi', '').strip()
        musteri_tc = request.form.get('musteri_tc', '').strip()
        musteri_telefon = request.form.get('musteri_telefon', '').strip()
        danisman = request.form.get('danisman', portfolio.danisman or '').strip()
        notlar = request.form.get('notlar', '').strip()
        
        showing = Showing(
            portfolio_id=portfolio.id,
            musteri_adi=musteri_adi,
            musteri_tc=musteri_tc,
            musteri_telefon=musteri_telefon,
            danisman=danisman,
            notlar=notlar
        )
        db.session.add(showing)
        db.session.commit()
        flash('Yer Gösterme Belgesi başarıyla oluşturuldu!', 'success')
        return redirect(url_for('print_showing', id=showing.id))
        
    customers = CustomerDemand.query.filter_by(durum='Aktif').all()
    return render_template('showing_form.html', portfolio=portfolio, customers=customers)

@app.route('/showing/<int:id>/print')
def print_showing(id):
    if not session.get('activated'):
        return redirect(url_for('activation'))
    showing = Showing.query.get_or_404(id)
    return render_template('showing_print.html', showing=showing)

# ----------------------------------------------------
# 💰 2. Tapu Harcı & Komisyon Hesaplayıcı
# ----------------------------------------------------
@app.route('/calculator')
def calculator():
    if not session.get('activated'):
        return redirect(url_for('activation'))
    return render_template('calculator.html')

# ----------------------------------------------------
# 📅 5. Müşteri Randevu & Takvim Modülü
# ----------------------------------------------------
@app.route('/appointments', methods=['GET', 'POST'])
def list_appointments():
    if not session.get('activated'):
        return redirect(url_for('activation'))
        
    if request.method == 'POST':
        baslik = request.form.get('baslik', '').strip()
        musteri_adi = request.form.get('musteri_adi', '').strip()
        telefon = request.form.get('telefon', '').strip()
        tarih_str = request.form.get('tarih', '')
        notlar = request.form.get('notlar', '').strip()
        
        if baslik and tarih_str:
            try:
                tarih_dt = datetime.strptime(tarih_str.replace('T', ' '), "%Y-%m-%d %H:%M")
            except:
                try:
                    tarih_dt = datetime.strptime(tarih_str, "%Y-%m-%d")
                except:
                    tarih_dt = datetime.utcnow()
                    
            app_obj = Appointment(
                baslik=baslik,
                musteri_adi=musteri_adi,
                telefon=telefon,
                tarih=tarih_dt,
                notlar=notlar
            )
            db.session.add(app_obj)
            db.session.commit()
            flash('Yeni randevu takvime eklendi!', 'success')
            return redirect(url_for('list_appointments'))
            
    appointments = Appointment.query.order_by(Appointment.tarih.asc()).all()
    customers = CustomerDemand.query.filter_by(durum='Aktif').all()
    return render_template('appointments.html', appointments=appointments, customers=customers)

@app.route('/appointments/<int:id>/delete', methods=['POST'])
def delete_appointment(id):
    if not session.get('activated'):
        return redirect(url_for('activation'))
    app_obj = Appointment.query.get_or_404(id)
    db.session.delete(app_obj)
    db.session.commit()
    flash('Randevu silindi.', 'success')
    return redirect(url_for('list_appointments'))

if __name__ == '__main__':
    import threading
    import webbrowser

    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:5000/")

    threading.Thread(target=open_browser).start()
    app.run(host='127.0.0.1', port=5000, debug=False)
