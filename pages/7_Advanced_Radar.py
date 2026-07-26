import streamlit as st
import pandas as pd
from sqlmodel import Session, select
from src.models import Transaction
from src.utils import get_db_engine, parse_occ_type_and_strike, get_days_to_expiration, parse_occ_expiration
from src.schwab_aw_api import get_quotes

engine = get_db_engine()

st.title("📡 Advanced Radar")
st.markdown("---")

tab_threats, tab_ops = st.tabs(["⚠️ Threats (Danger Zone)", "🎯 Opportunities (Scanners)"])

# ==========================================
# TAB 1: THREATS (THE DANGER ZONE)
# ==========================================
with tab_threats:
    st.subheader("Active Position Risk Radar")
    st.write("Highlights open option legs where the live stock price is dangerously close to your strike, but still actionable.")
    
    with Session(engine) as session:
        option_txs = session.exec(select(Transaction).where(Transaction.asset_type == "OPTION")).all()
        
        open_positions = {}
        for tx in option_txs:
            sym = tx.full_symbol
            if sym not in open_positions:
                open_positions[sym] = {"qty": 0.0, "root": tx.root_ticker}
            open_positions[sym]["qty"] += tx.quantity
            
        active_options = {sym: data for sym, data in open_positions.items() if round(data["qty"], 2) != 0}
        
        if not active_options:
            st.success("No active options contracts found in the database.")
        else:
            unique_roots = list(set([data["root"] for data in active_options.values()]))
            
            with st.spinner("Fetching live market data for threat analysis..."):
                try:
                    market_data = get_quotes(unique_roots)
                except Exception:
                    market_data = {}
                    st.error("Failed to fetch live prices from Schwab API.")

            threat_data = []
            
            for sym, data in active_options.items():
                qty = data["qty"]
                root = data["root"]
                opt_type, strike = parse_occ_type_and_strike(sym)
                exp_date = parse_occ_expiration(sym)
                dte = get_days_to_expiration(exp_date)
                
                if not strike or dte < 0:
                    continue
                    
                strike = float(strike)
                quote_info = market_data.get(root, {})
                current_price = quote_info.get("mark")
                
                if current_price:
                    if opt_type == 'P':
                        distance_pct = (current_price - strike) / current_price
                    else: 
                        distance_pct = (strike - current_price) / current_price
                    
                    if qty < 0:
                        if -0.10 <= distance_pct <= 0.05:
                            is_itm = distance_pct < 0
                            status = "🚨 Action Required (ITM)" if is_itm else "⚠️ Testing (Within 5%)"
                            
                            threat_data.append({
                                "Status": status,
                                "Symbol": root,
                                "Option": "Put" if opt_type == 'P' else "Call",
                                "Strike": strike,
                                "Live Price": current_price,
                                "Dist to Strike": f"{distance_pct * 100:.2f}%",
                                "DTE": dte
                            })

            if threat_data:
                df_threats = pd.DataFrame(threat_data).sort_values(by="Dist to Strike")
                st.dataframe(
                    df_threats,
                    column_config={
                        "Strike": st.column_config.NumberColumn(format="$%.2f"),
                        "Live Price": st.column_config.NumberColumn(format="$%.2f")
                    },
                    hide_index=True,
                    use_container_width=True
                )
            else:
                st.success("All clear! No short positions are currently testing their strikes (or they are too far gone to manage).")

# ==========================================
# TAB 2: OPPORTUNITIES & WATCHLISTS
# ==========================================
with tab_ops:
    st.subheader("Market Extremes Scanner")
    st.write("Find beaten-down stocks. When price hits the 52-week low, Implied Volatility usually spikes, making Puts expensive to buy but highly profitable to sell.")
    
    # Master dictionary of all AI, Nuclear, Space, Defense, and Shipping thematic lists
    THEMATIC_LISTS = {
        "My Custom List": "SPY, QQQ, IWM",
        
        # --- Nuclear Renaissance ---
        "Nuke: Miners & Fuel": "CCJ, UEC, UUUU, EU, URG, NXE, UROY, LEU, ASPI",
        "Nuke: SMRs & Tech": "SMR, OKLO, NNE, RYCEY",
        "Nuke: Picks & Shovels": "BWXT, CW, CR, EMR, FLS, BBU, GEV, ATI, CRS",
        "Nuke: Construction & Grid": "FLR, PWR, CAT",
        "Nuke: Utilities (Outputs)": "CEG, VST, TLN, NEE, D",
        
        # --- Space Economy ---
        "Space: Launch & Vehicles": "RKLB, SPCE, MNTS, SPCX",
        "Space: Satellites & Data": "ASTS, PL, LUNR, BKSY, GSAT, IRDM, SATS",
        "Space: Primes & ETFs": "LMT, NOC, BA, UFO, ARKX, ROKT",
        
        # --- Defense & Aerospace ---
        "Defense: Next-Gen & Tech": "PLTR, KTOS, AVAV",
        "Defense: The Primes": "LMT, RTX, GD, NOC, HII",
        "Defense: Parts & Systems": "TDG, TDY, SPR",
        
        # --- Global Shipping & Offshore ---
        "Shipping: Containers": "ZIM, DAC, GSL, MATX",
        "Shipping: Tankers (Oil)": "DHT, FRO, STNG, EURN, TNP",
        "Shipping: Dry Bulk": "SBLK, GOGL, EGLE, DSX",
        "Offshore: Drillers": "RIG, VAL, SDRL, NE, DO",
        
        # --- AI Infrastructure ---
        "AI: Edge Delivery": "AKAM, FSLY, NET",
        "AI: Hyperscalers": "MSFT, GOOG, AMZN, META",
        "AI: GPU Cloud & Pivots": "IREN, CIFR, WULF, APLD, CRWV, NBIS, ORCL, DOCN",
        "AI: Data Center REITs": "EQIX, DLR, IRM",
        "AI: Chip Design Ecosystem": "SNPS, CDNS, ARM, RMBS, NVDA, AVGO, MRVL, AMD, INTC, QCOM, LSCC",
        "AI: Semiconductor Mfg": "ASML, LRCX, KLAC, AMAT, ENTG, CAMT, ONTO, PLAB, NVMI, ACMR, KLIC, UCTT, ICHR, SOLS, TSM, GFS, UMC, TSEM, MU, SNDK, WDC, STX, P, NTAP, AMKR, ASX, KEYS, TER, AEHR, VIAV",
        "AI: Electrical Connectivity": "APH, TEL, CRDO, ALAB, SITM, SMTC, EXTR, TTMI",
        "AI: Optical & Fiber": "LITE, COHR, FN, GLW, MTSI, CIEN, AAOI",
        "AI: Networking Hardware": "ANET, CSCO",
        "AI: Rack Assembly / OEM": "HNHPF, JBL, CLS, DELL, HPE, SMCI",
        "AI: Power and Cooling": "VRT, MOD, ETN, NVT, CARR, TT, JCI, SPXC, SBGSY, XYL, VICR, ECL, CC, ENS, GNRC, CMI, CAT",
        "AI: Power Semiconductors": "TXN, ON, ADI, MCHP, MPWR, WOLF, LFUS",
        "AI: Data Center Construction": "EME, FIX, DY, HUBB, MYRG, PRIM, MTZ, STRL, IESC, AGX, FLR, ECG, LGN"
    }

    col_list1, col_list2 = st.columns([1, 2])
    
    with col_list1:
        selected_list = st.selectbox("Select Watchlist:", list(THEMATIC_LISTS.keys()))
        
    with col_list2:
        if selected_list == "My Custom List":
            active_tickers_str = st.text_input("Watchlist (Comma Separated):", value=THEMATIC_LISTS[selected_list])
        else:
            active_tickers_str = THEMATIC_LISTS[selected_list]
            st.text_input("Tickers in this list:", value=active_tickers_str, disabled=True)
    
    if st.button("🚀 Scan Selected List", type="primary"):
        tickers = [t.strip().upper() for t in active_tickers_str.split(",") if t.strip()]
        
        if not tickers:
            st.warning("No valid tickers found to scan.")
        else:
            with st.spinner(f"Scanning {len(tickers)} tickers across {selected_list}..."):
                try:
                    # 1. Fetch the live prices (Bulk call, very fast)
                    market_data = get_quotes(tickers)
                    
                    ops_data = []
                    for ticker in tickers:
                        if ticker in market_data:
                            quote = market_data[ticker]
                            live_price = quote.get("mark")
                            high_52 = quote.get("52WkHigh")
                            low_52 = quote.get("52WkLow")
                            
                            range_percentile = None
                            status = "Neutral"
                            
                            if live_price and high_52 and low_52 and high_52 > low_52:
                                # Calculate where the current price sits in the 52-week range (0 to 100%)
                                range_percentile = ((live_price - low_52) / (high_52 - low_52)) * 100
                                
                                if range_percentile <= 15:
                                    status = "🔥 Oversold (High IV Proxy)"
                                elif range_percentile >= 85:
                                    status = "🧊 Overbought"
                            
                            ops_data.append({
                                "Ticker": ticker,
                                "Live Price": live_price,
                                "52Wk Low": low_52,
                                "52Wk High": high_52,
                                "Range %": range_percentile, 
                                "Setup Quality": status 
                            })
                    
                    if ops_data:
                        df_ops = pd.DataFrame(ops_data)
                        
                        if "Range %" in df_ops.columns:
                             df_ops = df_ops.sort_values(by="Range %")
                             
                        st.dataframe(
                            df_ops, 
                            column_config={
                                "Live Price": st.column_config.NumberColumn(format="$%.2f"),
                                "52Wk Low": st.column_config.NumberColumn(format="$%.2f"),
                                "52Wk High": st.column_config.NumberColumn(format="$%.2f"),
                                "Range %": st.column_config.ProgressColumn(
                                    "52Wk Range %",
                                    help="0% is the 52-week low. 100% is the 52-week high.",
                                    format="%.1f%%",
                                    min_value=0.0,
                                    max_value=100.0,
                                ),
                            },
                            hide_index=True, 
                            use_container_width=True
                        )
                    else:
                        st.warning("No data returned for the watchlist. Check for typos in tickers.")
                except Exception as e:
                    st.error(f"Scan failed: {e}")