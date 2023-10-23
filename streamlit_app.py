from collections import namedtuple
import altair as alt
import math
import streamlit as st
import pandas as pd
import numpy as np
import time
import requests
from datetime import datetime, timedelta
from datetime import date
from yahoo_fin import options
global today
today = date.today()

from yahoo_fin import stock_info as si

from ipywidgets import interact, interactive, fixed, interact_manual
import ipywidgets as widgets
from IPython. display import clear_output
import traceback

# """
# # Welcome to Streamlit!

# Edit `/streamlit_app.py` to customize this app to your heart's desire :heart:

# If you have any questions, checkout our [documentation](https://docs.streamlit.io) and [community
# forums](https://discuss.streamlit.io).

# In the meantime, below is an example of what you can do with just a few lines of code:
# """

# Title
st.set_page_config(layout='wide')
st.title("Cash secured puts calculator")

text_block = """
Cash Secured Puts (CSP) are a strategy where an investor sells a put option and holds enough cash to cover the purchase of the underlying stock if it hits the 
strike price. The seller earns the premium from selling the put, but is obligated to buy the stock at the strike price if the option is exercised. It's a way to 
generate income or buy a stock at a discount. The risk is if the stock falls significantly below the strike price, leading to a loss. This strategy requires having 
enough cash on hand to cover the potential stock purchase.





"""

st.markdown(f"<div style='text-align: justify; margin-bottom: 20px;'>{text_block}</div>", unsafe_allow_html=True)
# Two-sided slider for user input
col1, col2, col3, col4 = st.columns(4)

with col1:
    min_DTE, max_DTE = st.slider("Days to Expiration (DTE)", 1, 100, (7, 45))

with col2:
    min_annualized_return = st.slider('Annualized return', 0, 200, 20)

with col3:
    min_stock_drawdown = st.slider('Minimum % Drawdown', min_value=0, max_value=100, step=5)
    st.markdown("""
    e.g. by setting this value to 10, the screener will only look for strike prices below a 10% fall in the current stock price
    """)
contract_types = ["Covered Call", "Cash secured put"]

# Multiselect dropdown for selecting stocks
selected_stocks = st.multiselect("Select one or more tickers:", list(set(si.tickers_other() + si.tickers_nasdaq())))
#selected_contract_type = st.multiselect("Contract Type", contract_types)

#### Checks if the market is open right now
def is_market_open(nowTime):
    trading_holidays = ["December 25, 2022", "January 2, 2023", "January 16, 2023","February 20, 2023", "April 7, 2023",
                    "May 29, 2023", "June 19, 2023", "July 4, 2023", "September 4, 2023", "November 23, 2023",
                    "November 24, 2023", "December 25, 2023"]

    trading_holidays = [datetime.strptime(dt, "%B %d, %Y").date() for dt in trading_holidays]

    timeStart, timeEnd = "0930", "1600"
    timeStart = datetime.strptime(timeStart, '%H%M').time()
    timeEnd = datetime.strptime(timeEnd, '%H%M').time()

    market_open = False

    if datetime.today().date() not in trading_holidays:
        if datetime.today().weekday() not in [5, 6]:
            if timeStart < nowTime.time() < timeEnd:
                market_open = True

    return(market_open)


### Cleans up the supplied options dataframe and returns some useful values that help pick between different options

def massage_dataframe(df, target_price_multiplier):   
    ## Clean up Expiration column and calculate DTE
    df["Expiration"] = df["Expiration"].apply(lambda x: datetime.strptime(x, "%B %d, %Y").date())  
    df["DTE"] = (df["Expiration"] - today).dt.days

    ## Fix the volume and open interest columns
    for col in ["Volume", "Open Interest", "Bid", "Ask"]:
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].replace(to_replace="-", value=0)
        else:
            df[col] = pd.to_numeric(df[col].str.replace(pat="-", repl="0"))


    ## Get current price
    ticker = df["ticker"].unique()[0]
    df["Current price"] = round(si.get_live_price(ticker), 2)

    ## Get target price
    df["target_prices"] = df["Current price"]*target_price_multiplier

    ## Calculate total return
    midpoint = (df["Ask"] + df["Bid"]) / 2
    df["Total return"] =  midpoint * 100 / df["Strike"]

    ## Calculate Annualized return
    df["Annualized return"] = round(((1 + df["Total return"]/100) ** (365/df["DTE"]) - 1) * 100, 3)

    return(df)

### Further filtering of dataframe to return only the desired options

def filter_dataframe(df, min_open_interest = 10, min_annualized_return = min_annualized_return, max_DTE = max_DTE, min_bid = 0.1, min_volume = 10, min_DTE = min_DTE):
    df = df[(df['Strike'] <= df["target_prices"]) &
            (df["Open Interest"] >= min_open_interest) &
            (df["Annualized return"] >= min_annualized_return) &
            (df["DTE"] <= max_DTE) &
            (df["DTE"] >= min_DTE) &
            (df["Bid"] >= min_bid) &
            (df["Volume"] >= min_volume)]
    df = df.sort_values(by = ["Annualized return", "DTE"], ascending = [False, True])
    return(df)


### Format the display dataframe for cleaner presentation

def format_dataframe(df):
    df = df[["ticker", "Current price", "target_prices", "Strike", "Open Interest", "Expiration", "DTE", "Volume", "Last Price", "Bid", "Ask", "Total return", "Annualized return"]]
    df.columns = ["Ticker", "Current Stock Price", "Target Price", "Option Strike",  "Option Open Interest", "Expiration", "DTE", "Option Volume", "Option Last Price", "Option Bid", "Option Ask", "Total return", "Annualized return"]
    df = df.reset_index(drop = True)

    return(df)

## Applies desired formatting for prettier display of dataframe

mapper =  {"Current Stock Price": "${:20,.2f}",
           "Target Price": "${:20,.2f}",
           "Option Strike": "${:20,.2f}",
           "Option Last Price": "${:20,.2f}",
           "Option Bid": "${:20,.2f}",
           "Option Ask": "${:20,.2f}",
           "Total return": "{:2.4f}%",
           "Annualized return": "{:2.2f}%",
           "Option Volume": "{:2.0f}"}

placeholder = st._legacy_dataframe()
## Run while the market is open
while True:
    all_puts, filtered_puts = [], []

    ## loop through desired stocks
    for stock in selected_stocks:

        ## first get all available dates
        available_dates= options.get_expiration_dates(stock)

        ## keep only those date within the next 45 days
        dates_to_keep = [dt for dt in available_dates if (datetime.strptime(dt, "%B %d, %Y").date() - today).days <= max_DTE]

        st.text(f"processing data for {stock}")


        try:
            ## Get puts for available dates
            for date in dates_to_keep:
                puts = options.get_puts(stock, date)
                puts["ticker"] = stock
                puts["Expiration"] = date
                all_puts.append(puts)

            ## Combine everything into single dataframe
            combined_df = pd.concat(all_puts)
            
            ## Copy this dataframe before modifying.
            ##This is important!! The functions used to modify the dataframe makes changes
            ## such that it becomes problematic to combine datatypes when we pull data for multiple stocks

            temp = pd.DataFrame.copy(combined_df)

            ## Process and filter the dataframe
            processed_df = massage_dataframe(temp, target_price_multiplier = 1 - (min_stock_drawdown/100))
            filtered_df = filter_dataframe(processed_df)
            
            ## If some puts are left over after filtering, we want to display them
            if(len(filtered_df) > 0):

                #clear the previous results
                clear_output(wait=True)

                #Display all the puts we identified for all tickers
                filtered_puts.append(filtered_df)
                display_df = pd.concat(filtered_puts)
                # Display the DataFrame with custom options
                
                display_df = format_dataframe(display_df).sort_values(by= "Annualized return", ascending = False)
                display_df.style.format(mapper).bar(subset=["Annualized return", "DTE", "Option Open Interest"],
                                                               color = "cornflowerblue")
                placeholder.dataframe(display_df)

        except Exception as e:
            st.exception(e)
            st.text(f"Failed to get data for {stock}")
        all_puts = []

    ## Update user on progress
    st.text(f"Last checked on {datetime.now().strftime('%H:%M:%S')}")
    #st.text(f"Next check on {(datetime.now() + timedelta(minutes = 10)).strftime('%H:%M:%S')}")
    break
