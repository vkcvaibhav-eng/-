import streamlit as st
import google.generativeai as genai
import sqlite3
import datetime
from PIL import Image
import io
import os
import PyPDF2
from docx import Document as DocxReader
import urllib.request
from fpdf import FPDF

# ==========================================
# Database Setup for Archiving
# ==========================================
DB_FILE = "sadar_nondh_archive.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS archive 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  date TEXT, 
                  month TEXT, 
                  year TEXT, 
                  subject TEXT, 
                  content TEXT)''')
    conn.commit()
    conn.close()

def save_to_db(subject, content):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.datetime.now()
    c.execute("INSERT INTO archive (date, month, year, subject, content) VALUES (?, ?, ?, ?, ?)", 
              (now.strftime("%d/%m/%Y"), now.strftime("%m"), now.strftime("%Y"), subject, content))
    conn.commit()
    conn.close()

def get_archives(month, year):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if month == "All":
        c.execute("SELECT date, subject, content FROM archive WHERE year=?", (year,))
    else:
        c.execute("SELECT date, subject, content FROM archive WHERE month=? AND year=?", (month, year))
    data = c.fetchall()
    conn.close()
    return data

init_db()

# ==========================================
# Permanent Attachments Extraction
# ==========================================
@st.cache_data
def load_permanent_context():
    statute_text = "Statute 121 Rules:\n"
    sample_text = "Sample Nondh Format:\n"
    
    if os.path.exists("121_Statutes_uploaded.pdf"):
        try:
            with open("121_Statutes_uploaded.pdf", "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    statute_text += page.extract_text() + "\n"
        except Exception as e:
            st.warning(f"Could not load 121 Statutes PDF: {e}")

    if os.path.exists("sample_nondh_uploaded.docx"):
        try:
            doc = DocxReader("sample_nondh_uploaded.docx")
            for para in doc.paragraphs:
                sample_text += para.text + "\n"
        except Exception as e:
            st.warning(f"Could not load sample_nondh DOCX: {e}")
            
    return statute_text, sample_text

# ==========================================
# Document Generation Logic (FPDF2 Engine)
# ==========================================
def create_pdf(content):
    font_path_regular = "NotoSansGujarati-Regular.ttf"
    font_path_bold = "NotoSansGujarati-Bold.ttf"
    
    # Download Regular Font
    if not os.path.exists(font_path_regular):
        try:
            url_reg = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansGujarati/NotoSansGujarati-Regular.ttf"
            urllib.request.urlretrieve(url_reg, font_path_regular)
        except Exception:
            pass

    # Download Bold Font (Fixes the FPDFException)
    if not os.path.exists(font_path_bold):
        try:
            url_bold = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansGujarati/NotoSansGujarati-Bold.ttf"
            urllib.request.urlretrieve(url_bold, font_path_bold)
        except Exception:
            pass
            
    # Setup A5 Landscape (210 x 148.5 mm)
    pdf = FPDF(orientation="L", unit="mm", format="A5")
    pdf.set_margins(10, 10, 10)
    pdf.add_page()
    
    # Load Regular Font
    try:
        pdf.add_font("Gujarati", style="", fname=font_path_regular)
    except Exception:
        pass
        
    # Load Bold Font safely
    has_bold = False
    if os.path.exists(font_path_bold):
        try:
            pdf.add_font("Gujarati", style="B", fname=font_path_bold)
            has_bold = True
        except Exception:
            pass
            
    pdf.set_font("Gujarati", size=10)
    
    # Enable Text Shaping to fix Gujarati Matras
    try:
        pdf.set_text_shaping(True)
    except Exception:
        pass 

    lines = content.split('\n')
    table_data = []
    in_table = False
    
    sig_roles = []
    principal_role = ""

    def render_buffered_table():
        if not table_data:
            return
        pdf.ln(3)
        # Find exactly how many columns the table should have based on the longest row
        max_cols = max(len(r) for r in table_data)
        
        # Pad any rows that might have missing cells to prevent FPDFException
        for r in table_data:
            while len(r) < max_cols:
                r.append("")
                
        c_widths = (15, 75, 25, 30, 35) if max_cols == 5 else None
        
        # CRITICAL FIX: first_row_as_headings=has_bold 
        # This gives bold headers if the font loaded, or safe regular headers if it didn't
        with pdf.table(borders_layout="ALL", text_align="CENTER", col_widths=c_widths, line_height=7, first_row_as_headings=has_bold) as table:
            for row_text in table_data:
                row = table.row()
                for c_idx, cell_text in enumerate(row_text):
                    # Left align the 'Details' column
                    row.cell(cell_text, align="L" if c_idx == 1 else "C")
        pdf.ln(5)

    for line in lines:
        line_stripped = line.strip()
        
        if not line_stripped:
            continue
            
        if line_stripped.startswith('|'):
            in_table = True
            
            # Correct markdown parsing (preserves empty cells)
            parts = line_stripped.split('|')
            if parts and not parts[0].strip():
                parts = parts[1:]
            if parts and not parts[-1].strip():
                parts = parts[:-1]
                
            row = [cell.strip() for cell in parts]
            
            # Skip markdown separator lines (e.g. |:---|:---|) safely
            if row and all(all(c in '-: ' for c in cell) for cell in row):
                continue
                
            table_data.append(row)
        else:
            if in_table and table_data:
                render_buffered_table()
                table_data = []
                in_table = False
            
            # Position Specific Text Blocks
            if line_stripped.startswith("તા.") or line_stripped.startswith("સ્થળ:"):
                pdf.cell(0, 5, line_stripped, ln=True, align="R")
                
            elif "સાદર નોંધ" in line_stripped:
                pdf.ln(2)
                # Use bold if available
                if has_bold:
                    pdf.set_font("Gujarati", style="B", size=11)
                else:
                    pdf.set_font("Gujarati", style="", size=11)
                    
                pdf.cell(0, 6, line_stripped, ln=True, align="L")
                pdf.set_font("Gujarati", style="", size=10)
                
            elif line_stripped.startswith("વિષય:"):
                if has_bold:
                    pdf.set_font("Gujarati", style="B", size=10)
                pdf.multi_cell(0, 5, line_stripped, align="L")
                pdf.set_font("Gujarati", style="", size=10)
                pdf.ln(3)
                
            elif any(role in line_stripped for role in ["અધિકારી", "ઈન્ચાર્જ", "પ્રાધ્યાપક", "વડા"]) and not any(r in line_stripped for r in ["આચાર્ય", "ડીનશ્રી"]):
                # Accumulate Committee Signatures
                sig_roles.append(line_stripped.replace(",", "\n"))
                
            elif any(role in line_stripped for role in ["આચાર્ય", "ડીનશ્રી", "મહાવિધાયલય", "ન.કૃ.યુ"]):
