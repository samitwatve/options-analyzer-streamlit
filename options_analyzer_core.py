# options_analyzer_core.py

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, date
import py_vollib.black_scholes.implied_volatility as iv
import py_vollib.black_scholes.greeks.numerical as greeks
from scipy.stats import norm

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
    df["Midpoint"] = premium_received

    # Calculate Total Return
    if option == "Cash secured put":
        df["Total return"] = premium_received * 100 / df["strike"]
    elif option == "Covered Call":
        if cost_basis is None:
            raise ValueError("Cost basis is required for Covered Call option")
        df["Total return"] = premium_received * 100 / cost_basis

    # Calculate Annualized return
    df["Annualized return"] = round(((1 + df["Total return"] / 100) ** (365 / df["DTE"]) - 1) * 100, 3)

    # Calculate Implied Volatility and Greeks
    df = calculate_iv_and_greeks(df, option)

    # Calculate Probability of Profit
    df = calculate_pop(df, option)

    return df

def calculate_iv_and_greeks(df, option_type):
    """
    Calculates the implied volatility and Greeks for each option in the DataFrame.
    """
    r = 0.01  # Risk-free interest rate (e.g., 1%)
    df['implied_volatility'] = np.nan
    df['delta'] = np.nan
    df['gamma'] = np.nan
    df['theta'] = np.nan
    df['vega'] = np.nan

    for idx, row in df.iterrows():
        S = row['Current price']
        K = row['strike']
        t = row['DTE'] / 365
        flag = 'c' if option_type == 'Covered Call' else 'p'
        option_price = row['Midpoint']

        if t <= 0:
            continue  # Avoid division by zero or negative time to expiration

        try:
            # Calculate Implied Volatility
            iv_value = iv.implied_volatility(option_price, S, K, t, r, flag)
            df.at[idx, 'implied_volatility'] = iv_value

            # Calculate Greeks
            delta = greeks.delta(flag, S, K, t, r, iv_value)
            gamma = greeks.gamma(flag, S, K, t, r, iv_value)
            theta = greeks.theta(flag, S, K, t, r, iv_value)
            vega = greeks.vega(flag, S, K, t, r, iv_value)

            df.at[idx, 'delta'] = delta
            df.at[idx, 'gamma'] = gamma
            df.at[idx, 'theta'] = theta
            df.at[idx, 'vega'] = vega
        except Exception as e:
            # Handle cases where implied volatility calculation fails
            df.at[idx, 'implied_volatility'] = np.nan
            df.at[idx, 'delta'] = np.nan
            df.at[idx, 'gamma'] = np.nan
            df.at[idx, 'theta'] = np.nan
            df.at[idx, 'vega'] = np.nan

    return df

def calculate_pop(df, option_type):
    """
    Calculates the Probability of Profit (POP) for each option.
    """
    if option_type == "Cash secured put":
        # For puts, Delta is negative
        df['POP'] = (1 - norm.cdf(-df['delta'])) * 100
    elif option_type == "Covered Call":
        # For calls, Delta is positive
        df['POP'] = (1 - norm.cdf(df['delta'])) * 100
    else:
        df['POP'] = np.nan
    return df

def filter_dataframe(df, min_open_interest=10, min_annualized_return=20, max_DTE=45, min_bid=0.1, min_volume=10, min_DTE=7, option='Cash secured put'):
    # Ensure implied_volatility, delta, and POP are numeric
    for col in ['implied_volatility', 'delta', 'POP']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    if option == "Cash secured put":
        df = df[
            (df['strike'] <= df["target_prices"]) &
            (df["openInterest"] >= min_open_interest) &
            (df["Annualized return"] >= min_annualized_return) &
            (df["DTE"] <= max_DTE) &
            (df["DTE"] >= min_DTE) &
            (df["bid"] >= min_bid) &
            (df["volume"] >= min_volume)
        ]
    elif option == "Covered Call":
        df = df[
            (df['strike'] >= df["target_prices"]) &
            (df["openInterest"] >= min_open_interest) &
            (df["Annualized return"] >= min_annualized_return) &
            (df["DTE"] <= max_DTE) &
            (df["DTE"] >= min_DTE) &
            (df["bid"] >= min_bid) &
            (df["volume"] >= min_volume)
        ]

    df = df.sort_values(by=["Annualized return", "DTE"], ascending=[False, True])
    return df

def format_dataframe(df):
    df = df[[
        "ticker", "Current price", "target_prices", "strike", "openInterest", "Expiration", "DTE",
        "volume", "lastPrice", "bid", "ask", "implied_volatility", "delta", "gamma", "theta", "vega",
        "POP", "Total return", "Annualized return"
    ]]
    df.columns = [
        "Ticker", "Current Stock Price", "Target Price", "Option Strike", "Option Open Interest",
        "Expiration", "DTE", "Option Volume", "Option Last Price", "Option Bid", "Option Ask",
        "Implied Volatility", "Delta", "Gamma", "Theta", "Vega", "Probability of Profit",
        "Total return", "Annualized return"
    ]
    df = df.reset_index(drop=True)

    # Applies desired formatting for prettier display of dataframe
    mapper = {
        "Current Stock Price": "${:,.2f}",
        "Target Price": "${:,.2f}",
        "Option Strike": "${:,.2f}",
        "Option Last Price": "${:,.2f}",
        "Option Bid": "${:,.2f}",
        "Option Ask": "${:,.2f}",
        "Implied Volatility": "{:.2%}",
        "Delta": "{:.4f}",
        "Gamma": "{:.4f}",
        "Theta": "{:.4f}",
        "Vega": "{:.4f}",
        "Probability of Profit": "{:.2f}%",
        "Total return": "{:.4f}%",
        "Annualized return": "{:.2f}%",
        "Option Volume": "{:.0f}"
    }

    for col, format_spec in mapper.items():
        if col in df.columns:
            df[col] = df[col].apply(lambda x: format_spec.format(x))
    return df
