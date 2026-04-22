import streamlit as st
import google.generativeai as genai
from docx import Document
from docx.shared import Mm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import sqlite3
import datetime
from PIL import Image
import io

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
# Document Generation Logic (A4 Layout)
# ==========================================
def create_docx(content):
    doc = Document()
    
    # Set page size to A4
    section = doc.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    
    lines = content.split('\n')
    table_data = []
    in_table = False
    
    for line in lines:
        line_stripped = line.strip()
        if line_stripped.startswith('|'):
            in_table = True
            row = [cell.strip() for cell in line_stripped.split('|') if cell.strip()]
            # Skip markdown separator row (e.g., |---|---|)
            if not all(c == '-' for c in row[0].replace(' ', '')): 
                table_data.append(row)
        else:
            if in_table:
                # Render table when exiting table block
                if table_data:
                    table = doc.add_table(rows=len(table_data), cols=len(table_data[0]))
                    table.style = 'Table Grid'
                    for i, row in enumerate(table_data):
                        for j, cell in enumerate(row):
                            if j < len(table.columns):
                                table.cell(i, j).text = cell
                table_data = []
                in_table = False
            
            if line_stripped:
                # Special alignment for signature blocks at the bottom
                p = doc.add_paragraph(line_stripped)
                if "પ્રાધ્યાપક અને વડા" in line_stripped or "આચાર્ય" in line_stripped:
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                
    # Catch any remaining table at the end
    if in_table and table_data:
        table = doc.add_table(rows=len(table_data), cols=len(table_data[0]))
        table.style = 'Table Grid'
        for i, row in enumerate(table_data):
            for j, cell in enumerate(row):
                if j < len(table.columns):
                    table.cell(i, j).text = cell

    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

# ==========================================
# Streamlit App UI
# ==========================================
st.set_page_config(page_title="સાદર નોંધ જનરેટર", layout="wide")
st.title("સાદર નોંધ જનરેટર (Intelligent Sadar Nondh App)")

api_key = st.sidebar.text_input("Enter Gemini API Key", type="password")

tab1, tab2 = st.tabs(["નવી સાદર નોંધ બનાવો (Create New)", "જુની નોંધ (Archives)"])

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
        elif not text_prompt and not uploaded_image:
            st.warning("Please provide either a text requirement or an image.")
        else:
            with st.spinner("તમારી માહિતી સમજવામાં અને નોંધ તૈયાર કરવામાં આવી રહી છે..."):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel('gemini-1.5-pro')
                    
                    # Core context integrated from standard department layouts and Statute 121
                    sys_prompt = f"""
                    You are an expert administrative AI for the Department of Entomology, N. M. College of Agriculture, NAU, Navsari.
                    Your task is to generate a formal 'સાદર નોંધ' in Gujarati based on the user's brief input or image. 
                    If the user does not provide a detailed reason for the purchase, logically invent a highly relevant academic/research justification suitable for the AINP on Agricultural Acarology project or general Entomology department needs.
                    
                    Statute 121 Rules to strictly apply based on context:
                    - 45 (iii) (iii): Consumables, petty stores, stationery, miscellaneous office expenses, printing.
                    - 54 (i): Seeds, chemicals, insecticides, fertilizers, farm inputs, lab chemicals.
                    - 41 (iii) (iii) / 41 (iv): Computer hardware, accessories, electronics, printers.
                    - 48 (ii) (i): Repairs and maintenance of equipment.
                    - 63 (iii) (iii): Printing, charts, publications, booklets.
                    - 45-A (New) (iii) (iii): Electricity, diesel/fuel, honorarium, TA/DA, seminar expenses.

                    Format REQUIRED:
                    તા. {datetime.date.today().strftime('%d/%m/%Y')}
                    સ્થળ: નવસારી
                    સાદર નોંધ:
                    વિષય: [Appropriate Subject]
                    સવિનય ઉપરોક્ત વિષય અન્વયે જણાવવાનું કે, અત્રેના કિટકશાસ્ત્ર વિભાગમાં [Detailed logical reason]. સદર વસ્તુનો કુલ અંદાજિત ખર્ચ [Total Amount] થનાર છે.
                    સદર ખર્ચની ખરીદી કરવા આપશ્રીની સતા અન્વયે સ્ટેચ્યુટ ૧૨૧ની આઈટમ નંબર [Insert Correct Item No. from rules above] મુજબ સૈદ્ધાંતિક મંજુરી આપવા આપ સાહેબશ્રીને નમ્ર વિનંતી છે.
                    સદર ખર્ચ અત્રેના વિભાગમાં ચાલતી આઈ.સી.એ.આર. યોજના (બ.સ. ૩૦૩/૨૦૯૨) માં કરવામાં આવશે.

                    [If multiple items, include a markdown table. Columns MUST be: ક્રમ | વિગત | જથ્થો | કિંમત | કુલ કિંમત]

                    પ્રાધ્યાપક અને વડા, કિટકશાસ્ત્ર વિભાગ
                    આચાર્યશ્રી, ન.મ.કૃ.મ., નકૃયુ, નવસારી
                    """
                    
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
                # Extract subject line automatically for database indexing
                subject_line = "No Subject"
                for line in edited_text.split('\n'):
                    if "વિષય:" in line:
                        subject_line = line.replace("વિષય:", "").strip()
                        break
                save_to_db(subject_line, edited_text)
                st.success("નોંધ ડેટાબેઝમાં સાચવી લેવામાં આવી છે!")
                
        with col_down:
            docx_data = create_docx(edited_text)
            st.download_button(label="Download as Word Document (A4)",
                               data=docx_data,
                               file_name=f"Sadar_Nondh_{datetime.date.today().strftime('%d_%m_%Y')}.docx",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

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
                    
                    # Generate a unique download button for archived files
                    archived_docx = create_docx(content)
                    st.download_button(label="Download this Document",
                                       data=archived_docx,
                                       file_name=f"Archive_{date.replace('/', '_')}.docx",
                                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                       key=f"dl_{idx}")
        else:
            st.info("કોઈ રેકોર્ડ મળેલ નથી (No records found for this period).")
