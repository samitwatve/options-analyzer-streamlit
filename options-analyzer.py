# options-analyzer.py

import streamlit as st
import pandas as pd
from datetime import datetime, date
import yfinance as yf

from options_analyzer_core import get_options_data, massage_dataframe, filter_dataframe, format_dataframe

st.set_page_config(layout='wide')
st.title("Options Analyzer")
st.markdown(""" **WARNING!**<br>
                    Using this tool outside market hours may produce unreliable / non-sensical results.<br>
                    **PROCEED WITH CAUTION. YOU HAVE BEEN WARNED!!**<br>
                    For either option type, this calculator assumes that the option is ***held to maturity*** and then ***expires worthless***.<br>
                    Therefore the ***Total return*** and ***Annualized Return*** numbers are ***Return if expired*** [see this](https://tradingmarkets.com/recent/calculating_covered_call_profits_-_not_as_easy_as_it_sounds-754753) for an in-depth discussion.
                    The calculator ***does not*** include the effect of taxes, dividends and transaction costs.
                    """, unsafe_allow_html=True)

option = st.selectbox(
   "Select a Contract Type",
   ("Cash secured put", "Covered Call"),
   index=0
)
st.write('You selected:', option)

if option == "Cash secured put":
   text_block = """
   Cash Secured Puts (CSP) are a strategy where an investor sells a put option and holds enough cash to cover the purchase of the underlying stock if it hits the 
   strike price. The seller earns the premium from selling the put, but is obligated to buy the stock at the strike price if the option is exercised. It's a way to 
   generate income or buy a stock at a discount. The risk is if the stock falls significantly below the strike price, leading to a loss. This strategy requires having 
   enough cash on hand to cover the potential stock purchase."""
elif option == "Covered Call":
   text_block = """
   A covered call is an options strategy where an investor holds a long position in an asset and sells (writes) call options on that same asset. 
   This is done to generate income from the option premium, which the investor collects when selling the call option. The strategy provides some 
   downside protection, as the premium collected can offset declines in the asset's price to an extent. However, it also caps the upside potential 
   since the investor is obligated to sell the asset at the strike price if the call option is exercised. Covered calls can be a conservative strategy 
   to generate additional income on a held asset."""
   
st.markdown(f"<div style='text-align: justify; margin-bottom: 20px;'>{text_block}</div>", unsafe_allow_html=True)

# Get user inputs
col1, col2, col3, col4 = st.columns(4)

with col1:
    min_DTE, max_DTE = st.slider("Days to Expiration (DTE)", 0, 100, (7, 45))

with col2:
    min_annualized_return = st.slider('Minimum Annualized Return (%)', min_value=0, max_value=200, value=20)

if option == "Cash secured put":
    with col3:
        min_stock_drawdown = st.slider('Minimum % Stock Down Move', min_value=0, max_value=100, step=5, value=15)
        st.text(f"You selected {min_stock_drawdown}%")
        st.markdown("""
        e.g., by setting this value to 10, the screener will only look for strike prices ***below*** a 10% fall in the current stock price
        """)
    with col4:
        min_volume = st.slider('Minimum Option Volume', 0, 1000, 10)
elif option == "Covered Call":
    with col3:
        min_stock_upside = st.slider('Minimum % Stock Up Move', min_value=0, max_value=100, step=5, value=15)
        st.markdown("""
        e.g., by setting this value to 10, the screener will only look for strike prices ***above*** a 10% upside in the current stock price
        """)
    with col4:
        min_volume = st.slider('Minimum Option Volume', 0, 1000, 10)

if option == "Covered Call":
    col5 = st.columns(1)[0]
    input_value = col5.text_input('Enter your cost basis for the stock', placeholder='$')

    if input_value:
        try:
            cost_basis = float(input_value)
        except ValueError:
            col5.error('Please enter a valid number for the cost basis.')
            cost_basis = None
    else:
        cost_basis = None

    input_ticker = st.text_input("Enter stock ticker (max 1):", value="AAPL")
    selected_stocks = [input_ticker.strip().upper()]
elif option == "Cash secured put":
    # Set default tickers for CSPs
    default_tickers = ["TQQQ", "UPRO", "GOOG", "NFLX", "TSLA", "NVDA", "META", "AMZN", "AAPL"]
    default_tickers_str = ", ".join(default_tickers)
    tickers_input = st.text_input("Enter one or more tickers (comma-separated):", value=default_tickers_str)
    selected_stocks = [ticker.strip().upper() for ticker in tickers_input.split(",")]

with st.expander("Click here for explanations of each metric"):
    st.markdown("""
    - **Implied Volatility**: The market's forecast of a likely movement in a security's price.
    - **Delta**: Measures the rate of change of the option value with respect to changes in the underlying asset's price.
    - **Gamma**: Measures the rate of change in the delta with respect to changes in the underlying price.
    - **Theta**: Represents the rate of change between the option price and time, or time sensitivity.
    - **Vega**: Measures the sensitivity of the option price to changes in the volatility of the underlying asset.
    - **Probability of Profit**: An estimate of the likelihood that the option will expire out of the money, resulting in a profit for option sellers.
    """)

placeholder = st.empty()

all_options = []
filtered_options = []

for stock in selected_stocks:
    st.text(f"Processing data for {stock}")

    # Get available expiration dates
    ticker = yf.Ticker(stock)
    available_dates = ticker.options

    if not available_dates:
        st.text(f"No available option dates for {stock}")
        continue

    # Keep only those dates within the specified DTE range
    today = date.today()
    dates_to_keep = []
    for dt in available_dates:
        dt_date = datetime.strptime(dt, "%Y-%m-%d").date()
        DTE = (dt_date - today).days
        if DTE >= min_DTE and DTE <= max_DTE:
            dates_to_keep.append(dt)

    if not dates_to_keep:
        st.text(f"No options within the specified DTE range for {stock}")
        continue

    if option == "Cash secured put":
        target_price_multiplier = 1 - (min_stock_drawdown / 100)
        option_type = 'put'
    elif option == "Covered Call":
        target_price_multiplier = 1 + (min_stock_upside / 100)
        option_type = 'call'

    # Get options data
    options_df = get_options_data(stock, option_type, dates_to_keep)

    if options_df.empty:
        st.text(f"No options data available for {stock}")
        continue

    # Process and filter the dataframe
    try:
        if option == "Covered Call":
            if cost_basis is None:
                st.error("Please enter a valid cost basis for the stock.")
                continue
            processed_df = massage_dataframe(
                options_df,
                target_price_multiplier=target_price_multiplier,
                option=option,
                cost_basis=cost_basis
            )
        else:
            # For Cash Secured Put, no need to pass cost_basis
            processed_df = massage_dataframe(
                options_df,
                target_price_multiplier=target_price_multiplier,
                option=option
            )

        filtered_df = filter_dataframe(
            processed_df,
            min_open_interest=10,
            min_annualized_return=min_annualized_return,
            max_DTE=max_DTE,
            min_bid=0.1,
            min_volume=min_volume,
            min_DTE=min_DTE,
            option=option
        )
    except Exception as e:
        st.error(f"Error processing data for {stock}: {e}")
        continue

    st.text(f"Processed {len(processed_df)} options, {len(filtered_df)} remain after filtering")

    if len(filtered_df) > 0:
        filtered_options.append(filtered_df)

if filtered_options:
    display_df = pd.concat(filtered_options)
    display_df = format_dataframe(display_df)
    placeholder.dataframe(display_df)
else:
    st.text("No options meet the criteria.")

st.text(f"Last checked on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
