import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from datetime import time
from rapidfuzz import fuzz
from calendar import monthrange

def match_names(df, col1="Receiver Name - WU", col2="Receiver Name - IBAG"):
    if {col1, col2}.issubset(df.columns):
        equivalent_names = {name.lower(): [name.lower()] for name in df[col1].dropna().unique()}

        def compare_names(name1, name2):
            if pd.isna(name1) or pd.isna(name2):
                return 0
            name1, name2 = str(name1).lower().strip(), str(name2).lower().strip()
            if name1 == name2 or name2 in equivalent_names.get(name1, []):
                return 100
            return fuzz.ratio(name1, name2)

        df["Similarity (%)"] = df.apply(lambda row: compare_names(row[col1], row[col2]), axis=1)

        def categorize_similarity(score):
            if score >= 91:
                return "Correct Name"
            elif 81 <= score < 91:
                return "Wrong Middle Name"
            elif 50 <= score < 81:
                return "Wrong Last Name"
            else:
                return "Wrong Name"

        df["Name Match Category"] = df["Similarity (%)"].apply(categorize_similarity)
    else:
        print("تأكد من أن الأعمدة WU_Name و IBAG_Name موجودة في الملف")
    return df


def calculate_peak_waiting_time_actual(df):
    df = df.sort_values(by='Creation Date')
    peak_waits = []

    for day, group in df.groupby('transaction_date'):
        group = group.sort_values('Creation Date')
        count = group.shape[0]

        if count <= 300 or count < 2:
            continue

        start = group['Creation Date'].iloc[0]
        end = group['Creation Date'].iloc[-1]
        total_minutes = (end - start).total_seconds() / 60

        expected_minutes = (count - 1) * 1  # دقيقة واحدة لكل تحويل
        excess_wait = max(total_minutes - expected_minutes, 0)

        peak_waits.append(excess_wait)

    avg_peak_wait = int(round(sum(peak_waits) / len(peak_waits))) if peak_waits else 0
    return avg_peak_wait



def calculate_system_downtime(df):
    df = df.sort_values(by='Creation Date')
    result = []
    for day, group in df.groupby('transaction_date'):
        group = group.sort_values('Creation Date')
        group['Prev Time'] = group['Creation Date'].shift(1)
        group['Gap (min)'] = (group['Creation Date'] - group['Prev Time']).dt.total_seconds() / 60
        downtime_gaps = group[group['Gap (min)'] > 30]['Gap (min)']
        total_downtime_hours = downtime_gaps.sum() / 60
        result.append({
            'تاريخ': day,
            'اليوم': pd.to_datetime(day).day_name(),
            'عدد_التحويلات': len(group),
            'عدد_الموظفين': group['Operator Id'].nunique(),
            'عدد_مرات_التوقف': downtime_gaps.count(),
            'إجمالي_ساعات_التوقف': round(total_downtime_hours, 2)
        })

    # تصفية الأيام التي لا يوجد بها توقف
    result_df = pd.DataFrame(result)
    result_df = result_df[result_df['عدد_مرات_التوقف'] > 0]
    return result_df












def classify_names(df, name_column='Sender Full Name'):
    ignore_words = ['Abu', 'Abdallah', 'Abdul', 'Abo', 'Abdel', 'Dr', 'Mr', 'Sir', 'Jr', 'Sr', 'FR']

    def classify_name(name):
        if pd.isna(name):
            return 'غير معروف'
        name_parts = [part for part in str(name).split() if part not in ignore_words]
        length = len(name_parts)
        if length == 2:
            return 'Two Names'
        elif length == 3:
            return 'Three Names'
        elif length > 3:
            return 'Full Name'
        else:
            return 'Invalid'

    df['Name Classification'] = df[name_column].apply(classify_name)
    return df

def add_transfer_duration(df):
    df = df.sort_values(by=['Operator Id', 'Creation Date'])
    df['Transfer Day'] = df['Creation Date'].dt.date
    df['Prev Transfer'] = df.groupby(['Operator Id', 'Transfer Day'])['Creation Date'].shift(1)
    df['Transfer Duration'] = (df['Creation Date'] - df['Prev Transfer']).dt.total_seconds() / 60
    df['Transfer Duration'] = df['Transfer Duration'].fillna(0)
    return df

def prepare_data(file):
    df = pd.read_excel(file)

    if "Sender Mobile Number" in df.columns:
        df["Sender Mobile Number"] = df["Sender Mobile Number"].astype(str)

    df['Creation Date'] = pd.to_datetime(df['Creation Date'], errors='coerce')
    df['Payout Time'] = pd.to_datetime(df['Payout Time'], format='%I:%M %p', errors='coerce').dt.time

    df["hour"] = df["Creation Date"].dt.hour
    df["day_of_week"] = df["Creation Date"].dt.day_name()
    df["month"] = df["Creation Date"].dt.month_name()
    df["transaction_date"] = df["Creation Date"].dt.date
    df["Minute"] = df["Creation Date"].dt.minute

    if "TRX Type" in df.columns:
        df['System'] = df['TRX Type'].apply(
            lambda x: 'App' if str(x).upper() == 'S&P' 
            else 'WC' if str(x).upper() == 'WC' 
            else 'Other'
        )
    else:
        df['System'] = 'Unknown'

    df['Amount_range'] = pd.cut(df['Actual Payout Amount'], bins=[0, 1000, 2000, 3000, 4999, float('inf')],
                                labels=['Limit_1000', 'Limit_2000', 'Limit_3000', 'Limit_5000', 'over_limit'])

    df['Sender Name Count'] = df.groupby('Sender Full Name')['Sender Full Name'].transform('count')

    df = classify_names(df)
    df = match_names(df)
    df = add_transfer_duration(df)

    return df

def branch_summary(df):
    report = {}
    report["unique_customers"] = df["Receiver Name - WU"].nunique()
    report["total_transfers"] = len(df)
    report["transfers_by_system"] = df["System"].value_counts().to_dict()

    day_stats = df.groupby("transaction_date").agg({
        "MTCN": "count",
        "Operator Id": lambda x: x.unique().tolist()
    }).reset_index()
    over_300 = day_stats[day_stats["MTCN"] > 300]
    report["high_transfer_days"] = over_300.to_dict(orient="records")

    if "Sender Country" in df.columns:
        top_countries = df["Sender Country"].value_counts().head(5).to_dict()
    else:
        top_countries = {}
    report["top_5_senders"] = top_countries

    report["total_amount"] = df["Actual Payout Amount"].sum()
    return report


def employee_summary(df):
    summary = {}
    for emp in df["Operator Id"].unique():
        emp_df = df[df["Operator Id"] == emp]
        days_worked = emp_df["transaction_date"].nunique()

        first_transactions = emp_df.groupby("transaction_date")["Creation Date"].min()
        first_transactions = pd.Series(first_transactions.values, index=pd.to_datetime(first_transactions.index))

        on_time_morning = first_transactions.between_time("08:30", "08:45").count()
        on_time_evening = first_transactions.between_time("13:30", "13:45").count()
        on_time_days = on_time_morning + on_time_evening
        commitment_score = on_time_days * 1

        summary[emp] = {
            "unique_clients": emp_df["Receiver Name - WU"].nunique(),
            "total_transfers": len(emp_df),
            "total_amount": emp_df["Actual Payout Amount"].sum(),
            "over_limit_transfers": emp_df[emp_df["Amount_range"] == "over_limit"].shape[0],
            "working_days": days_worked,
            "total_hours_worked": round(emp_df["Transfer Duration"].sum() / 60, 2),
            "avg_speed": round(emp_df["Transfer Duration"].mean(), 2),
            "high_volume_days": emp_df.groupby("transaction_date").size().gt(80).sum(),
            "on_time_days": on_time_days,
            "commitment_score": commitment_score
        }
    return summary




def generate_final_employee_report(df):
    df['transaction_date'] = df['Creation Date'].dt.date

    all_branch_days = sorted(df['transaction_date'].unique())
    total_branch_days = len(all_branch_days)

    days_worked = df.groupby('Operator Id')['transaction_date'].nunique().reset_index(name='أيام_العمل')

    work_time = df.groupby(['Operator Id', 'transaction_date'])['Creation Date'].agg(['min', 'max']).reset_index()
    work_time['ساعات_اليوم'] = (work_time['max'] - work_time['min']).dt.total_seconds() / 3600

    total_hours = work_time.groupby('Operator Id')['ساعات_اليوم'].sum().reset_index(name='إجمالي_الساعات')

    report = days_worked.merge(total_hours, on='Operator Id')
    report['أيام_الغياب'] = total_branch_days - report['أيام_العمل']

    report['عدد_التحويلات'] = df.groupby('Operator Id').size().reindex(report['Operator Id']).fillna(0).astype(int).values
    report['عدد_الحوالات_في_الساعة'] = (report['عدد_التحويلات'] / report['إجمالي_الساعات'].replace(0, 1)).round().astype(int)
    report['متوسط_السرعة_في_الساعة'] = ((report['إجمالي_الساعات'] * 60) / report['عدد_التحويلات'].replace(0, 1)).round().astype(int)

    total_branch_transfers = report['عدد_التحويلات'].sum()
    report['نسبة_التحويلات'] = ((report['عدد_التحويلات'] / total_branch_transfers) * 100).round().astype(int)

    final = report.rename(columns={
        'Operator Id': 'الموظف',
        'إجمالي_الساعات': 'إجمالي ساعات العمل'
    })[[
        'الموظف',
        'عدد_التحويلات',
        'نسبة_التحويلات',
        'عدد_الحوالات_في_الساعة',
        'متوسط_السرعة_في_الساعة',
        'أيام_العمل',
        'إجمالي ساعات العمل',
        'أيام_الغياب'
    ]]

    return final






def client_behavior_report(df):
    report = {}

    top_receivers = df["Receiver Name - WU"].value_counts().head(10)
    report["top_receivers_by_count"] = df[df["Receiver Name - WU"].isin(top_receivers.index)]

    top_amounts = df.groupby("Receiver Name - WU")["Actual Payout Amount"].sum().sort_values(ascending=False).head(10)
    report["top_receivers_by_amount"] = df[df["Receiver Name - WU"].isin(top_amounts.index)]

    sender_counts = df.groupby("Receiver Name - WU")["Sender Full Name"].nunique()
    multiple_senders = sender_counts[sender_counts > 3].index
    report["receivers_with_multiple_senders"] = df[df["Receiver Name - WU"].isin(multiple_senders)]

    combo_clients = set(top_receivers.index) & set(top_amounts.index) & set(multiple_senders)
    report["flagged_clients"] = df[df["Receiver Name - WU"].isin(combo_clients)]

    report["sender_name_classification"] = df["Name Classification"].value_counts().reset_index()
    report["sender_name_classification"].columns = ["تصنيف الاسم", "العدد"]

    return report

# ==================== Streamlit ====================

st.set_page_config(layout="wide")
st.markdown("""
    <h1 style='text-align: right;'>لوحة تحكم أداء الفرع والموظفين</h1>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("📂 ارفع ملف Excel", type="xlsx")

if uploaded_file:
    df = prepare_data(uploaded_file)
    branch_report = branch_summary(df)
    employee_report = employee_summary(df)
    client_report = client_behavior_report(df)
    final_emp_report = generate_final_employee_report(df)
    downtime_report = calculate_system_downtime(df)
    avg_peak_wait = calculate_peak_waiting_time(df)





    
    st.subheader("📈 تقرير الأداء التفصيلي")
    st.dataframe(final_emp_report, use_container_width=True)

    st.subheader("🛑 تقرير توقف السيستم")
    st.dataframe(downtime_report, use_container_width=True)

    st.metric("⏱️ متوسط وقت انتظار العملاء (فعليًا) في أيام الذروة", f"{avg_peak_wait} دقيقة")


    
    st.markdown("""<h2 style='text-align: right;'>🏅 الموظف المثالي</h2>""", unsafe_allow_html=True)
    emp_df = pd.DataFrame.from_dict(employee_report, orient="index").reset_index().rename(columns={"index": "اسم الموظف"})
    emp_df = emp_df.rename(columns={
        "unique_clients": "عدد العملاء",
        "total_transfers": "عدد التحويلات",
        "total_amount": "إجمالي المبلغ",
        "over_limit_transfers": "تحويلات Over Limit",
        "working_days": "أيام العمل",
        "total_hours_worked": "ساعات العمل",
        "avg_speed": "متوسط السرعة",
        "high_volume_days": "أيام النشاط العالي",
        "on_time_days": "أيام الالتزام",
        "commitment_score": "نقاط الالتزام"
    })

    emp_df["مؤشر الأداء"] = (
        emp_df["عدد العملاء"] * 0.10 +
        emp_df["عدد التحويلات"] * 0.25 +
        emp_df["إجمالي المبلغ"] * 0.10 +
        emp_df["نقاط الالتزام"] * 0.25 +
        emp_df["أيام النشاط العالي"] * 0.15 -
        emp_df["متوسط السرعة"] * 0.05
    )
    ideal_emp = emp_df.sort_values("مؤشر الأداء", ascending=False).iloc[0]
    st.success(f"✨ {ideal_emp['اسم الموظف']} هو الموظف المثالي بناءً على الأداء العام")
    st.dataframe(emp_df.sort_values("مؤشر الأداء", ascending=False), use_container_width=True)

    st.markdown("""<h2 style='text-align: right;'>🏢 تقرير الفرع</h2>""", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    col1.metric("عدد عملاء الفرع", branch_report["unique_customers"])
    col2.metric("إجمالي عدد التحويلات", branch_report["total_transfers"])

    with st.expander("📊 التحويلات حسب النظام"):
        system_df = pd.DataFrame(branch_report["transfers_by_system"].items(), columns=["النظام", "عدد التحويلات"])
        st.dataframe(system_df.style.set_table_styles([{ 'selector': 'th', 'props': [('text-align', 'right')] }]), use_container_width=True)

    st.markdown("#### أعلى 5 دول مرسلة")
    countries_df = pd.DataFrame(branch_report["top_5_senders"].items(), columns=["الدولة", "عدد التحويلات"])
    st.dataframe(countries_df)

    st.markdown(f"### 💰 إجمالي المبلغ المدفوع: **{branch_report['total_amount']:.2f} دولار**")

    st.markdown("""<h2 style='text-align: right;'>👤 تحليل العملاء</h2>""", unsafe_allow_html=True)
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["ذو مخاطر عالية", "الأكثر استلامًا", "الأعلى مبالغ", "أكثر من 3 راسلين", "تشابه الأسماء", "تصنيف أسماء الراسلين"])

    with tab1:
        flagged = client_report["flagged_clients"]
        flagged_summary = flagged.groupby("Receiver Name - WU").agg({
            "Actual Payout Amount": "sum",
            "Sender Full Name": pd.Series.nunique,
            "MTCN": "count"
        }).reset_index().rename(columns={
            "Receiver Name - WU": "اسم العميل",
            "Actual Payout Amount": "إجمالي المبلغ",
            "Sender Full Name": "عدد الراسلين",
            "MTCN": "عدد التحويلات"
        })
        st.dataframe(flagged_summary, use_container_width=True)

    with tab2:
        count_df = df.groupby("Receiver Name - WU").agg({"MTCN": "count"}).reset_index()
        count_df = count_df.rename(columns={"Receiver Name - WU": "اسم العميل", "MTCN": "عدد التحويلات"})
        st.dataframe(count_df.sort_values("عدد التحويلات", ascending=False), use_container_width=True)

    with tab3:
        amount_df = df.groupby("Receiver Name - WU").agg({"Actual Payout Amount": "sum", "MTCN": "count"}).reset_index()
        amount_df = amount_df.rename(columns={"Receiver Name - WU": "اسم العميل", "Actual Payout Amount": "إجمالي المبلغ", "MTCN": "عدد التحويلات"})
        st.dataframe(amount_df.sort_values("إجمالي المبلغ", ascending=False), use_container_width=True)

    with tab4:
        multi_df = df.groupby("Receiver Name - WU").agg({"Sender Full Name": pd.Series.nunique, "Actual Payout Amount": "sum"}).reset_index()
        multi_df = multi_df[multi_df["Sender Full Name"] > 1].rename(columns={
            "Receiver Name - WU": "اسم العميل",
            "Sender Full Name": "عدد الراسلين",
            "Actual Payout Amount": "إجمالي المبلغ"
        })
        st.dataframe(multi_df.sort_values("عدد الراسلين", ascending=False), use_container_width=True)

    with tab5:
        similarity_options = df["Name Match Category"].unique().tolist()
        selected_similarities = st.multiselect("اختر نوع التشابه", similarity_options)
        filtered_similarity_df = df[df["Name Match Category"].isin(selected_similarities)] if selected_similarities else df
        st.dataframe(filtered_similarity_df[["Receiver Name - WU", "Receiver Name - IBAG", "Similarity (%)", "Name Match Category", "Sender Full Name"]], use_container_width=True)

    with tab6:
        st.dataframe(client_report["sender_name_classification"], use_container_width=True)

    st.markdown("#### 📅 فلترة حسب أيام التحويل وعدد العمليات")
    day_stats = df.groupby(["transaction_date", "day_of_week"]).agg({"MTCN": "count", "Operator Id": pd.Series.nunique}).reset_index()
    day_stats = day_stats.rename(columns={"transaction_date": "تاريخ", "day_of_week": "اليوم", "MTCN": "عدد التحويلات", "Operator Id": "عدد الموظفين"})

    category = st.selectbox("اختر فئة اليوم", ["أقل من 200", "من 200 إلى 250", "من 250 إلى 300", "أكثر من 300"])

    if category == "أقل من 200":
        filtered_days = day_stats[day_stats["عدد التحويلات"] < 200]
    elif category == "من 200 إلى 250":
        filtered_days = day_stats[(day_stats["عدد التحويلات"] >= 200) & (day_stats["عدد التحويلات"] <= 250)]
    elif category == "من 250 إلى 300":
        filtered_days = day_stats[(day_stats["عدد التحويلات"] > 250) & (day_stats["عدد التحويلات"] <= 300)]
    else:
        filtered_days = day_stats[day_stats["عدد التحويلات"] > 300]

    st.dataframe(filtered_days, use_container_width=True)

else:
    st.warning("يرجى رفع ملف البيانات للبدء بالتحليل.")
