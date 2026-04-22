import streamlit as st
import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.formula.api import ols
from scipy import stats
from fpdf import FPDF
import io

# --- 1. SETUP PDF REPORTING ---
class PDFReport(FPDF):
    def header(self):
        self.set_font('Courier', 'B', 12)
        self.cell(0, 10, 'RBD Analysis Report', 0, 1, 'C')
        self.ln(5)
    def footer(self):
        self.set_y(-15)
        self.set_font('Courier', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

# --- 2. HELPER FUNCTIONS ---
def run_anova(df, val_col):
    """Calculates ANOVA stats for a specific dataframe"""
    model = ols(f'{val_col} ~ C(Treatment) + C(Replication)', data=df).fit()
    anova = sm.stats.anova_lm(model, typ=1)
    
    mse = anova.loc['Residual', 'mean_sq']
    df_err = anova.loc['Residual', 'df']
    grand_mean = df[val_col].mean()
    sem = np.sqrt(mse / df['Replication'].nunique())
    cv = (np.sqrt(mse) / grand_mean) * 100
    t_val = stats.t.ppf(1 - 0.05/2, df_err)
    cd = sem * np.sqrt(2) * t_val
    
    return {"anova": anova, "mean": grand_mean, "sem": sem, "cv": cv, "cd": cd}

def format_anova_txt(anova_df, sem, cd):
    """Converts ANOVA table to text with SEm and CD columns like PDF"""
    # Define Header
    txt = f"{'Source':<20} | {'DF':<4} | {'SS':<10} | {'MS':<10} | {'F-Cal':<6} | {'SEm':<8} | {'CD':<8}\n" 
    txt += "-"*85 + "\n"
    
    for idx, row in anova_df.iterrows():
        source = idx.replace("C(", "").replace(")", "").replace("Residual", "Error")
        f_val = f"{row['F']:.2f}" if not pd.isna(row['F']) else "-"
        
        # Only add SEm and CD to the Treatment row
        if source == "Treatment":
            s_val = f"{sem:.3f}"
            c_val = f"{cd:.3f}"
        else:
            s_val = "-"
            c_val = "-"

        txt += f"{source:<20} | {int(row['df']):<4} | {row['sum_sq']:<10.2f} | {row['mean_sq']:<10.2f} | {f_val:<6} | {s_val:<8} | {c_val:<8}\n"
    return txt

# --- 3. STREAMLIT APP INTERFACE ---
st.set_page_config(page_title="AgriStat Package", layout="wide")
st.title("🌾 Agricultural Statistical Package")
st.markdown("Perform **RBD Analysis** with outputs matching standard PDF reports (SEm, CD in table).")

# SIDEBAR: Upload and Settings
st.sidebar.header("Data Setup")
uploaded_file = st.sidebar.file_uploader("Upload Combined Data (Excel/CSV)", type=['xlsx', 'csv'])
trans_type = st.sidebar.selectbox("Transformation", ["Original Data", "Square Root", "Arcsine"])

if uploaded_file:
    # READ DATA
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
        
        # CLEAN DATA
        df.columns = df.columns.str.strip()
        if 'Year' not in df.columns: df.rename(columns={df.columns[0]: 'Year'}, inplace=True)
        if 'Treatment' not in df.columns: df.rename(columns={df.columns[1]: 'Treatment'}, inplace=True)
        
        # RESHAPE
        id_vars = ['Year', 'Treatment']
        val_vars = [c for c in df.columns if c not in id_vars]
        df_long = df.melt(id_vars=id_vars, value_vars=val_vars, var_name='Replication', value_name='Yield')
        df_long['Yield'] = pd.to_numeric(df_long['Yield'], errors='coerce')

        # TRANSFORM
        if trans_type == "Square Root":
            df_long['Analyzed_Value'] = np.sqrt(df_long['Yield'] + 0.5)
        elif trans_type == "Arcsine":
            safe = df_long['Yield'].clip(0, 100)
            df_long['Analyzed_Value'] = np.degrees(np.arcsin(np.sqrt(safe / 100)))
        else:
            df_long['Analyzed_Value'] = df_long['Yield']
            
        st.sidebar.success(f"Loaded: {df_long['Year'].nunique()} Years, {df_long['Treatment'].nunique()} Treatments")

    except Exception as e:
        st.error(f"Error reading file: {e}")
        st.stop()

    # BUTTON TO RUN
    if st.button("Run Analysis", type="primary"):
        log_lines = [] 
        def log(txt): log_lines.append(str(txt))
        
        log(f"Transformation Used: {trans_type}")
        
        tab1, tab2 = st.tabs(["Individual Years", "Pooled Analysis"])
        
        # --- TAB 1: INDIVIDUAL YEARS ---
        with tab1:
            for year in df_long['Year'].unique():
                st.subheader(f"Year: {year}")
                log(f"\n--- YEAR {year} ANALYSIS ---")
                
                df_curr = df_long[df_long['Year'] == year]
                res = run_anova(df_curr, 'Analyzed_Value')
                
                # Metrics
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Gen Mean", f"{res['mean']:.2f}")
                c2.metric("SEm", f"{res['sem']:.3f}")
                c3.metric("CD (5%)", f"{res['cd']:.3f}")
                c4.metric("CV %", f"{res['cv']:.2f}")
                
                log(f"General Mean: {res['mean']:.3f} | CV%: {res['cv']:.2f}")
                
                # Table with SEm/CD columns
                txt_table = format_anova_txt(res['anova'], res['sem'], res['cd'])
                st.text(txt_table)
                log(txt_table)
        
        # --- TAB 2: POOLED ANALYSIS ---
        with tab2:
            st.subheader("Pooled Analysis")
            log("\n--- POOLED ANALYSIS ---")
            
            formula = 'Analyzed_Value ~ C(Year) + C(Replication):C(Year) + C(Treatment) + C(Year):C(Treatment)'
            model_pool = ols(formula, data=df_long).fit()
            anova_pool = sm.stats.anova_lm(model_pool, typ=1)
            
            # Logic
            try:
                ms_err = anova_pool.loc['Residual', 'mean_sq']
                df_err = anova_pool.loc['Residual', 'df']
                ms_int = anova_pool.loc['C(Year):C(Treatment)', 'mean_sq']
                df_int = anova_pool.loc['C(Year):C(Treatment)', 'df']
                p_int = anova_pool.loc['C(Year):C(Treatment)', 'PR(>F)']
                ms_trt = anova_pool.loc['C(Treatment)', 'mean_sq']
                
                is_sig_int = p_int < 0.05
                if is_sig_int:
                    valid_ms, valid_df = ms_int, df_int
                    f_trt = ms_trt / ms_int
                    note = "Tested vs Interaction (Significant *)"
                else:
                    valid_ms, valid_df = ms_err, df_err
                    f_trt = ms_trt / ms_err
                    note = "Tested vs Pooled Error (NS)"
                
                # Stats
                n_yrs, n_reps = df_long['Year'].nunique(), df_long['Replication'].nunique()
                sem_pool = np.sqrt(valid_ms / (n_yrs * n_reps))
                cd_pool = sem_pool * np.sqrt(2) * stats.t.ppf(1 - 0.05/2, valid_df)
                
                # Interaction Stats
                sem_int = np.sqrt(ms_err / n_reps) # SEm for interaction
                cd_int = sem_int * np.sqrt(2) * stats.t.ppf(1 - 0.05/2, df_err)

                gm_pool = df_long['Analyzed_Value'].mean()
                cv_pool = (np.sqrt(ms_err) / gm_pool) * 100
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Interaction", "SIG *" if is_sig_int else "NS")
                c2.metric("SEm (Trt)", f"{sem_pool:.3f}")
                c3.metric("CD (Trt)", f"{cd_pool:.3f}")
                c4.metric("CV %", f"{cv_pool:.2f}")
                
                log(f"Interaction: {'SIG' if is_sig_int else 'NS'} | CV%: {cv_pool:.2f}")
                
                # Manual Pooled Table with SEm/CD Columns
                st.write("**Pooled ANOVA Table**")
                p_txt = f"{'Source':<22} | {'DF':<4} | {'MS':<10} | {'F-Cal':<6} | {'Sig':<4} | {'SEm':<8} | {'CD':<8}\n" 
                p_txt += "-"*90 + "\n"
                
                rows = [
                    ('C(Replication):C(Year)', 'Rep(Year)'), 
                    ('C(Year)', 'Year'), 
                    ('C(Treatment)', 'Treatment'), 
                    ('C(Year):C(Treatment)', 'Year x Trt'), 
                    ('Residual', 'Pooled Error')
                ]
                
                for code, name in rows:
                    r = anova_pool.loc[code]
                    s_val, c_val = "-", "-"
                    
                    if code == 'C(Treatment)':
                         f_val, sig = f_trt, ("*" if (1-stats.f.cdf(f_trt, r['df'], valid_df)) < 0.05 else "NS")
                         s_val, c_val = f"{sem_pool:.3f}", f"{cd_pool:.3f}"
                    elif code == 'C(Year):C(Treatment)':
                         f_val, sig = r['F'], ("*" if r['PR(>F)'] < 0.05 else "NS")
                         # Show Interaction SEm/CD only if significant or if user wants to see it
                         s_val, c_val = f"{sem_int:.3f}", (f"{cd_int:.3f}" if is_sig_int else "NS")
                    elif code in ['Residual', 'C(Replication):C(Year)']:
                         f_val, sig = np.nan, ""
                    else:
                         f_val, sig = r['F'], ("*" if r['PR(>F)'] < 0.05 else "NS")
                    
                    f_s = f"{f_val:.2f}" if not pd.isna(f_val) else "-"
                    p_txt += f"{name:<22} | {int(r['df']):<4} | {r['mean_sq']:<10.2f} | {f_s:<6} | {sig:<4} | {s_val:<8} | {c_val:<8}\n"
                
                st.text(p_txt)
                st.info(f"Note: {note}")
                log(p_txt)
                log(f"Note: {note}")

            except Exception as e:
                st.error(f"Pooled Error: {e}")

        # --- MEAN TABLE GENERATION ---
        st.subheader("Mean Table (Year x Treatment)")
        log("\n--- MEAN TABLE ---")
        
        # Calculate means
        means = df_long.groupby(['Treatment', 'Year'])['Analyzed_Value'].mean().unstack()
        means['Pooled Mean'] = means.mean(axis=1)
        
        # Format table
        mean_txt = f"{'Treatment':<10} |"
        for col in means.columns:
            mean_txt += f" {str(col):<10} |"
        mean_txt += "\n" + "-" * (15 + 13 * len(means.columns)) + "\n"
        
        for idx, row in means.iterrows():
            mean_txt += f"{str(idx):<10} |"
            for val in row:
                mean_txt += f" {val:<10.2f} |"
            mean_txt += "\n"
            
        st.text(mean_txt)
        log(mean_txt)

        # --- PDF DOWNLOADER ---
        pdf = PDFReport()
        pdf.add_page()
        pdf.set_font("Courier", size=9)
        for line in log_lines:
            pdf.multi_cell(0, 5, txt=line)
            
        pdf_out = pdf.output(dest='S').encode('latin-1')
        st.download_button("📄 Download PDF Report", data=pdf_out, file_name="RBD_Report.pdf", mime="application/pdf")