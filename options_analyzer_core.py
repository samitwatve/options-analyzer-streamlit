# options_analyzer_core.py

import yfinance as yf
import pandas as pd
from datetime import datetime, date

def get_options_data(ticker, option_type, dates_to_keep):
    """
    Fetches options data for a given ticker, option type, and list of expiration dates.
    """
    all_options = []
    stock = yf.Ticker(ticker)
    for date_str in dates_to_keep:
        try:
            # Fetch options chain for the given expiration date
            option_chain = stock.option_chain(date_str)
            if option_type == 'put':
                options = option_chain.puts
            elif option_type == 'call':
                options = option_chain.calls
            else:
                raise ValueError("option_type must be 'put' or 'call'")
            options['ticker'] = ticker
            options['Expiration'] = date_str
            all_options.append(options)
        except Exception as e:
            print(f"Failed to get data for {ticker} on {date_str}: {e}")
            continue
    if all_options:
        combined_df = pd.concat(all_options, ignore_index=True)
        return combined_df
    else:
        return pd.DataFrame()

# options_analyzer_core.py

def massage_dataframe(df, target_price_multiplier, option, cost_basis=None):
    """
    Processes the options DataFrame to calculate additional metrics.
    """
    # Clean up Expiration column and calculate DTE
    df["Expiration"] = pd.to_datetime(df["Expiration"])
    today = pd.to_datetime(date.today())
    df["DTE"] = (df["Expiration"] - today).dt.days

    # Fix Volume and Open Interest columns
    for col in ["volume", "openInterest", "bid", "ask"]:
        df[col] = df[col].fillna(0)
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Get current price
    ticker = df["ticker"].unique()[0]
    current_price = yf.Ticker(ticker).history(period="1d")['Close'][-1]
    df["Current price"] = round(current_price, 2)

    # Get target price
    df["target_prices"] = df["Current price"] * target_price_multiplier

    # Calculate midpoint
    premium_received = (df["ask"] + df["bid"]) / 2

    if option == "Cash secured put":
        # Calculate total return
        df["Total return"] = premium_received * 100 / df["strike"]
    elif option == "Covered Call":
        if cost_basis is None:
            raise ValueError("Cost basis is required for Covered Call option")
        # Calculate total return
        df["Total return"] = premium_received * 100 / cost_basis

    # Calculate Annualized return
    df["Annualized return"] = round(((1 + df["Total return"] / 100) ** (365 / df["DTE"]) - 1) * 100, 3)

    return df


def filter_dataframe(df, min_open_interest=10, min_annualized_return=20, max_DTE=45, min_bid=0.1, min_volume=10, min_DTE=7, option='Cash secured put'):
    if option == "Cash secured put":
        df = df[(df['strike'] <= df["target_prices"]) &
                (df["openInterest"] >= min_open_interest) &
                (df["Annualized return"] >= min_annualized_return) &
                (df["DTE"] <= max_DTE) &
                (df["DTE"] >= min_DTE) &
                (df["bid"] >= min_bid) &
                (df["volume"] >= min_volume)]
    elif option == "Covered Call":
        df = df[(df['strike'] >= df["target_prices"]) &
                (df["openInterest"] >= min_open_interest) &
                (df["Annualized return"] >= min_annualized_return) &
                (df["DTE"] <= max_DTE) &
                (df["DTE"] >= min_DTE) &
                (df["bid"] >= min_bid) &
                (df["volume"] >= min_volume)]

    df = df.sort_values(by=["Annualized return", "DTE"], ascending=[False, True])
    return df

def format_dataframe(df):
    df = df[["ticker", "Current price", "target_prices", "strike", "openInterest", "Expiration", "DTE", "volume", "lastPrice", "bid", "ask", "Total return", "Annualized return"]]
    df.columns = ["Ticker", "Current Stock Price", "Target Price", "Option Strike", "Option Open Interest", "Expiration", "DTE", "Option Volume", "Option Last Price", "Option Bid", "Option Ask", "Total return", "Annualized return"]
    df = df.reset_index(drop=True)

    # Applies desired formatting for prettier display of dataframe
    mapper = {"Current Stock Price": "${:,.2f}",
              "Target Price": "${:,.2f}",
              "Option Strike": "${:,.2f}",
              "Option Last Price": "${:,.2f}",
              "Option Bid": "${:,.2f}",
              "Option Ask": "${:,.2f}",
              "Total return": "{:.4f}%",
              "Annualized return": "{:.2f}%",
              "Option Volume": "{:.0f}"}

    for col, format_spec in mapper.items():
        if col in df.columns:
            df[col] = df[col].apply(lambda x: format_spec.format(x))
    return df
