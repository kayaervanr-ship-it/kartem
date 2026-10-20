import streamlit as st
import pandas as pd
import io
from thefuzz import process, fuzz

st.set_page_config(page_title="KARTEM Mutabakat Asistanı", layout="wide")

# Sol Üst KARTEM, Sağ Alt B.T Tasarımı
st.markdown("""
    <style>
    .kartem-header {
        font-size: 28px;
        font-weight: bold;
        color: #1E88E5;
        letter-spacing: 2px;
        margin-bottom: 5px;
    }
    .footer-bt {
        position: fixed;
        bottom: 10px;
        right: 20px;
        font-size: 14px;
        font-weight: bold;
        color: #888888;
        opacity: 0.7;
        z-index: 1000;
    }
    </style>
    <div class="kartem-header">KARTEM</div>
    <div class="footer-bt">B.T</div>
""", unsafe_allow_html=True)

st.title("📊 Akıllı Fatura ve Banka Eşleştirme Otomasyonu")
st.markdown("Faturalarınızı ve banka ödemelerinizi yükleyin; sistem kurum adlarını esnek benzerlik oranıyla eşleştirsin.")

# BENZERLİK ORANI FİLTRELEME ÇUBUĞU (Varsayılan %65)
st.markdown("---")
benzerlik_orani = st.slider(
    "🎯 İsim Benzerlik Eşik Oranı (%):", 
    min_value=1, 
    max_value=100, 
    value=65, 
    step=1,
    help="Uygulama açılışında otomatik %65 ayarlanır. İhtiyacınıza göre oranı artırıp azaltabilirsiniz."
)
st.markdown("---")

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Fatura Listesi")
    fatura_file = st.file_uploader("Fatura Dosyası (Excel/CSV)", type=["xlsx", "xls", "csv"], key="fatura")

with col2:
    st.subheader("2. Banka Ödeme Listesi")
    banka_file = st.file_uploader("Banka Dosyası (Excel/CSV)", type=["xlsx", "xls", "csv"], key="banka")

def load_data(uploaded_file):
    if uploaded_file is not None:
        try:
            file_bytes = uploaded_file.getvalue()
            df = None

            for eng in ['xlrd', 'openpyxl', None]:
                try:
                    if eng:
                        df = pd.read_excel(io.BytesIO(file_bytes), engine=eng)
                    else:
                        df = pd.read_excel(io.BytesIO(file_bytes))
                    if df is not None and not df.empty:
                        break
                except Exception:
                    continue

            if df is None:
                for enc in ['utf-8', 'latin-1', 'cp1254', 'iso-8859-9']:
                    try:
                        df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc, sep=None, engine='python')
                        if df is not None and not df.empty:
                            break
                    except Exception:
                        continue

            if df is not None:
                df.columns = [str(c).strip() for c in df.columns]
                return df
            else:
                st.error(f"'{uploaded_file.name}' dosyası okunamadı.")
        except Exception as e:
            st.error(f"Dosya okuma hatası: {e}")
    return None

df_fatura = load_data(fatura_file)
df_banka = load_data(banka_file)

if df_fatura is not None and df_banka is not None:
    st.success("Dosyalar başarıyla yüklendi!")

    def find_kurum_col(df):
        engellenenler = ['tarih', 'date', 'zaman', 'saat', 'tutar', 'bedel', 'vergi', 'kdv', 'no', 'id', 'unnamed', 'toplam', 'matrah', 'fatura no']
        for col in df.columns:
            c_low = str(col).lower()
            if not any(eng in c_low for eng in engellenenler):
                if any(kw in c_low for kw in ['kurum', 'firma', 'unvan', 'üntaraf', 'müşteri', 'musteri', 'sirket', 'şirket', 'açıklama', 'aciklama', 'detay', 'ad', 'isim']):
                    return col
        for col in df.columns:
            c_low = str(col).lower()
            if not any(eng in c_low for eng in engellenenler):
                return col
        return df.columns[0]

    def find_col(df, keywords):
        for col in df.columns:
            c_low = str(col).lower()
            for kw in keywords:
                if kw in c_low and "unnamed" not in c_low:
                    return col
        valid = [c for c in df.columns if "unnamed" not in c.lower()]
        return valid[0] if valid else df.columns[0]

    auto_f_kurum = find_kurum_col(df_fatura)
    auto_b_kurum = find_kurum_col(df_banka)

    with st.expander("🔍 Otomatik Sütun Tespiti (Gerekirse Kurum Adı Sütununu Buradan Değiştirebilirsiniz)", expanded=False):
        c_s1, c_s2 = st.columns(2)
        with c_s1:
            f_kurum_col = st.selectbox("Fatura - Firma/Kurum Adı Sütunu:", df_fatura.columns, index=list(df_fatura.columns).index(auto_f_kurum) if auto_f_kurum in df_fatura.columns else 0)
        with c_s2:
            b_kurum_col = st.selectbox("Banka - Firma Adı/Açıklama Sütunu:", df_banka.columns, index=list(df_banka.columns).index(auto_b_kurum) if auto_b_kurum in df_banka.columns else 0)

    f_ara_col = find_col(df_fatura, ['ara toplam', 'aratoplam', 'matrah'])
    f_vergi_col = find_col(df_fatura, ['vergi', 'kdv'])
    b_tutar_col = find_col(df_banka, ['tutar', 'meblağ', 'meblag', 'ödeme', 'odeme', 'gelen'])

    if st.button("🚀 Mutabakatı Başlat"):

        def clean_val(val):
            if pd.isna(val): return 0.0
            if isinstance(val, (int, float)): return float(val)
            s = str(val).strip().replace('TL', '').replace('₺', '').replace(' ', '')
            if ',' in s and '.' in s:
                if s.find('.') < s.find(','): s = s.replace('.', '').replace(',', '.')
                else: s = s.replace(',', '')
            elif ',' in s: s = s.replace(',', '.')
            try: return float(s)
            except: return 0.0

        # HESAPLAMA MANTIĞI: (Ara Toplam * 1.00948) + Toplam Vergi
        ara = df_fatura[f_ara_col].apply(clean_val) if f_ara_col in df_fatura.columns else 0.0
        vergi = df_fatura[f_vergi_col].apply(clean_val) if f_vergi_col in df_fatura.columns else 0.0
        
        # Ara Toplam + Binde 9.48 Damga Vergisi + Toplam Vergi
        df_fatura['Final_Tutar'] = (ara * 1.00948) + vergi

        df_banka['Final_Tutar'] = df_banka[b_tutar_col].apply(clean_val)

        eslesenler = []
        islenen_banka_idx = set()
        islenen_fatura_idx = set()

        banka_kurumlar = df_banka[b_kurum_col].astype(str).tolist()

        # 1. KURAL: İsim Benzerliği ile Eşleştirme
        for f_idx, f_row in df_fatura.iterrows():
            f_kurum = str(f_row[f_kurum_col]).strip()
            f_tutar = round(f_row['Final_Tutar'], 2)

            if not f_kurum or f_kurum.lower() in ["nan", "none", ""]:
                continue

            match_result = process.extractOne(f_kurum, banka_kurumlar, scorer=fuzz.token_sort_ratio)
            
            if match_result and match_result[1] >= benzerlik_orani:
                b_kurum_adi = match_result[0]
                matching_bank_rows = df_banka[(df_banka[b_kurum_col].astype(str).str.strip() == b_kurum_adi) & (~df_banka.index.isin(islenen_banka_idx))]
                
                if not matching_bank_rows.empty:
                    b_idx = matching_bank_rows.index[0]
                    b_row = matching_bank_rows.iloc[0]
                    b_tutar = round(b_row['Final_Tutar'], 2)
                    
                    eslesenler.append({
                        "Ödeme Yapan Kurum Adı": f_kurum,
                        "Banka Kaydı / Açıklama": b_row[b_kurum_col],
                        "Hesaplanan Fatura Tutarı (TL)": f_tutar,
                        "Banka Tutarı (TL)": b_tutar,
                        "Eşleşme Yolu": f"Kurum Adı Benzerliği (%{match_result[1]})"
                    })
                    islenen_fatura_idx.add(f_idx)
                    islenen_banka_idx.add(b_idx)

        # 2. KURAL: Tutar Birebir Eşleşmesi (Ara Toplam + Damga Vergisi + Toplam Vergi = Ödeme)
        for f_idx, f_row in df_fatura.iterrows():
            if f_idx in islenen_fatura_idx:
                continue
            
            f_tutar = round(f_row['Final_Tutar'], 2)
            f_kurum = str(f_row[f_kurum_col]).strip()

            if f_tutar <= 0:
                continue

            matching_tutar_rows = df_banka[(df_banka['Final_Tutar'].round(2) == f_tutar) & (~df_banka.index.isin(islenen_banka_idx))]
            
            if not matching_tutar_rows.empty:
                b_idx = matching_tutar_rows.index[0]
                b_row = matching_tutar_rows.iloc[0]
                
                eslesenler.append({
                    "Ödeme Yapan Kurum Adı": f_kurum,
                    "Banka Kaydı / Açıklama": b_row[b_kurum_col],
                    "Hesaplanan Fatura Tutarı (TL)": f_tutar,
                    "Banka Tutarı (TL)": round(b_row['Final_Tutar'], 2),
                    "Eşleşme Yolu": "Tutar Eşleşmesi (Ara Toplam + Damga Vergisi + Vergi)"
                })
                islenen_fatura_idx.add(f_idx)
                islenen_banka_idx.add(b_idx)

        # Sekmeler
        df_odenmeyenler = df_fatura[~df_fatura.index.isin(islenen_fatura_idx)]
        df_eslesmeyen_banka = df_banka[~df_banka.index.isin(islenen_banka_idx)]

        st.markdown("---")
        tab1, tab2, tab3 = st.tabs(["✅ Eşleşenler (Ödeme Yapanlar)", "⚠️ Eşleşmeyen Banka Ödemeleri", "❌ Ödeme Yapmayanlar"])

        with tab1:
            st.subheader(f"Ödemesi Başarıyla Yapılan Kurumlar Listesi (Eşik: %{benzerlik_orani})")
            if eslesenler:
                st.dataframe(pd.DataFrame(eslesenler), use_container_width=True)
            else:
                st.info(f"%{benzerlik_orani} benzerlik oranına göre eşleşen kayıt bulunamadı.")

        with tab2:
            st.subheader("Banka Ödemesi Bulunan Ama Faturası Olmayanlar")
            if not df_eslesmeyen_banka.empty:
                st.dataframe(df_eslesmeyen_banka[[b_kurum_col, b_tutar_col]], use_container_width=True)
            else:
                st.info("Açıkta kalan banka ödemesi yok.")

        with tab3:
            st.subheader("Hiç Ödeme Yapılmamış Faturası Olan Kurumlar")
            if not df_odenmeyenler.empty:
                st.dataframe(df_odenmeyenler[[f_kurum_col, 'Final_Tutar']], use_container_width=True)
            else:
                st.info("Ödemesi yapılmayan fatura yok.")
else:
    st.info("Lütfen mutabakatı başlatmak için her iki dosyayı da yükleyin.")
