import streamlit as st
import pandas as pd
import plotly.express as px

# Load raw data and parse the timestamp column into a date-only column
# ISO8601 format is needed because some rows have milliseconds and some don't
df = pd.read_csv('stations.csv')
df['date'] = pd.to_datetime(df['lastUpdated'], format='ISO8601').dt.date

# Aggregate to one average price per company per day
# (multiple stations of the same company can report on the same day)
daily_avg = df.groupby(['date', 'companyName'])['price'].mean().reset_index()

# --- Helper functions ---

# For each day, find which company was cheapest and how much cheaper it was
# compared to the second cheapest — days with less than 2 companies are skipped
def get_cheapest_info(group):
    sorted_group = group.sort_values('price')
    if len(sorted_group) < 2:
        return None
    cheapest = sorted_group.iloc[0]
    second = sorted_group.iloc[1]
    return pd.Series({
        'cheapest_company': cheapest['companyName'],
        'savings': round(second['price'] - cheapest['price'], 4)
    })


# --- App ---

st.set_page_config(layout="wide")
st.title("Gas Station Price Tracker")
st.markdown("Analysis of **Avanti**, **JET** and **DISKONT (HOFER)** fuel prices from October 2022 to October 2024.")

st.subheader("Price over time")
st.markdown("Daily average price per company. Multiple station reports on the same day are averaged.")
fig = px.line(
    daily_avg,
    height=600,
    x='date',
    y='price',
    color='companyName',
    title='Daily Average Gasoline Super Price per Company',
    labels={
        'date': 'Date',
        'price': 'Price (€/L)',
        'companyName': 'Company'
    }
)

st.plotly_chart(fig)

st.subheader("Daily savings: cheapest vs. second cheapest")
st.markdown("How much cheaper the cheapest station was each day compared to the next best option. Color shows which company was cheapest.")
# --- Chart 2: Daily savings ---
cheapest_df = daily_avg.groupby('date').apply(get_cheapest_info).dropna().reset_index()

fig2 = px.bar(
    cheapest_df,
    x='date',
    y='savings',
    color='cheapest_company',
    height=400,
    title='Daily Savings: Cheapest vs. Second Cheapest Station',
    labels={
        'date': 'Date',
        'savings': 'Price Difference (€/L)',
        'cheapest_company': 'Cheapest Company'
    }
)

st.plotly_chart(fig2)

st.subheader("Cheapest station ranking")
st.markdown("Number of days each company had the lowest price.")
# --- Table 1: Cheapest station ranking ---
# Counts how many days each company was the cheapest
cheapest_counts = cheapest_df.groupby('cheapest_company').size().reset_index(name='days_cheapest').sort_values('days_cheapest', ascending=False)
st.dataframe(cheapest_counts, hide_index=True)

st.subheader("Mean price deviation from daily market average")
st.markdown("How much each company's price differs on average from the daily mean across all three companies. Negative = consistently cheaper, positive = consistently more expensive.")
# --- Table 2: Mean deviation from daily average ---
# For each day, calculate the market average price across all companies.
# Then measure how much each company deviates from that average on average.
daily_mean = daily_avg.groupby('date')['price'].mean().rename('daily_mean')
deviation_df = daily_avg.join(daily_mean, on='date')
deviation_df['deviation'] = deviation_df['price'] - deviation_df['daily_mean']
mean_deviation = deviation_df.groupby('companyName')['deviation'].mean().round(4).reset_index()
mean_deviation.columns = ['Company', 'Mean Deviation (€/L)']
mean_deviation = mean_deviation.sort_values('Mean Deviation (€/L)')
st.dataframe(mean_deviation, hide_index=True)

st.subheader("Price volatility per company")
st.markdown("How actively each company changes its price. Includes total number of changes, average change size, and averages split by increases and decreases.")

# Sort by company and date so shift(1) gives the previous day's price for the same company
changes_df = daily_avg.sort_values(['companyName', 'date']).copy()
changes_df['prev_price'] = changes_df.groupby('companyName')['price'].shift(1)
changes_df['change'] = changes_df['price'] - changes_df['prev_price']

# Drop the first row per company (no previous day to compare to)
changes_df = changes_df.dropna(subset=['change'])

# Split into increases and decreases
increases = changes_df[changes_df['change'] > 0]
decreases = changes_df[changes_df['change'] < 0]

volatility = pd.DataFrame({
    'Company': daily_avg['companyName'].unique()
})

# Total number of price changes (any direction)
total_changes = changes_df[changes_df['change'] != 0].groupby('companyName').size()

# Mean absolute change — treats increases and decreases equally (e.g. -0.02 counts as 0.02)
mean_change = changes_df[changes_df['change'] != 0].groupby('companyName')['change'].apply(lambda x: x.abs().mean())

# Mean increase and mean decrease separately
mean_increase = increases.groupby('companyName')['change'].mean()
mean_decrease = decreases.groupby('companyName')['change'].mean()

volatility = pd.concat([total_changes, mean_change, mean_increase, mean_decrease], axis=1).reset_index()
volatility.columns = ['Company', 'Total Changes', 'Mean Change (€/L)', 'Mean Increase (€/L)', 'Mean Decrease (€/L)']
volatility = volatility.round(4).sort_values('Total Changes', ascending=False)

st.dataframe(volatility, hide_index=True)
