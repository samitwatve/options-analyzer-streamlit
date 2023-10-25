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
st.title("Options Analyzer")
st.markdown(""" **WARNING!**<br>
                Using this tool outside market hours may produce unreliable / non-sensical results.<br>
                **PROCEED WITH CAUTION. YOU HAVE BEEN WARNED!!**<br>
                For either option type, this calculator assumes that the option is ***held to maturity*** and then ***expires worthless***.<br>
                Therefore the ***Total return*** and ***Annualized Return*** numbers are ***Return if expired*** [see this](https://tradingmarkets.com/recent/calculating_covered_call_profits_-_not_as_easy_as_it_sounds-754753) for an in-depth discussion
                The calculator ***does not*** include the effect of taxes, dividends and transaction costs.
                """, unsafe_allow_html=True)
text_block = None

option = st.selectbox(
   "Select a Contract Type",
   ("Cash secured put", "Covered Call"),
   index=0,
   placeholder="Cash secured put"
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
# Two-sided slider for user input
col1, col2, col3, col4 = st.columns(4)

with col1:
    min_DTE, max_DTE = st.slider("Days to Expiration (DTE)", 0, 100, (7, 45))

with col2:
    min_annualized_return = st.slider('Minimum Annualized return', min_value=0, max_value=200, value=20)
if option == "Cash secured put":
   with col3:
       min_stock_drawdown = st.slider('Minimum % Stock down move', min_value=0, max_value=100, step=5, value=15)
       st.text(f"You selected {min_stock_drawdown}")
       st.markdown("""
       e.g. by setting this value to 10, the screener will only look for strike prices ***below*** a 10% fall in the current stock price
       """)
elif option == "Covered Call":
   with col3:
      min_stock_upside = st.slider('Minimum % stock up move', min_value=0, max_value=100, step=5, value=15)
      st.markdown("""
      e.g. by setting this value to 10, the screener will only look for strike prices ***above*** a 10% upside in the current stock price
      """)
with col4:
    min_volume = st.slider('Minimum Option Volume', 0, 1000, 10)

if option == "Covered Call":
    col5, = st.columns(1)
    
    input_value = col5.text_input('Enter your cost basis for the stock', placeholder='$')

    if input_value:
        try:
            cost_basis = float(input_value)
        except ValueError:
            col5.error('Please enter a valid number for the cost basis.')
            cost_basis = None  # or another appropriate fallback value
    else:
        cost_basis = None  # or another appropriate fallback value

    # Multiselect dropdown for selecting stocks
    selected_stocks = st.multiselect(
        "Select stock ticker (max 1):", 
        options=list(set(si.tickers_other() + si.tickers_nasdaq())), 
        default=["TQQQ"], 
        max_selections=1
    )
elif option == "Cash secured put":
    # Multiselect dropdown for selecting stocks
    selected_stocks = st.multiselect(
        "Select one or more tickers (max 5):", 
        options=list(set(si.tickers_other() + si.tickers_nasdaq())), 
        default=["TQQQ"], 
        max_selections=5
    )



#### Checks if the market is open right now
def is_market_open(nowTime):
    trading_holidays = ["November 23, 2023", "November 24, 2023", "December 25, 2023", "January 1, 2024", "January 15, 2024", "February 19, 2024", "March 29, 2024", "May 27, 2024"
                       "June 19, 2024","July 4, 2024","September 2, 2024","November 28, 2024", "December 25, 2024"]

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

def massage_dataframe(df, target_price_multiplier, option, cost_basis = None):   
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

    ## Calculate midpoint
    premium_recieved = (df["Ask"] + df["Bid"]) / 2
   
    if option == "Cash secured put":
       ## Calculate total return
       df["Total return"] =  premium_recieved * 100 / df["Strike"]
          
    elif option == "Covered Call":
       ## Calculate total return
       df["Total return"] =  premium_recieved * 100 / cost_basis
      
    ## Calculate Annualized return
    df["Annualized return"] = round(((1 + df["Total return"]/100) ** (365/df["DTE"]) - 1) * 100, 3)
       
    return(df)

### Further filtering of dataframe to return only the desired options

def filter_dataframe(df, min_open_interest = 10, min_annualized_return = min_annualized_return, max_DTE = max_DTE, min_bid = 0.1, min_volume = min_volume, min_DTE = min_DTE, option = option):
    
    if option == "Cash secured put":
        df = df[(df['Strike'] <= df["target_prices"]) &
             (df["Open Interest"] >= min_open_interest) &
             (df["Annualized return"] >= min_annualized_return) &
             (df["DTE"] <= max_DTE) &
             (df["DTE"] >= min_DTE) &
             (df["Bid"] >= min_bid) &
             (df["Volume"] >= min_volume)]
    elif option == "Covered Call":
        df = df[(df['Strike'] >= df["target_prices"]) &
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

    for col, format_spec in mapper.items():
     if col in df.columns:
         df[col] = df[col].apply(lambda x: format_spec.format(x))
    return(df)

placeholder = st._legacy_dataframe()

## Run while the market is open

if option == "Cash secured put":
   all_puts, filtered_puts = [], []

elif option == "Covered Call":
   all_calls, filtered_calls = [], []
   
## loop through desired stocks
for stock in selected_stocks:

    ## first get all available dates
    available_dates= options.get_expiration_dates(stock)

    ## keep only those date within the next 45 days
    dates_to_keep = [dt for dt in available_dates if (datetime.strptime(dt, "%B %d, %Y").date() - today).days <= max_DTE]
    
    if option == "Cash secured put":
        st.text(f"processing data for {stock}")
        target_price_multiplier = 1 - (min_stock_drawdown/100)

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
           ## This is important!! The functions used to modify the dataframe makes changes
           ## such that it becomes problematic to combine datatypes when we pull data for multiple stocks

           temp = pd.DataFrame.copy(combined_df)

           ## Process and filter the dataframe
           processed_df = massage_dataframe(temp, target_price_multiplier = target_price_multiplier, option = option)
           filtered_df = filter_dataframe(processed_df)
           st.text(f"Processed {len(processed_df)} puts, {len(filtered_df)} remain after filtering")
           
           ## If some puts are left over after filtering, we want to display them
           if(len(filtered_df) > 0):

               # clear the previous results
               clear_output(wait=True)

               # Display all the puts we identified for all tickers
               filtered_puts.append(filtered_df)
               display_df = pd.concat(filtered_puts)
               # Display the DataFrame with custom options
               
               display_df = format_dataframe(display_df).sort_values(by= "Annualized return", ascending = False)
               #display_df.style.format(mapper).bar(subset=["Annualized return", "DTE", "Option Open Interest"],
               #                                   color = "cornflowerblue")
               placeholder.dataframe(display_df)

        except Exception as e:
           st.exception(e)
           st.text(f"Failed to get data for {stock}")
        all_puts = []


    elif option == "Covered Call":
        st.text(f"processing data for {stock}")
        target_price_multiplier = 1 + (min_stock_upside/100)
     
        try:
           ## Get puts for available dates
           for date in dates_to_keep:
               calls = options.get_calls(stock, date)
               calls["ticker"] = stock
               calls["Expiration"] = date
               all_calls.append(calls)
               
           ## Combine everything into single dataframe
           combined_df = pd.concat(all_calls)
           
           ## Copy this dataframe before modifying.
           ## This is important!! The functions used to modify the dataframe makes changes
           ## such that it becomes problematic to combine datatypes when we pull data for multiple stocks
           
           temp = pd.DataFrame.copy(combined_df)
           
           ## Process and filter the dataframe
           processed_df = massage_dataframe(temp, target_price_multiplier = target_price_multiplier, option = option, cost_basis = cost_basis)
           filtered_df = filter_dataframe(processed_df)
           st.text(f"Processed {len(processed_df)} calls, {len(filtered_df)} remain after filtering")
           
           ## If some puts are left over after filtering, we want to display them
           if(len(filtered_df) > 0):
               
               # clear the previous results
               clear_output(wait=True)
               
               # Display all the puts we identified for all tickers
               filtered_calls.append(filtered_df)
               display_df = pd.concat(filtered_calls)
               display_df = format_dataframe(display_df).sort_values(by= "DTE", ascending = True)
               #display(display_df.style.format(mapper).bar(subset=["Annualized return", "DTE", "Option Open Interest"], 
               #                                        color = "cornflowerblue"))
               placeholder.dataframe(display_df)
        
        except Exception as e:
           st.exception(e)
           st.text(f"Failed to get data for {stock}")
        all_calls = []

if not option == None:
    ## Update user on progress
    st.text(f"Last checked on {datetime.now().strftime('%H:%M:%S')}")
    #st.text(f"Next check on {(datetime.now() + timedelta(minutes = 10)).strftime('%H:%M:%S')}")

