import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from datetime import time
from rapidfuzz import fuzz

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

def generate_final_employee_report(df):
    df['transaction_date'] = df['Creation Date'].dt.date

    days_worked = df.groupby('Operator Id')['transaction_date'].nunique().reset_index(name='أيام_العمل')

    work_time = df.groupby(['Operator Id', 'transaction_date'])['Creation Date'].agg(['min', 'max']).reset_index()
    work_time['ساعات_اليوم'] = (work_time['max'] - work_time['min']).dt.total_seconds() / 3600

    total_hours = work_time.groupby('Operator Id')['ساعات_اليوم'].sum().reset_index(name='إجمالي_الساعات')

    all_dates = pd.date_range(start=df['transaction_date'].min(), end=df['transaction_date'].max(), freq='D')
    work_days = all_dates[all_dates.dayofweek < 5]
    expected = pd.DataFrame({'Operator Id': df['Operator Id'].unique()})
    expected['عدد_أيام_العمل_المتوقعة'] = len(work_days)

    report = days_worked.merge(total_hours, on='Operator Id')
    report = report.merge(expected, on='Operator Id')
    report['أيام_الغياب'] = report['عدد_أيام_العمل_المتوقعة'] - report['أيام_العمل']

    report['عدد_التحويلات'] = df.groupby('Operator Id').size().reindex(report['Operator Id']).values
    report['عدد_الحوالات_في_الساعة'] = round(report['عدد_التحويلات'] / report['إجمالي_الساعات'].replace(0, 1), 2)
    report['متوسط_السرعة_في_الساعة'] = round((report['إجمالي_الساعات'] * 60) / report['عدد_التحويلات'].replace(0, 1), 2)

    final = report.rename(columns={
        'Operator Id': 'الموظف',
        'إجمالي_الساعات': 'إجمالي ساعات العمل'
    })[[
        'الموظف',
        'عدد_التحويلات',
        'عدد_الحوالات_في_الساعة',
        'متوسط_السرعة_في_الساعة',
        'أيام_العمل',
        'إجمالي ساعات العمل',
        'أيام_الغياب'
    ]]

    return final

# ==================== Streamlit ====================

st.set_page_config(layout="wide")
st.title("📊 تقرير أداء الموظفين")

uploaded_file = st.file_uploader("📂 ارفع ملف البيانات (Excel)", type=["xlsx", "xls"])

if uploaded_file:
    df = prepare_data(uploaded_file)
    final_emp_report = generate_final_employee_report(df)

    st.subheader("📈 التقرير التفصيلي")
    st.dataframe(final_emp_report, use_container_width=True)
else:
    st.warning("يرجى رفع ملف البيانات للبدء بالتحليل.")
