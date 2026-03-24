import streamlit as st
import pandas as pd
from sqlalchemy import text
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta

# --- MAKE THE APP WIDE ---
st.set_page_config(page_title="Inventory & Sales Tracker", layout="wide")

# --- MAGIC CSS: HOVER ZOOM EFFECT FOR IMAGES ---
st.markdown("""
<style>
[data-testid="stImage"] img {
    transition: transform 0.3s ease;
    cursor: zoom-in;
    border-radius: 8px;
}
[data-testid="stImage"] img:hover {
    transform: scale(2.0);
    z-index: 9999;
    position: relative;
    box-shadow: 0px 10px 30px rgba(0,0,0,0.5);
}
</style>
""", unsafe_allow_html=True)

# --- DATABASE SETUP (SUPABASE CLOUD) ---
# This securely grabs the secret key we put in your secrets.toml file!
DB_URL = st.secrets["DATABASE_URL"]
engine = create_engine(DB_URL)

def init_db():
    with engine.begin() as conn:
        conn.execute(text('''CREATE TABLE IF NOT EXISTS inventory
                     (date TEXT, unique_id TEXT, name TEXT, image TEXT, url TEXT, inventory INTEGER, price REAL)'''))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS daily_sales
                     (date TEXT, unique_id TEXT, name TEXT, image TEXT, sales_qty INTEGER, price REAL, revenue REAL, status TEXT)'''))

init_db()

# ==========================================
# PAGE 2: PRODUCT DETAILS REPORT (NEW TAB)
# ==========================================
if "sku" in st.query_params:
    sku = st.query_params["sku"]
    
    if st.button("⬅️ Back to Main Dashboard"):
        st.query_params.clear()
        st.rerun()
        
    st.title("📦 Product Data Report")
    
    latest_info = pd.read_sql(f"SELECT * FROM inventory WHERE unique_id = '{sku}' AND image IS NOT NULL AND image != '' ORDER BY date DESC LIMIT 1", engine)
    
    if latest_info.empty:
         latest_info = pd.read_sql(f"SELECT * FROM inventory WHERE unique_id = '{sku}' ORDER BY date DESC LIMIT 1", engine)

    if not latest_info.empty:
        info = latest_info.iloc[0]
        col_img, col_details = st.columns([1, 3])
        with col_img:
            if info['image']:
                st.image(info['image'], use_container_width=True)
            else:
                st.info("No Image Available")
                
        with col_details:
            st.markdown(f"### [{info['name']}]({info['url']})")
            st.write(f"**SKU:** {sku}")
            
            converted_price = info['price'] * 3.66
            st.write(f"**Current Price:** AED {converted_price:,.2f}")
            st.write(f"**Current Inventory:** {int(info['inventory'])} units remaining")
            
        st.divider()
        st.subheader("📈 Sales History")
        
        default_end = datetime.now().date()
        default_start = default_end - timedelta(days=30) 
        
        col_sd, col_ed = st.columns(2)
        with col_sd:
            p_start = st.date_input("Start Date", default_start, key="p_start")
        with col_ed:
            p_end = st.date_input("End Date", default_end, key="p_end")
            
        sales_history = pd.read_sql(f"SELECT date, sales_qty FROM daily_sales WHERE unique_id = '{sku}' AND date >= '{p_start}' AND date <= '{p_end}' ORDER BY date", engine)
        
        if not sales_history.empty:
            sales_history.set_index('date', inplace=True)
            st.line_chart(sales_history['sales_qty'], y_label="Units Sold")
        else:
            st.info("No sales data found for this date range.")
    else:
        st.error("Product not found in database.")

# ==========================================
# PAGE 1: MAIN DASHBOARD
# ==========================================
else:
    st.title("🛍️ Daily Inventory & Sales Tracker")

    # --- SIDEBAR: BULK UPLOAD ---
    st.sidebar.header("1. Upload Daily Data")
    uploaded_files = st.sidebar.file_uploader("Upload Excel/CSV Files", type=['csv', 'xlsx'], accept_multiple_files=True)

    if uploaded_files:
        if st.sidebar.button("Process Uploaded Files"):
            with st.spinner("Analyzing and syncing to Supabase..."):
                all_data = []
                
                for file in uploaded_files:
                    if file.name.endswith('.csv'):
                        df = pd.read_csv(file)
                    else:
                        df = pd.read_excel(file)
                        
                    if 'DateTime Extracted' not in df.columns:
                        file.seek(0)
                        if file.name.endswith('.csv'):
                            df = pd.read_csv(file, header=None)
                        else:
                            df = pd.read_excel(file, header=None)
                            
                        if len(df.columns) >= 7:
                            df = df.iloc[:, :7]
                            df.columns = ['DateTime Extracted', 'Name', 'Sku', 'Image', 'Url', 'inventory Amount', 'Price']
                        elif len(df.columns) == 6:
                            df.columns = ['DateTime Extracted', 'Name', 'Sku', 'Url', 'inventory Amount', 'Price']

                    if 'Image' not in df.columns:
                        df['Image'] = None
                        
                    df['inventory Amount'] = pd.to_numeric(df['inventory Amount'], errors='coerce').fillna(0).astype(int)
                    df['Price'] = pd.to_numeric(df['Price'], errors='coerce').fillna(0.0)

                    all_data.append(df)
                
                combined_df = pd.concat(all_data, ignore_index=True)
                
                combined_df['Sku'] = combined_df['Sku'].fillna(combined_df['Url'])
                combined_df = combined_df.rename(columns={'Sku': 'unique_id', 'inventory Amount': 'inventory'})
                combined_df = combined_df.dropna(subset=['unique_id'])
                
                combined_df['date'] = pd.to_datetime(combined_df['DateTime Extracted'], format='mixed', errors='coerce').dt.strftime('%Y-%m-%d')
                combined_df = combined_df.dropna(subset=['date'])
                
                unique_dates = sorted(combined_df['date'].unique())
                st.sidebar.write(f"Found data for these dates: {', '.join(unique_dates)}")
                
                for process_date in unique_dates:
                    existing_data = pd.read_sql(f"SELECT COUNT(*) as cnt FROM inventory WHERE date = '{process_date}'", engine)
                    
                    if existing_data['cnt'][0] > 0:
                        st.sidebar.warning(f"Skipped {process_date}: Data already calculated.")
                        continue 
                    
                    df_day = combined_df[combined_df['date'] == process_date].copy()
                    df_day = df_day.drop_duplicates(subset=['unique_id'], keep='last')
                    
                    df_to_save = df_day[['date', 'unique_id', 'Name', 'Image', 'Url', 'inventory', 'Price']].copy()
                    df_to_save.rename(columns={'Name': 'name', 'Image': 'image', 'Url': 'url', 'Price': 'price'}, inplace=True)
                    df_to_save.to_sql('inventory', engine, if_exists='append', index=False)
                    
                    yesterday_df = pd.read_sql(f"SELECT unique_id, inventory as yesterday_inv FROM inventory WHERE date < '{process_date}' ORDER BY date DESC", engine)
                    yesterday_df = yesterday_df.drop_duplicates(subset=['unique_id'])
                    
                    if not yesterday_df.empty:
                        merged = pd.merge(df_to_save, yesterday_df, on='unique_id', how='left')
                        merged['yesterday_inv'] = merged['yesterday_inv'].fillna(merged['inventory']).astype(int)
                        merged['inventory'] = merged['inventory'].astype(int)
                        
                        def calc_sales(row):
                            if row['yesterday_inv'] > row['inventory']:
                                return int(row['yesterday_inv'] - row['inventory']), ""
                            elif row['inventory'] > row['yesterday_inv']:
                                return 0, "Restocked"
                            else:
                                return 0, ""
                        
                        merged[['sales_qty', 'status']] = merged.apply(calc_sales, axis=1, result_type='expand')
                        merged['revenue'] = merged['sales_qty'] * merged['price']
                        
                        sales_to_save = merged[['date', 'unique_id', 'name', 'image', 'sales_qty', 'price', 'revenue', 'status']]
                        sales_to_save.to_sql('daily_sales', engine, if_exists='append', index=False)
                        st.sidebar.success(f"Successfully processed sales for {process_date}!")
                    else:
                        st.sidebar.info(f"Processed {process_date} (First baseline set).")

    # --- MAIN DASHBOARD: REPORTING ---
    st.header("2. Sales Reports")

    if "start_date" not in st.session_state:
        st.session_state.start_date = datetime.now().date()
    if "end_date" not in st.session_state:
        st.session_state.end_date = datetime.now().date()

    # --- QUICK FILTER BUTTONS ---
    today = datetime.now().date()
    
    b1, b2, b3, b4, b5, b6, b7, b8 = st.columns(8)
    
    if b1.button("Today", use_container_width=True):
        st.session_state.start_date = today
        st.session_state.end_date = today
        st.rerun()
    if b2.button("Yesterday", use_container_width=True):
        st.session_state.start_date = today - timedelta(days=1)
        st.session_state.end_date = today - timedelta(days=1)
        st.rerun()
    if b3.button("Last 7 Days", use_container_width=True):
        st.session_state.start_date = today - timedelta(days=7)
        st.session_state.end_date = today
        st.rerun()
    if b4.button("Last 14 Days", use_container_width=True):
        st.session_state.start_date = today - timedelta(days=14)
        st.session_state.end_date = today
        st.rerun()
    if b5.button("Last 30 Days", use_container_width=True):
        st.session_state.start_date = today - timedelta(days=30)
        st.session_state.end_date = today
        st.rerun()
    if b6.button("This Month", use_container_width=True):
        st.session_state.start_date = today.replace(day=1)
        st.session_state.end_date = today
        st.rerun()
    if b7.button("Last Month", use_container_width=True):
        first_day_of_this_month = today.replace(day=1)
        last_day_of_last_month = first_day_of_this_month - timedelta(days=1)
        first_day_of_last_month = last_day_of_last_month.replace(day=1)
        st.session_state.start_date = first_day_of_last_month
        st.session_state.end_date = last_day_of_last_month
        st.rerun()
        
    if b8.button("All Time", use_container_width=True):
        min_date_query = pd.read_sql("SELECT MIN(date) as min_date FROM daily_sales", engine)
        if min_date_query['min_date'][0]: 
            first_recorded_date = datetime.strptime(min_date_query['min_date'][0], '%Y-%m-%d').date()
            st.session_state.start_date = first_recorded_date
        else: 
            st.session_state.start_date = today - timedelta(days=365)
            
        st.session_state.end_date = today
        st.rerun()

    st.write("---")

    # --- CALENDAR INPUTS ---
    col_back, col_start, col_end, col_fwd = st.columns([1, 2, 2, 1])
    
    with col_back:
        st.write("") 
        st.write("")
        if st.button("⬅️ Prev Day", use_container_width=True):
            st.session_state.start_date -= timedelta(days=1)
            st.session_state.end_date -= timedelta(days=1)
            st.rerun()
            
    with col_start:
        st.session_state.start_date = st.date_input("Start Date", st.session_state.start_date)
    with col_end:
        st.session_state.end_date = st.date_input("End Date", st.session_state.end_date)
        
    with col_fwd:
        st.write("") 
        st.write("")
        if st.button("Next Day ➡️", use_container_width=True):
            st.session_state.start_date += timedelta(days=1)
            st.session_state.end_date += timedelta(days=1)
            st.rerun()

    # --- QUERY AND DISPLAY TABLE (Postgres uses STRING_AGG instead of GROUP_CONCAT) ---
    query = f"""
    WITH RankedInventory AS (
        SELECT unique_id, price as current_price, url, image,
               ROW_NUMBER() OVER(PARTITION BY unique_id ORDER BY date DESC) as rn
        FROM inventory
        WHERE date <= '{st.session_state.end_date}'
    )
    SELECT 
        r.image,
        d.name,
        r.url,
        d.unique_id,
        SUM(d.sales_qty) as total_units_sold,
        (r.current_price * 3.66) as current_price_aed,
        SUM(d.revenue * 3.66) as total_revenue_aed,
        STRING_AGG(DISTINCT d.status, ', ') as notes
    FROM daily_sales d
    LEFT JOIN (SELECT * FROM RankedInventory WHERE rn = 1) r ON d.unique_id = r.unique_id
    WHERE d.date >= '{st.session_state.start_date}' AND d.date <= '{st.session_state.end_date}'
    GROUP BY d.unique_id, d.name, r.image, r.url, r.current_price
    HAVING SUM(d.sales_qty) > 0 OR STRING_AGG(DISTINCT d.status, ', ') LIKE '%Restocked%'
    ORDER BY SUM(d.sales_qty) DESC, SUM(d.revenue * 3.66) DESC
    """
    
    with engine.connect() as conn:
        report_df = pd.read_sql(text(query), con=conn)
    
    if report_df.empty:
        st.info("No sales or restock data found for this date range.")
    else:
        report_df['product_data'] = '/?sku=' + report_df['unique_id']
        
        total_rev = report_df['total_revenue_aed'].sum()
        total_units = report_df['total_units_sold'].sum()
        avg_sale_price = total_rev / total_units if total_units > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        col1.metric(f"Total Revenue ({st.session_state.start_date.strftime('%b %d')} - {st.session_state.end_date.strftime('%b %d')})", f"AED {total_rev:,.2f}")
        col2.metric("Total Units Sold", f"{total_units:,.0f}")
        col3.metric("Average Sale Price", f"AED {avg_sale_price:,.2f}")
        
        st.write("---")
        
        if total_units > 0:
            st.subheader("🏆 Top 10 Sellers")
            top_10_df = report_df.head(10)
            
            cols = st.columns(5)
            for index, row in top_10_df.reset_index().iterrows():
                with cols[index % 5]:
                    if row['image']:
                        st.image(row['image'], use_container_width=True)
                    else:
                        st.info("No Image")
                    
                    short_name = row['name'][:40] + "..." if len(row['name']) > 40 else row['name']
                    st.markdown(f"**[{short_name}]({row['url']})**")
                    st.markdown(f"📦 **{row['total_units_sold']:,.0f} Sold**")
                    st.markdown(f"💰 AED {row['total_revenue_aed']:,.2f}")
                    st.write("") 
            
            st.write("---")
        
        st.subheader("📋 Complete Sales Data")
        
        # Clean up any missing notes
        report_df['notes'] = report_df['notes'].fillna('')
        
        display_df = report_df[['image', 'name', 'url', 'product_data', 'total_units_sold', 'current_price_aed', 'total_revenue_aed', 'notes']]
        
        st.dataframe(
            display_df,
            column_config={
                "image": st.column_config.ImageColumn("Image"),
                "name": "Product Name",
                "url": st.column_config.LinkColumn("Store Link", display_text="🛍️ View on Store"),
                "product_data": st.column_config.LinkColumn("Product Data", display_text="📊 View Data"),
                "total_units_sold": st.column_config.NumberColumn("Units Sold", format="%d"),
                "current_price_aed": st.column_config.NumberColumn("Current Price", format="AED %.2f"),
                "total_revenue_aed": st.column_config.NumberColumn("Total Revenue", format="AED %.2f"),
                "notes": "Notes"
            },
            hide_index=True,
            use_container_width=True
        )
