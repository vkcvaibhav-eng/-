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
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib import colors

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
    
    # Read Statute PDF
    if os.path.exists("121_Statutes_uploaded.pdf"):
        try:
            with open("121_Statutes_uploaded.pdf", "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    statute_text += page.extract_text() + "\n"
        except Exception as e:
            st.warning(f"Could not load 121 Statutes PDF: {e}")

    # Read Sample DOCX
    if os.path.exists("sample_nondh_uploaded.docx"):
        try:
            doc = DocxReader("sample_nondh_uploaded.docx")
            for para in doc.paragraphs:
                sample_text += para.text + "\n"
        except Exception as e:
            st.warning(f"Could not load sample_nondh DOCX: {e}")
            
    return statute_text, sample_text

# ==========================================
# Document Generation Logic (Perfect Half A4 Layout)
# ==========================================
def create_pdf(content):
    # Download Gujarati Font automatically if missing
    font_path = "NotoSansGujarati-Regular.ttf"
    if not os.path.exists(font_path):
        try:
            url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansGujarati/NotoSansGujarati-Regular.ttf"
            urllib.request.urlretrieve(url, font_path)
        except Exception as e:
            pass # Failsafe
            
    try:
        pdfmetrics.registerFont(TTFont('Gujarati', font_path))
        font_name = 'Gujarati'
    except:
        font_name = 'Helvetica' # Fallback if font fails

    bio = io.BytesIO()
    
    # Half A4 setup (210mm wide x 148.5mm high - A5 Landscape)
    doc = SimpleDocTemplate(bio, pagesize=(210*mm, 148.5*mm),
                            rightMargin=15*mm, leftMargin=15*mm,
                            topMargin=10*mm, bottomMargin=10*mm)
    
    styles = {
        'normal': ParagraphStyle('Normal', fontName=font_name, fontSize=11, leading=18),
        'bold': ParagraphStyle('Bold', fontName=font_name, fontSize=11, leading=18),
        'right': ParagraphStyle('Right', fontName=font_name, fontSize=11, leading=18, alignment=TA_RIGHT)
    }
    
    elements = []
    lines = content.split('\n')
    table_data = []
    in_table = False
    
    for line in lines:
        line_stripped = line.strip()
        
        # Skip empty lines to control spacing manually
        if not line_stripped:
            continue
            
        if line_stripped.startswith('|'):
            in_table = True
            row = [cell.strip() for cell in line_stripped.split('|') if cell.strip()]
            # Skip Markdown separator line (e.g. |---|---|)
            if not all(c == '-' for c in row[0].replace(' ', '')): 
                table_data.append(row)
        else:
            # Render Table when exiting the markdown table block
            if in_table:
                if table_data:
                    table_style = [
                        ('FONTNAME', (0,0), (-1,-1), font_name),
                        ('FONTSIZE', (0,0), (-1,-1), 10),
                        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                        ('PADDING', (0,0), (-1,-1), 4),
                    ]
                    # Left align the second column (Details/વિગત) if it exists
                    if len(table_data[0]) > 1:
                        table_style.append(('ALIGN', (1,0), (1,-1), 'LEFT'))
                        
                    t = Table(table_data)
                    t.setStyle(TableStyle(table_style))
                    elements.append(Spacer(1, 5))
                    elements.append(t)
                    elements.append(Spacer(1, 10))
                table_data = []
                in_table = False
            
            # Position Specific Text Blocks
            if line_stripped.startswith("તા.") or line_stripped.startswith("સ્થળ:"):
                elements.append(Paragraph(line_stripped, styles['right']))
            
            elif "સાદર નોંધ" in line_stripped:
                elements.append(Spacer(1, 5))
                elements.append(Paragraph(f"<b>{line_stripped}</b>", styles['bold']))
            
            elif line_stripped.startswith("વિષય:"):
                elements.append(Paragraph(f"<b>{line_stripped}</b>", styles['bold']))
                elements.append(Spacer(1, 5))
            
            elif any(role in line_stripped for role in ["અધિકારી", "ઈન્ચાર્જ", "પ્રાધ્યાપક", "વડા"]):
                # Right Side Signatures: Add 30pt blank space above EACH for handwritten signatures
                elements.append(Spacer(1, 30))
                elements.append(Paragraph(line_stripped, styles['right']))
                
            elif any(role in line_stripped for role in ["આચાર્ય", "ડીનશ્રી", "મહાવિધાયલય", "ન.કૃ.યુ"]):
                # Left Side Signature (Principal)
                if "આચાર્ય" in line_stripped:
                    elements.append(Spacer(1, 30)) # Add sign space only before the title
                elements.append(Paragraph(line_stripped, styles['normal']))
            
            else:
                # Normal Body Text
                elements.append(Paragraph(line_stripped, styles['normal']))
                elements.append(Spacer(1, 3))
                
    # Failsafe if the document ends with a table
    if in_table and table_data:
        t = Table(table_data)
        table_style = [
            ('FONTNAME', (0,0), (-1,-1), font_name),
            ('FONTSIZE', (0,0), (-1,-1), 10),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('PADDING', (0,0), (-1,-1), 4),
        ]
        if len(table_data[0]) > 1:
            table_style.append(('ALIGN', (1,0), (1,-1), 'LEFT'))
        t.setStyle(TableStyle(table_style))
        elements.append(t)

    doc.build(elements)
    return bio.getvalue()

# ==========================================
# Streamlit App UI
# ==========================================
st.set_page_config(page_title="સાદર નોંધ જનરેટર", layout="wide")
st.title("સાદર નોંધ જનરેટર (Intelligent Sadar Nondh App)")

api_key = st.sidebar.text_input("Enter Gemini API Key", type="password")

tab1, tab2, tab3 = st.tabs(["નવી સાદર નોંધ બનાવો (Create New)", "જુની નોંધ (Archives)", "સેટિંગ્સ (Settings / Files)"])

with tab1:
    st.markdown("### જરૂરિયાતની વિગત આપો (Provide Requirements)")
    
    col1, col2 = st.columns(2)
    with col1:
        text_prompt = st.text_area("તમારી જરૂરિયાત લખો (Write short requirement):", 
                                   placeholder="e.g., need 10 entomological pins and 5 files for the AINP scheme.")
    with col2:
        uploaded_image = st.file_uploader("અથવા હાથથી લખેલી ચબરખીનો ફોટો અપલોડ કરો (Upload handwritten note):", type=["jpg", "jpeg", "png"])
    
    if st.button("જનરેટ કરો (Generate)"):
        if not api_key:
            st.error("Please enter your Gemini API Key in the sidebar.")
        elif not os.path.exists("121_Statutes_uploaded.pdf") or not os.path.exists("sample_nondh_uploaded.docx"):
             st.warning("Please upload the Statute PDF and Sample DOCX in the 'સેટિંગ્સ (Settings)' tab first.")
        elif not text_prompt and not uploaded_image:
            st.warning("Please provide either a text requirement or an image.")
        else:
            with st.spinner("સ્ટેચ્યુટ ૧૨૧ ની ચકાસણી અને નોંધ તૈયાર કરવામાં આવી રહી છે..."):
                try:
                    statute_context, sample_context = load_permanent_context()
                    
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
                    
                    sys_prompt = f"""
                    You are an expert administrative AI for the Department of Entomology, N. M. College of Agriculture, NAU, Navsari.
                    Your task is to generate a formal 'સાદર નોંધ' in Gujarati based on the user's brief input or image. 
                    
                    CRITICAL INSTRUCTION: You MUST read the provided 'Statute 121 Rules' below and select the exact correct Item Number for the requested items.
                    CRITICAL INSTRUCTION: You MUST format the output EXACTLY matching the 'Sample Nondh Format' provided below. Do not add any conversational text.
                    
                    If the user does not provide a detailed reason, logically invent a highly relevant academic/research justification suitable for the AINP on Agril Acarology project (Budget Head 303/2092).
                    
                    [CONTEXT START]
                    {statute_context[:15000]}
                    
                    {sample_context}
                    [CONTEXT END]

                    Format REQUIRED:
                    તા. {datetime.date.today().strftime('%d/%m/%Y')}
                    સ્થળ: નવસારી
                    સાદર નોંધ:
                    વિષય: [Appropriate Subject...]
                    સવિનય ઉપરોક્ત વિષય અન્વયે જણાવવાનું કે, અત્રેનાં કીટકશાસ્ત્ર વિભાગની આઈ.સી.એ.આર. યોજના AINP on Agril Acarology બ.સ. ૩૦૩/૨૦૯૨ અંતર્ગત [Detailed logical reason]. સદર વસ્તુનો કુલ અંદાજિત ખર્ચ [Total Amount] થનાર છે.
                    જે આપ સાહેબશ્રીને સ્ટેચ્યુટ ૧૨૧ની આઈટમ નંબર [Insert Correct Item No. from Statute] મુજબ એનાયત થયેલ સત્તા અનુસાર સૈદ્ધાંતિક મંજુરી આપવા વિનંતી. સદર ખર્ચ અત્રેના વિભાગમાં ચાલતી આઈ.સી.એ.આર યોજના (બ.સ. ૩૦૩/૨૦૯૨) માં કરવામાં આવશે.

                    [If multiple items, include a markdown table. Columns MUST be: ક્રમ | વિગત | જથ્થો | કિંમત | કુલ કિંમત]

                    # 1. Data for the first row of 3 signatures
row_1_signatures = [
    [
        "ખેતીવાડી અધિકારી\nકીટકશાસ્ત્ર વિભાગ", 
        "પ્રોજેકટ ઈન્ચાર્જ\nકીટકશાસ્ત્ર વિભાગ", 
        "પ્રાધ્યાપક અને વડા\nકીટકશાસ્ત્ર વિભાગ"
    ]
]

# Create a 3-column table evenly spaced across the page
sig_table_1 = Table(row_1_signatures, colWidths=['33%', '34%', '33%'])
sig_table_1.setStyle(TableStyle([
    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),  # Center text in each column
    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ('TOPPADDING', (0, 0), (-1, -1), 60),   # Adds 60 points of blank space ABOVE text for the physical signature
]))

# 2. Data for the Principal/Dean signature (bottom right)
row_2_signatures = [
    [
        "", # Empty left column
        "", # Empty middle column
        "આચાર્ય અને ડીનશ્રી\nન. મ. કૃષિ મહાવિધાયલય\nન.કૃ.યુ. નવસારી" # Right column
    ]
]

sig_table_2 = Table(row_2_signatures, colWidths=['33%', '34%', '33%'])
sig_table_2.setStyle(TableStyle([
    ('ALIGN', (2, 0), (2, 0), 'CENTER'),    # Center the text in the rightmost column
    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ('TOPPADDING', (0, 0), (-1, -1), 60),   # Space for the Dean's signature
]))

# 3. Add these to your document 'Story' (the list of elements to build)
# story.append(Spacer(1, 40)) # Add some space after your main table
# story.append(sig_table_1)
# story.append(Spacer(1, 20)) # Space between the two signature rows
# story.append(sig_table_2)
                    
                    inputs = [sys_prompt, text_prompt]
                    if uploaded_image:
                        img = Image.open(uploaded_image)
                        inputs.append(img)
                        
                    response = model.generate_content(inputs)
                    generated_text = response.text
                    
                    st.session_state['generated_nondh'] = generated_text
                    st.success("સાદર નોંધ સફળતાપૂર્વક તૈયાર થઈ ગઈ છે!")
                    
                except Exception as e:
                    st.error(f"Error generating document: {e}")

    if 'generated_nondh' in st.session_state:
        st.markdown("### ડ્રાફ્ટ (Draft Review)")
        edited_text = st.text_area("તમે અહીં સુધારા-વધારા કરી શકો છો (Edit if required):", 
                                   st.session_state['generated_nondh'], height=350)
        
        col_save, col_down = st.columns(2)
        with col_save:
            if st.button("આર્કાઇવમાં સેવ કરો (Save & Approve)"):
                subject_line = "No Subject"
                for line in edited_text.split('\n'):
                    if "વિષય:" in line:
                        subject_line = line.replace("વિષય:", "").strip()
                        break
                save_to_db(subject_line, edited_text)
                st.success("નોંધ ડેટાબેઝમાં સાચવી લેવામાં આવી છે!")
                
        with col_down:
            pdf_data = create_pdf(edited_text)
            st.download_button(label="Download as PDF",
                               data=pdf_data,
                               file_name=f"Sadar_Nondh_{datetime.date.today().strftime('%d_%m_%Y')}.pdf",
                               mime="application/pdf")

with tab2:
    st.markdown("### જુની નોંધ શોધો (Search Archives)")
    
    current_year = datetime.date.today().year
    years = [str(y) for y in range(current_year-2, current_year+3)]
    months = ["All", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
    
    col_y, col_m = st.columns(2)
    with col_y:
        sel_year = st.selectbox("વર્ષ (Year):", years, index=2)
    with col_m:
        sel_month = st.selectbox("મહિનો (Month):", months)
        
    if st.button("શોધો (Search)"):
        records = get_archives(sel_month, sel_year)
        if records:
            for idx, record in enumerate(records):
                date, subject, content = record
                with st.expander(f"{date} - {subject}"):
                    st.text(content)
                    
                    archived_pdf = create_pdf(content)
                    st.download_button(label="Download this Document (PDF)",
                                       data=archived_pdf,
                                       file_name=f"Archive_{date.replace('/', '_')}.pdf",
                                       mime="application/pdf",
                                       key=f"dl_{idx}")
        else:
            st.info("કોઈ રેકોર્ડ મળેલ નથી (No records found for this period).")

with tab3:
    st.markdown("### કાયમી ફાઇલો અપલોડ કરો (Upload Permanent Reference Files)")
    st.info("અહીં એકવાર અપલોડ કરેલી ફાઇલો એપમાં સેવ થઈ જશે અને દર વખતે નવી નોંધ બનાવતી વખતે બેકગ્રાઉન્ડમાં ઉપયોગમાં લેવાશે.")
    
    col_pdf, col_docx = st.columns(2)
    
    with col_pdf:
        statute_file = st.file_uploader("સ્ટેચ્યુટ પીડીએફ (Statute 121 PDF):", type=["pdf"])
        if statute_file:
            if st.button("Save Statute PDF"):
                with open("121_Statutes_uploaded.pdf", "wb") as f:
                    f.write(statute_file.getbuffer())
                load_permanent_context.clear() # Clear cache to refresh context
                st.success("Statute PDF saved permanently!")
        
        if os.path.exists("121_Statutes_uploaded.pdf"):
            st.success("✅ Statute PDF is currently saved and active.")

    with col_docx:
        sample_file = st.file_uploader("નમૂનાની વર્ડ ફાઇલ (Sample Nondh DOCX):", type=["docx"])
        if sample_file:
            if st.button("Save Sample DOCX"):
                with open("sample_nondh_uploaded.docx", "wb") as f:
                    f.write(sample_file.getbuffer())
                load_permanent_context.clear() # Clear cache to refresh context
                st.success("Sample DOCX saved permanently!")
                
        if os.path.exists("sample_nondh_uploaded.docx"):
            st.success("✅ Sample DOCX is currently saved and active.")

