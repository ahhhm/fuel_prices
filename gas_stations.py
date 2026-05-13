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

# Aggregate to one row per station: average price over all time + keep location info
station_avg = df.groupby(['id', 'companyName', 'latitude', 'longitude', 'street', 'houseNumber', 'city']).agg(
    avg_price=('price', 'mean')
).reset_index().round({'avg_price': 4})

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


# --- Page routing ---
# st.session_state persists values across reruns of the app.
# We use it to track which page the user is on.
# When a button is clicked, we update session_state.page and call st.rerun()
# to immediately re-render the app showing the new page.

if 'page' not in st.session_state:
    st.session_state.page = 'main'

def go_to(page):
    st.session_state.page = page
    st.rerun()

st.set_page_config(layout="wide")


# ==================== MAP PAGE ====================
if st.session_state.page == 'map':

    if st.button("← Back to Analysis"):
        go_to('main')

    st.title("Station Map")
    st.markdown("""
    All 3 stations plotted on a map, colored by their average price over the full 2-year period.
    Note: all stations are located in **Klagenfurt**, so this shows within-city price differences rather than regional ones.
    Hover over a station to see its address and exact average price.
    """)

    # Each station gets its average price over all time, plotted at its lat/lon
    fig_map = px.scatter_mapbox(
        station_avg,
        lat='latitude',
        lon='longitude',
        color='avg_price',
        size='avg_price',
        hover_name='companyName',
        hover_data={'street': True, 'houseNumber': True, 'avg_price': True, 'latitude': False, 'longitude': False},
        color_continuous_scale='RdYlGn_r',  # red = expensive, green = cheap
        zoom=12,
        height=600,
        mapbox_style='open-street-map',
        title='Average Price per Station',
        labels={'avg_price': 'Avg Price (€/L)'}
    )

    st.plotly_chart(fig_map, use_container_width=True)


# ==================== LEADERSHIP PAGE ====================
elif st.session_state.page == 'leadership':

    if st.button("← Back to Analysis"):
        go_to('main')

    st.title("Price Leadership")
    st.markdown("""
    Which company tends to move first when prices change?
    A **lead event** is when company A changes price but company B does not on that same day.
    A **follow event** is when company B then changes price the very next day.
    A high **follow rate** suggests B consistently reacts to A's moves.
    """)

    changes_df = daily_avg.sort_values(['companyName', 'date']).copy()
    changes_df['prev_price'] = changes_df.groupby('companyName')['price'].shift(1)
    changes_df['change'] = changes_df['price'] - changes_df['prev_price']
    changes_df = changes_df.dropna(subset=['change'])

    pivot = changes_df.pivot(index='date', columns='companyName', values='change').fillna(0)
    pivot_changed = pivot != 0

    companies = pivot_changed.columns.tolist()
    leadership_results = []

    for leader in companies:
        for follower in companies:
            if leader == follower:
                continue
            leader_led = pivot_changed[leader] & ~pivot_changed[follower]
            follower_next_day = pivot_changed[follower].shift(-1)
            follow_events = (leader_led & follower_next_day).sum()
            lead_events = leader_led.sum()
            follow_rate = round(follow_events / lead_events, 3) if lead_events > 0 else 0
            leadership_results.append({
                'Leader': leader,
                'Follower': follower,
                'Lead Events': int(lead_events),
                'Follow Events': int(follow_events),
                'Follow Rate': follow_rate
            })

    leadership_df = pd.DataFrame(leadership_results).sort_values('Follow Rate', ascending=False)
    st.markdown("""
    **How to read the table:**
    - **Leader** — the company that changed its price first
    - **Follower** — the company being watched for a reaction the next day
    - **Lead Events** — number of days where the Leader changed price but the Follower did not
    - **Follow Events** — out of those days, how many times the Follower changed price the very next day
    - **Follow Rate** — Follow Events / Lead Events. A rate of 0.7 means the Follower reacted the next day 70% of the time
    """)
    st.dataframe(leadership_df, hide_index=True)

    heatmap_data = leadership_df.pivot(index='Follower', columns='Leader', values='Follow Rate')
    fig_heat = px.imshow(
        heatmap_data,
        text_auto=True,
        color_continuous_scale='Blues',
        title='Follow Rate Heatmap (how often row follows column)',
        labels={'color': 'Follow Rate'}
    )
    st.plotly_chart(fig_heat, use_container_width=True)


# ==================== OIL PAGE ====================
elif st.session_state.page == 'oil':

    if st.button("← Back to Analysis"):
        go_to('main')

    st.title("Gas Price vs. Brent Oil Price")
    st.markdown("Each price is divided by its historical maximum, so 1.0 = the highest price ever recorded and 0 = true zero. This preserves the relative distance from zero while allowing both curves to be compared on the same scale despite different units (€/L vs. USD/barrel).")

    # Load oil futures and parse date
    oil_df = pd.read_csv('Brent Oil Futures Historical Data.csv')
    oil_df['date'] = pd.to_datetime(oil_df['Date'], format='%m/%d/%Y').dt.date
    oil_df = oil_df[['date', 'Price']].rename(columns={'Price': 'oil_price'})
    oil_df = oil_df.sort_values('date')

    # Forward-fill gaps (weekends, holidays) so every calendar day has a value
    all_dates = pd.DataFrame({'date': pd.date_range(oil_df['date'].min(), oil_df['date'].max()).date})
    oil_df = all_dates.merge(oil_df, on='date', how='left').ffill()

    # Daily mean gas price across all companies
    gas_mean_df = daily_avg.groupby('date')['price'].mean().reset_index().rename(columns={'price': 'gas_price'})
    gas_mean_df['date'] = pd.to_datetime(gas_mean_df['date']).dt.date

    # Merge both on date
    combined = gas_mean_df.merge(oil_df, on='date', how='inner')

    # Store actual min/max before normalizing
    gas_min, gas_max = combined['gas_price'].min(), combined['gas_price'].max()
    oil_min, oil_max = combined['oil_price'].min(), combined['oil_price'].max()

    # Normalize by dividing by the maximum — scale goes from 0 to 1 where 1 = historical max
    # Unlike min-max normalization this preserves the true zero point
    combined['gas_norm'] = combined['gas_price'] / gas_max
    combined['oil_norm'] = combined['oil_price'] / oil_max

    # Show actual ranges
    col1, col2 = st.columns(2)
    col1.markdown(f"**Gas Price Range:** €{gas_min:.3f} – €{gas_max:.3f}/L")
    col2.markdown(f"**Brent Oil Price Range:** USD {oil_min:.2f} – {oil_max:.2f}/barrel")

    # Melt to long format so both lines can share a single color legend
    melted = combined.melt(id_vars='date', value_vars=['gas_norm', 'oil_norm'],
                           var_name='series', value_name='normalized_price')
    melted['series'] = melted['series'].map({'gas_norm': 'Gas Price (€/L)', 'oil_norm': 'Brent Oil (USD/barrel)'})

    fig_oil = px.line(
        melted,
        x='date',
        y='normalized_price',
        color='series',
        height=500,
        title='Gas Price vs. Brent Oil Price (Normalized to Maximum)',
        labels={'date': 'Date', 'normalized_price': 'Price / Maximum (0–1)', 'series': ''}
    )
    st.plotly_chart(fig_oil, use_container_width=True)

    # Resample to weekly means — used by scatter plot and rockets & feathers below
    combined_indexed = combined.set_index(pd.to_datetime(combined['date']))
    weekly = combined_indexed[['gas_norm', 'oil_norm']].resample('W').mean().reset_index()

    st.subheader("Weekly % change: oil vs. gas")
    st.markdown("""
    Each dot is one week. The x-axis shows how much the oil price changed that week, the y-axis shows how much the gas price changed.
    If they move tightly together, dots cluster along the diagonal. The trendline shows the average relationship.
    Dots far from the trendline are weeks where gas and oil moved differently.
    """)

    # Calculate week-over-week % change for both prices using the already-resampled weekly data
    weekly['oil_pct_change'] = weekly['oil_norm'].pct_change() * 100
    weekly['gas_pct_change'] = weekly['gas_norm'].pct_change() * 100

    # Drop the first row (no previous week to compare to) and any NaNs
    scatter_df = weekly.dropna(subset=['oil_pct_change', 'gas_pct_change'])

    fig_scatter = px.scatter(
        scatter_df,
        x='oil_pct_change',
        y='gas_pct_change',
        hover_data={'date': True, 'oil_pct_change': ':.2f', 'gas_pct_change': ':.2f'},
        trendline='ols',
        height=500,
        title='Weekly % Change: Oil vs. Gas Price',
        labels={
            'oil_pct_change': 'Oil Price Change (%)',
            'gas_pct_change': 'Gas Price Change (%)',
            'date': 'Week'
        }
    )

    # Add a reference line at x=0 and y=0 to show the quadrants clearly
    fig_scatter.add_hline(y=0, line_dash='dash', line_color='grey', opacity=0.5)
    fig_scatter.add_vline(x=0, line_dash='dash', line_color='grey', opacity=0.5)

    st.plotly_chart(fig_scatter, use_container_width=True)

    # Correlation coefficient as a summary stat
    corr = scatter_df['oil_pct_change'].corr(scatter_df['gas_pct_change'])
    st.markdown(f"**Pearson correlation of weekly % changes:** {corr:.3f} — {'strong' if abs(corr) > 0.6 else 'moderate' if abs(corr) > 0.3 else 'weak'} {'positive' if corr > 0 else 'negative'} relationship")

    st.subheader("Rolling correlation")
    st.markdown("""
    The Pearson correlation between oil and gas prices calculated over a sliding window.
    A value near **1** means they were moving tightly together during that period.
    A value near **0** means they were decoupled.
    Drops in correlation reveal periods where gas prices stopped following oil.
    """)

    # Use daily data for a smoother rolling window
    # rolling().corr() computes the correlation between two columns over the last N rows
    # We sort by date and assign it as index so rolling() operates in time order,
    # but keep the 'date' column intact so we don't need reset_index()
    combined_daily = combined.copy().sort_values('date')
    combined_daily.index = pd.to_datetime(combined_daily['date'])
    combined_daily['roll_30'] = combined_daily['gas_norm'].rolling(30).corr(combined_daily['oil_norm'])
    combined_daily['roll_60'] = combined_daily['gas_norm'].rolling(60).corr(combined_daily['oil_norm'])

    roll_melted = combined_daily.melt(
        id_vars='date',
        value_vars=['roll_30', 'roll_60'],
        var_name='window',
        value_name='correlation'
    )
    roll_melted['window'] = roll_melted['window'].map({'roll_30': '30-day window', 'roll_60': '60-day window'})

    fig_roll = px.line(
        roll_melted,
        x='date',
        y='correlation',
        color='window',
        height=450,
        title='Rolling Pearson Correlation: Gas vs. Oil Price',
        labels={'date': 'Date', 'correlation': 'Correlation', 'window': 'Window'}
    )
    fig_roll.add_hline(y=0, line_dash='dash', line_color='grey', opacity=0.5)

    st.plotly_chart(fig_roll, use_container_width=True)

    # ---- Lag correlation ----
    st.subheader("Lag correlation: how many days does gas follow oil?")
    st.markdown("""
    For each lag (0–30 days), the oil price is shifted forward by that many days and the correlation with the gas price is computed.
    The **peak** shows the lag at which oil best predicts gas — that's how many days gas typically takes to react to an oil price move.
    """)

    # Shift oil by each lag and compute correlation with gas
    lag_results = []
    for lag in range(0, 31):
        corr = combined_daily['gas_norm'].corr(combined_daily['oil_norm'].shift(lag))
        lag_results.append({'lag_days': lag, 'correlation': round(corr, 4)})

    lag_df = pd.DataFrame(lag_results)
    best_lag = lag_df.loc[lag_df['correlation'].idxmax()]

    fig_lag = px.bar(
        lag_df,
        x='lag_days',
        y='correlation',
        height=400,
        title='Correlation between Oil (shifted) and Gas Price at Different Lags',
        labels={'lag_days': 'Lag (days)', 'correlation': 'Pearson Correlation'},
        color='correlation',
        color_continuous_scale='Blues'
    )
    fig_lag.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig_lag, use_container_width=True)
    st.markdown(f"**Peak lag: {int(best_lag['lag_days'])} days** (correlation: {best_lag['correlation']:.3f}) — gas prices best follow oil with a {int(best_lag['lag_days'])}-day delay.")

    # ---- Rockets and Feathers ----
    st.subheader("Rockets and feathers")
    st.markdown("""
    A classic economics phenomenon: do gas prices **rise faster** when oil goes up than they **fall** when oil goes down?
    Each dot is one week. The box shows the distribution of gas price changes split by whether oil went up or down that week.
    If the "Oil Up" box is higher than the "Oil Down" box is low, prices are asymmetric — rising faster than they fall.
    """)

    # Tag each week by oil direction, then show distribution of gas responses as a box plot
    scatter_df['oil_direction'] = scatter_df['oil_pct_change'].apply(
        lambda x: 'Oil Up' if x > 0 else 'Oil Down'
    )

    fig_rf = px.box(
        scatter_df,
        x='oil_direction',
        y='gas_pct_change',
        color='oil_direction',
        points='all',
        height=450,
        title='Gas Price Response: Oil Up Weeks vs. Oil Down Weeks',
        labels={'oil_direction': '', 'gas_pct_change': 'Gas Price Change (%)'},
        color_discrete_map={'Oil Up': '#e74c3c', 'Oil Down': '#2ecc71'}
    )
    fig_rf.add_hline(y=0, line_dash='dash', line_color='grey', opacity=0.5)
    st.plotly_chart(fig_rf, use_container_width=True)

    # Summary stats for the two groups
    up_mean = scatter_df[scatter_df['oil_direction'] == 'Oil Up']['gas_pct_change'].mean()
    down_mean = scatter_df[scatter_df['oil_direction'] == 'Oil Down']['gas_pct_change'].mean()
    col1, col2 = st.columns(2)
    col1.markdown(f"**Average gas change when oil goes up:** +{up_mean:.3f}%")
    col2.markdown(f"**Average gas change when oil goes down:** {down_mean:.3f}%")


# ==================== MAIN PAGE ====================
else:

    st.title("Gas Station Price Tracker")
    st.markdown("Analysis of **Avanti**, **JET** and **DISKONT (HOFER)** fuel prices from October 2022 to October 2024.")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("View Station Map →"):
            go_to('map')
    with col2:
        if st.button("View Price Leadership →"):
            go_to('leadership')
    with col3:
        if st.button("View Oil vs. Gas →"):
            go_to('oil')

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

    st.subheader("Daily spread: cheapest vs. most expensive")
    st.markdown("The price difference between the cheapest and most expensive station each day. A larger spread means more potential savings from choosing the right station.")

    # Still needed for the ranking table below
    cheapest_df = daily_avg.groupby('date').apply(get_cheapest_info).dropna().reset_index()

    # For each day, calculate the spread between the min and max price across all companies
    spread_df = daily_avg.groupby('date').agg(
        cheapest=('price', 'min'),
        most_expensive=('price', 'max')
    ).reset_index()
    spread_df['spread'] = (spread_df['most_expensive'] - spread_df['cheapest']).round(4)

    fig2 = px.line(
        spread_df,
        x='date',
        y='spread',
        height=400,
        title='Daily Price Spread: Cheapest vs. Most Expensive Station',
        labels={
            'date': 'Date',
            'spread': 'Price Spread (€/L)'
        }
    )
    st.plotly_chart(fig2)

    st.subheader("Cheapest station ranking")
    st.markdown("Number of days each company had the lowest price.")
    cheapest_counts = cheapest_df.groupby('cheapest_company').size().reset_index(name='days_cheapest').sort_values('days_cheapest', ascending=False)
    st.dataframe(cheapest_counts, hide_index=True)

    st.subheader("Mean price deviation from daily market average")
    st.markdown("How much each company's price differs on average from the daily mean across all three companies. Negative = consistently cheaper, positive = consistently more expensive.")
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

