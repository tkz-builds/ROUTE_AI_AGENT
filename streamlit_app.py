import streamlit as st
import pandas as pd
import os
from io import BytesIO
import base64
import streamlit.components.v1 as components

from route_optimizer import optimize_routes

st.set_page_config(page_title="Logistics Optimization", layout="wide")
st.title("🚚 Logistics Optimization Dashboard")
st.markdown("Upload your data files and hit **Run Optimization** to compute routes.")

# Sidebar inputs
with st.sidebar:
    st.header("⚙️ Settings")
    speed_factor    = st.number_input("Speed Factor (km/h)", 0.5, 100.0, 30.0, 0.1)
    search_strategy = st.selectbox("Search Strategy",
        ["PATH_CHEAPEST_ARC", "GLOBAL_CHEAPEST_ARC", "LOCAL_CHEAPEST_ARC"]
    )
    email_enabled   = st.checkbox("Enable Email Delivery", value=False)

    up_warehouses = st.file_uploader("Warehouse Data (.csv/.xlsx)", type=["csv","xlsx"])
    up_vehicles   = st.file_uploader("Vehicle Data (.csv/.xlsx)", type=["csv","xlsx"])
    up_drivers    = st.file_uploader("Driver Data (.csv/.xlsx)", type=["csv","xlsx"])
    up_emails     = (
        st.file_uploader("Emails (.xlsx)", type=["xlsx"])
        if email_enabled else None
    )

def load_df(u, name):
    if not u:
        st.error(f"Please upload {name} data.")
        return None
    try:
        return pd.read_csv(u) if u.name.endswith(".csv") else pd.read_excel(u)
    except Exception as e:
        st.error(f"Error loading {name}: {e}")
        return None

def download_link(path, label):
    b = base64.b64encode(open(path,"rb").read()).decode()
    return f'<a href="data:application/octet-stream;base64,{b}" download="{os.path.basename(path)}">{label}</a>'

# Main
if up_warehouses:
    df_wh = load_df(up_warehouses, "Warehouse")
    if df_wh is not None:
        st.subheader("📍 Warehouses")
        st.dataframe(df_wh)

        if up_vehicles and up_drivers:
            df_v  = load_df(up_vehicles, "Vehicle")
            df_d  = load_df(up_drivers,  "Driver")

            if df_v is not None and df_d is not None:
                st.subheader("🚚 Vehicles")
                st.dataframe(df_v)
                st.subheader("🧑‍✈️ Drivers")
                st.dataframe(df_d)

                if st.button("Run Optimization"):
                    try:
                        # Validate columns
                        need_wh = ["Warehouse Name","latitude","longitude",
                                   "demand","service_time","start_time","end_time","priority"]
                        if not all(c in df_wh.columns for c in need_wh):
                            raise ValueError(f"Warehouse data must contain {need_wh}")
                        if not all(c in df_v.columns for c in ["type","capacity"]):
                            raise ValueError("Vehicle data must contain ['type','capacity']")
                        if not all(c in df_d.columns for c in ["driver_id","start_time","end_time"]):
                            raise ValueError("Driver data must contain ['driver_id','start_time','end_time']")

                        with st.spinner("🔄 Optimizing routes…"):
                            routes, map_file = optimize_routes(
                                df_wh.copy(), df_v.copy(), df_d.copy(),
                                speed_factor, search_strategy
                            )

                        st.success("✅ Routes optimized!")

                        # Display map
                        st.subheader("🗺 Route Map")
                        html = open(map_file,"r").read()
                        components.html(html, height=600, scrolling=True)
                        st.markdown(download_link(map_file, "📥 Download Map"), unsafe_allow_html=True)

                        # Display route sheets
                        st.subheader("📄 Route Sheets")
                        for i, r in enumerate(routes):
                            df_r = pd.DataFrame({"Stop": r})
                            st.markdown(f"**Vehicle {df_v.type.iloc[i]}**")
                            st.dataframe(df_r)
                            buf = BytesIO()
                            df_r.to_excel(buf, index=False)
                            buf.seek(0)
                            st.download_button(
                                f"Download Vehicle {df_v.type.iloc[i]} Route",
                                buf, file_name=f"vehicle_{df_v.type.iloc[i]}_route.xlsx"
                            )

                        # Email block (stub)
                        if email_enabled and up_emails:
                            df_e = load_df(up_emails, "Emails")
                            if df_e is not None and "email" in df_e.columns:
                                st.warning("Email sending disabled in this demo.")
                            else:
                                st.error("Emails file needs an 'email' column.")

                    except Exception as e:
                        st.error(f"Error: {e}")

            else:
                st.warning("Upload both vehicle and driver files.")
        else:
            st.info("Please upload vehicle & driver data.")
else:
    st.info("Please upload warehouse data to get started.")